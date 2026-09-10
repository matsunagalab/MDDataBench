"""Reproducible multi-attempt benchmark campaigns.

The campaign layer deliberately contains no scientific code.  It records what
an agent was shown, captures harness and scheduler events, turns every terminal
attempt into a binary result, and rebuilds paper tables from immutable per-run
files.  The deterministic scorer remains the only authority on MD fidelity.
"""

from __future__ import annotations

import csv
import hashlib
import json
import math
import os
import re
import shlex
import shutil
import subprocess
import sys
import tempfile
import time
from collections import Counter, defaultdict
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
from pathlib import Path

from .attempt_diagnostics import diagnose, gpu_totals, measured, read_record
from .recovery import recovery_report
from .slurm_binds import discover_slurm_binds
from .transcript import (error_codes, iter_calls, mdclaw_results, skill_reads, timeline,
                         token_usage)


CONDITIONS = frozenset({"cli_skill_sif", "cli_sif", "sif_only"})
# How a CLI attempt reaches MDClaw. ``overlay`` freezes a checkout and imports
# it through PYTHONPATH inside the SIF; ``image`` runs only the package baked
# into the SIF, so an attempt needs nothing but its skills and the image.
SOURCE_MODES = frozenset({"overlay", "image"})
PASS_RULE = "all_weighted_checks_pass"
TERMINAL_SLURM_STATES = frozenset({
    "COMPLETED", "FAILED", "CANCELLED", "TIMEOUT", "OUT_OF_MEMORY",
    "NODE_FAIL", "PREEMPTED", "BOOT_FAIL", "DEADLINE",
})


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _json(path: Path) -> dict:
    return json.loads(path.read_text())


def _write_json(path: Path, value) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile("w", dir=path.parent, delete=False) as handle:
        json.dump(value, handle, indent=2, sort_keys=True)
        handle.write("\n")
        temporary = Path(handle.name)
    temporary.replace(path)


def _append_event(attempt_dir: Path, event: str, **fields) -> dict:
    row = {"at": _now(), "event": event, **fields}
    with (attempt_dir / "events.jsonl").open("a") as handle:
        handle.write(json.dumps(row, sort_keys=True) + "\n")
    return row


def _slug(value: str) -> str:
    slug = re.sub(r"[^A-Za-z0-9_.-]+", "-", value).strip("-.").lower()
    if not slug:
        raise ValueError(f"cannot make a safe identifier from {value!r}")
    return slug


def _git_revision(path: Path) -> str | None:
    try:
        return subprocess.run(
            ["git", "-C", str(path), "rev-parse", "HEAD"], check=True,
            text=True, capture_output=True, timeout=10,
        ).stdout.strip()
    except (OSError, subprocess.SubprocessError):
        return None


FROZEN_SOURCE_EXCLUDES = (
    ".git", "__pycache__", ".pytest_cache", ".ruff_cache", ".mypy_cache",
    ".mdclaw_cache", "node_modules", ".venv",
    # Images are passed as dependencies, not imported as source. The laboratory
    # checkout keeps its 5.2 GB image at the source root.
    "*.sif", "*.sif.*",
    # Run output that happens to live inside the checkout. What is frozen is
    # the source an attempt imports; a study workspace is data. Measured
    # 2026-08-27: a checkout carrying 37 GB of trajectories under `studies/`
    # was copied whole into the experiment and then hashed file by file, which
    # exhausted the 1 TB project quota before the first attempt dispatched.
    "studies", "runs", "outputs", "benchmark_runs",
)


def _freeze_source(src: Path, dest: Path) -> dict:
    """Copy a source checkout into the experiment and take write access away.

    An attempt reaches MDClaw through CLAUDE_PLUGIN_ROOT and PYTHONPATH, which
    pointed at the operator's live checkout: an agent that decided MDClaw had a
    bug could edit the package it was being measured against, and every later
    attempt in the campaign inherited the edit. Measured 2026-08-25, one did.
    The same aliasing cuts the other way -- the operator cannot touch the
    checkout while a campaign runs without perturbing it.

    The frozen copy is what the campaign runs, and the digest recorded here is
    what the numbers belong to. Directories lose write permission as well as
    files, because a writable directory still allows creating and replacing
    entries inside it.
    """
    revision = _git_revision(src)
    dirty = None
    try:
        dirty = bool(subprocess.run(
            ["git", "-C", str(src), "status", "--porcelain"], check=True,
            text=True, capture_output=True, timeout=30).stdout.strip())
    except (OSError, subprocess.SubprocessError):
        pass
    shutil.copytree(src, dest,
                    ignore=shutil.ignore_patterns(*FROZEN_SOURCE_EXCLUDES),
                    symlinks=True)
    digest, files = hashlib.sha256(), 0
    for path in sorted(p for p in dest.rglob("*") if p.is_file() and not p.is_symlink()):
        digest.update(str(path.relative_to(dest)).encode())
        digest.update(path.read_bytes())
        files += 1
    for path in sorted(dest.rglob("*"), key=lambda p: len(p.parts), reverse=True):
        if path.is_symlink():
            continue
        path.chmod(path.stat().st_mode & ~0o222)
    dest.chmod(dest.stat().st_mode & ~0o222)
    return {"origin": str(src), "frozen": str(dest), "revision": revision,
            "origin_dirty": dirty, "files": files,
            "tree_sha256": digest.hexdigest()}


def _probe_image(sif: Path, sha256: str | None = None) -> dict:
    """Identify the MDClaw package an image-mode attempt will run.

    The module path is what the sbatch shim's runtime check compares against,
    and the digest is what the campaign's numbers belong to, in place of the
    frozen tree digest of overlay mode.
    """
    sif = sif.resolve()
    if not sif.is_file():
        raise ValueError(f"sif is not a file: {sif}")
    runtime = shutil.which("singularity") or shutil.which("apptainer")
    if not runtime:
        raise ValueError("image mode needs singularity or apptainer on the submission host")
    probe = ("import sys; sys.path = [p for p in sys.path if p]; import mdclaw; "
             "from pathlib import Path; print(Path(mdclaw.__file__).resolve()); "
             "print(getattr(mdclaw, '__version__', ''))")
    completed = subprocess.run(
        [runtime, "exec", "--env", "PYTHONPATH=", "--env", "PYTHONHOME=", str(sif),
         "python", "-c", probe], text=True, capture_output=True, timeout=900, check=False)
    if completed.returncode:
        raise ValueError(f"could not import mdclaw from {sif}: {completed.stderr.strip()[-500:]}")
    module, _, version = completed.stdout.strip().partition("\n")
    return {"sif": str(sif), "sha256": sha256 or _sha256(sif),
            "mdclaw_module": module.strip(), "mdclaw_version": version.strip() or None}


RUNTIME_PACKAGES = ("openmm", "openmmforcefields", "openff-toolkit", "pdbfixer", "parmed",
                    "mdtraj", "MDAnalysis", "numpy", "scipy", "rdkit", "pymbar", "ambertools")
RUNTIME_EXECUTABLES = ("tleap", "pdb4amber", "antechamber", "parmchk2", "cpptraj", "packmol",
                       "packmol-memgen", "reduce", "obabel", "gmx", "hole")
_RUNTIME_PROBE = """import json, shutil, sys
from importlib import metadata
packages = {}
for name in %r:
    try:
        packages[name] = metadata.version(name)
    except metadata.PackageNotFoundError:
        pass
executables = [name for name in %r if shutil.which(name)]
try:
    import mdclaw
    mdclaw_present = True
except ImportError:
    mdclaw_present = False
print(json.dumps({"python": sys.version.split()[0], "packages": packages,
                  "executables": executables, "mdclaw_present": mdclaw_present}))
""" % (RUNTIME_PACKAGES, RUNTIME_EXECUTABLES)


def _probe_runtime(runtime_sif: Path, sha256: str | None = None) -> dict:
    """Inventory a `sif_only` runtime image from inside the image itself.

    The inventory is environment documentation for the agent, generated
    rather than hand-written so it cannot drift from the image, and the
    probe doubles as the content check that the image carries no MDClaw.
    """
    runtime_sif = runtime_sif.resolve()
    if not runtime_sif.is_file():
        raise ValueError(f"runtime_sif is not a file: {runtime_sif}")
    runtime = shutil.which("singularity") or shutil.which("apptainer")
    if not runtime:
        raise ValueError("probing a runtime image needs singularity or apptainer")
    completed = subprocess.run(
        [runtime, "exec", "--env", "PYTHONPATH=", "--env", "PYTHONHOME=", str(runtime_sif),
         "python", "-c", _RUNTIME_PROBE], text=True, capture_output=True, timeout=900, check=False)
    if completed.returncode:
        raise ValueError(f"could not probe {runtime_sif}: {completed.stderr.strip()[-500:]}")
    inventory = json.loads(completed.stdout.strip().splitlines()[-1])
    if inventory.get("mdclaw_present"):
        raise ValueError(f"sif_only runtime_sif must not contain MDClaw: {runtime_sif}")
    return {"runtime_sif": str(runtime_sif), "sha256": sha256 or _sha256(runtime_sif),
            "python": inventory.get("python"), "packages": inventory.get("packages") or {},
            "executables": inventory.get("executables") or []}


def _runtime_capabilities(record: dict) -> list[str]:
    packages = ", ".join(f"{name} {version}" for name, version in record["packages"].items())
    executables = ", ".join(record["executables"]) or "none of the probed names"
    return [
        f"Runtime SIF: {record['runtime_sif']} (sha256 {record['sha256']})",
        f"Runtime contents, probed from the image at campaign setup and listed as documentation, "
        f"not as a recommendation: python {record['python']}; {packages}",
        f"Runtime executables on PATH inside the image: {executables}",
        f"Run it as: singularity exec --env PYTHONPATH= --env PYTHONHOME= {record['runtime_sif']} "
        "python ...   (add --nv inside a GPU allocation for OpenMM CUDA)",
    ]


def _version(command: str) -> str | None:
    try:
        return subprocess.run(
            [command, "--version"], check=False, text=True, capture_output=True,
            timeout=10,
        ).stdout.strip() or None
    except (OSError, subprocess.SubprocessError):
        return None


def _harness_version(harness: str) -> str | None:
    """Resolve public harness names to their executable names."""
    return _version("claude" if harness == "claude-code" else harness)


def _image_mode(cell: dict) -> bool:
    return cell.get("condition") != "sif_only" and cell.get("source_mode") == "image"


def _harness_executable(harness: str) -> str:
    command = "claude" if harness == "claude-code" else harness
    return shutil.which(command) or command


def _task_paths(dataset_dir: Path, task_id: str) -> tuple[Path, Path, dict]:
    root = dataset_dir / "tasks" / task_id
    task_file, prompt_file = root / "task.json", root / "prompt.md"
    if not task_file.is_file() or not prompt_file.is_file():
        raise ValueError(f"{task_id}: task.json or prompt.md is missing under {root}")
    task = _json(task_file)
    if task.get("task_id") != task_id:
        raise ValueError(f"{task_id}: task.json declares {task.get('task_id')!r}")
    return task_file.resolve(), prompt_file.resolve(), task


def _normalise_spec(spec: dict, experiment_dir: Path, dataset_dir: Path) -> dict:
    cells = spec.get("cells") or []
    tasks = spec.get("tasks") or []
    if not cells or not tasks:
        raise ValueError("the experiment spec needs non-empty tasks and cells")
    replicates = int(spec.get("replicates", 3))
    if replicates < 1:
        raise ValueError("replicates must be positive")
    agent_timeout = int(spec.get("agent_timeout_seconds", 1200))
    md_time_limit = str(spec.get("md_time_limit", "00:20:00"))
    if agent_timeout < 1:
        raise ValueError("agent_timeout_seconds must be positive")
    if not re.fullmatch(r"[0-9:-]+", md_time_limit):
        raise ValueError("md_time_limit must be a Slurm time value")
    normal_cells = []
    for cell in cells:
        condition = str(cell.get("condition") or "")
        if condition not in CONDITIONS:
            raise ValueError(f"unknown condition {condition!r}; choose {sorted(CONDITIONS)}")
        harness, model = str(cell.get("harness") or ""), str(cell.get("model") or "")
        if not harness or not model:
            raise ValueError("every cell needs harness and fully-qualified model")
        skill_source = str(cell.get("skill_source") or "frozen_source")
        if skill_source not in {"frozen_source", "user"}:
            raise ValueError("skill_source must be frozen_source or user")
        if skill_source == "user" and harness != "pi":
            raise ValueError("user skill_source is supported only for pi")
        cell_limit = str(cell.get("md_time_limit") or md_time_limit)
        if not re.fullmatch(r"[0-9:-]+", cell_limit):
            raise ValueError("cell md_time_limit must be a Slurm time value")
        source_mode = str(cell.get("source_mode") or spec.get("source_mode") or "overlay")
        if source_mode not in SOURCE_MODES:
            raise ValueError(f"source_mode must be one of {sorted(SOURCE_MODES)}, "
                             f"got {source_mode!r}")
        skills_dir = cell.get("skills_dir") or spec.get("skills_dir")
        if skills_dir and not Path(skills_dir).is_dir():
            raise ValueError(f"skills_dir is not a directory: {skills_dir}")
        if condition != "sif_only":
            if not (cell.get("sif") or spec.get("sif")):
                raise ValueError(f"{condition} requires sif")
            if source_mode == "image":
                if cell.get("mdclaw_source") or cell.get("mdclaw_cli"):
                    raise ValueError("image mode takes the CLI from the SIF; remove "
                                     "mdclaw_source and mdclaw_cli from the cell")
                if condition == "cli_skill_sif" and skill_source != "user" and not skills_dir:
                    raise ValueError("image mode cli_skill_sif needs skill_source=user "
                                     "(pi) or a skills_dir")
            else:
                if not (cell.get("mdclaw_cli") or spec.get("mdclaw_cli")):
                    raise ValueError(f"{condition} requires mdclaw_cli")
                source = cell.get("mdclaw_source") or spec.get("mdclaw_source")
                if not source:
                    raise ValueError(f"{condition} requires mdclaw_source for the SIF overlay")
                if not Path(source).is_dir():
                    raise ValueError(f"mdclaw_source is not a directory: {source}")
        if condition == "sif_only" and not (cell.get("runtime_sif") or spec.get("runtime_sif")):
            raise ValueError("sif_only requires a runtime_sif that does not contain MDClaw")
        if condition == "sif_only":
            runtime = Path(cell.get("runtime_sif") or spec["runtime_sif"]).resolve()
            full = cell.get("sif") or spec.get("sif")
            if full and runtime == Path(full).resolve():
                raise ValueError("sif_only runtime_sif must differ from the MDClaw SIF")
        inventory = cell.get("runtime_inventory", spec.get("runtime_inventory", True))
        if not isinstance(inventory, bool):
            raise ValueError("runtime_inventory must be true or false")
        normal_cells.append({**cell, "condition": condition, "harness": harness,
                             "model": model, "skill_source": skill_source,
                             "source_mode": source_mode, "skills_dir": skills_dir,
                             "runtime_inventory": inventory})
    return {
        **spec,
        "schema_version": 1,
        "experiment_id": str(spec.get("experiment_id") or experiment_dir.name),
        "dataset_dir": str(dataset_dir.resolve()),
        "replicates": replicates,
        "agent_timeout_seconds": agent_timeout,
        "md_time_limit": md_time_limit,
        "pass_rule": PASS_RULE,
        "tasks": [str(task) for task in tasks],
        "cells": normal_cells,
    }


def _agent_instructions(condition: str, agent_timeout_seconds: int,
                        md_time_limit: str) -> str:
    # Paths are relative to the workspace, which is already the agent's working
    # directory. Naming it again - "workspace/study" - reads as a subdirectory
    # to create, and agents duly created workspace/workspace/study.
    destination = ("study/jobs/main, the completed MDClaw schema-v3 job that "
                   "`mdclaw bootstrap_md_workflow --study-dir study` creates "
                   "in this directory"
                   if condition != "sif_only" else
                   "workspace/submission using the portable layout in PORTABLE_SUBMISSION.md")
    return f"""
This is one independent MDDataBench attempt. Work autonomously and do not ask
for human help. Do not search for or read task.json, reference bundles, prior
attempts, scorer output, or hidden benchmark data. Use only the public task
below and the capabilities exposed in this workspace.

Do structure acquisition and preparation on the login node. Run all molecular
dynamics computation through Slurm, using sbatch; compute nodes may not have
Internet access. Before exiting, submit the final MD work and leave the
submission at {destination}. The evaluator, not you, will run the scorer.
Your final sbatch invocation must be the final MD job for this attempt; the
evaluation harness records that job and attaches its scorer with afterany.

This attempt ends at submission. Submit the MD stages as one dependency chain
-- each stage held by `afterok` on the one before it -- and then exit. Do not
wait for a stage to finish before submitting the next, and do not poll squeue
or the job state: queue time and Slurm run time are outside your wall-clock
limit, but time spent waiting for them is not.

Operational limits: the agent session has a hard {agent_timeout_seconds} s
wall-clock limit for structure acquisition, preparation, topology construction,
and final Slurm submission. Each MD Slurm job has a hard {md_time_limit}
wall-time limit.

These operational limits do not relax the scientific requirements. Do not
shorten the requested minimum production duration or alter the requested force
field, solvent, ensemble, temperature, or pressure to fit the limits.
Put ad-hoc logs and temporary files under `$TMPDIR`; never use a fixed
`/tmp/<name>` shared with other attempts.
""".strip()


PORTABLE_LAYOUT = """# Portable MDDataBench submission

Condition `sif_only` has no MDClaw CLI.  Put these files under `submission/`:

```
prepared.pdb
system.topology.pdb
system.system.xml
system.state.xml
amber_metadata.json
minimized_structure.pdb
minimized.xml
trajectory.dcd
energy.dat
production.json
```

`production.json` records at least `simulation_time_ns`, `temperature_kelvin`,
`pressure_bar`, `timestep_fs`, `output_frequency_ps`, and `system_signature`
with `ensemble` and `pressure_bar`. `amber_metadata.json` records
`parameters.water_model` and `forcefield_provenance.openmm_xml`, the latter as
a list of OpenMM XML files. Paths are fixed; no benchmark reference is needed
or permitted. The evaluator converts this portable layout to its internal
read-only scoring view.
"""


def init_experiment(experiment_dir: str, spec_file: str,
                    dataset_dir: str = "benchmarks/mddatabench") -> dict:
    """Create immutable manifests and isolated workspaces for a campaign."""
    root = Path(experiment_dir).resolve()
    source_tree = Path(__file__).resolve().parents[1]
    if root == source_tree or source_tree in root.parents:
        raise ValueError(
            "experiment directory must be outside the MDDataBench source "
            f"checkout ({source_tree}): {root}"
        )
    if root.exists() and any(root.iterdir()):
        raise ValueError(f"experiment directory is not empty: {root}")
    spec_path, dataset = Path(spec_file).resolve(), Path(dataset_dir).resolve()
    spec = _normalise_spec(_json(spec_path), root, dataset)
    root.mkdir(parents=True, exist_ok=True)

    # Freeze every MDClaw checkout the spec names, and run the campaign against
    # the frozen copy. See _freeze_source.
    frozen: dict[str, dict] = {}
    for cell in spec["cells"]:
        source = cell.get("mdclaw_source") or spec.get("mdclaw_source")
        if not source or _image_mode(cell):
            continue
        origin = Path(source).resolve()
        if str(origin) in frozen:
            continue
        dest = root / "frozen-source" / f"mdclaw-{len(frozen)}"
        dest.parent.mkdir(parents=True, exist_ok=True)
        frozen[str(origin)] = _freeze_source(origin, dest)

    # Image-mode cells run the SIF's own package: identify it once per image
    # and gather the host resources its Slurm tools need inside the container.
    images: dict[str, dict] = {}
    for cell in spec["cells"]:
        sif = cell.get("sif") or spec.get("sif")
        if not _image_mode(cell) or not sif or sif in images:
            continue
        images[sif] = _probe_image(Path(sif), cell.get("sif_sha256") or spec.get("sif_sha256"))
    container_binds = spec.get("container_binds")
    if images and container_binds is None:
        container_binds = discover_slurm_binds(str(root / "host-binds"))
    runtimes: dict[str, dict] = {}
    for cell in spec["cells"]:
        runtime_sif = cell.get("runtime_sif") or spec.get("runtime_sif")
        if cell["condition"] != "sif_only" or not cell["runtime_inventory"] or runtime_sif in runtimes:
            continue
        runtimes[runtime_sif] = _probe_runtime(
            Path(runtime_sif), cell.get("runtime_sif_sha256") or spec.get("runtime_sif_sha256"))

    _write_json(root / "experiment.json", {
        **spec, "created_at": _now(), "spec_sha256": _sha256(spec_path),
        "mddatabench_revision": _git_revision(Path(__file__).resolve().parents[1]),
        "frozen_sources": list(frozen.values()),
        "images": list(images.values()),
        "runtime_images": list(runtimes.values()),
        "container_binds": container_binds,
    })

    attempts = []
    for task_id in spec["tasks"]:
        task_file, prompt_file, task = _task_paths(dataset, task_id)
        for cell in spec["cells"]:
            cell_name = "__".join(_slug(cell[key]) for key in
                                  ("condition", "harness", "model"))
            for replicate in range(1, spec["replicates"] + 1):
                attempt_id = f"{task_id}__{cell_name}__r{replicate}"
                attempt = root / "attempts" / task_id / f"{cell_name}__r{replicate}"
                workspace = attempt / "workspace"
                workspace.mkdir(parents=True)
                shutil.copy2(prompt_file, workspace / "task_prompt.md")
                instructions = _agent_instructions(
                    cell["condition"],
                    int(cell.get("agent_timeout_seconds") or
                        spec["agent_timeout_seconds"]),
                    cell.get("md_time_limit") or spec["md_time_limit"],
                )
                (workspace / "agent_prompt.md").write_text(
                    instructions + "\n\n--- PUBLIC TASK ---\n\n" + prompt_file.read_text())
                if cell["condition"] == "sif_only":
                    (workspace / "PORTABLE_SUBMISSION.md").write_text(PORTABLE_LAYOUT)
                image_mode = _image_mode(cell)
                cell_source = None if image_mode else (
                    cell.get("mdclaw_source") or spec.get("mdclaw_source"))
                cell_cli = None if image_mode else (
                    cell.get("mdclaw_cli") or spec.get("mdclaw_cli"))
                image = images.get(cell.get("sif") or spec.get("sif")) if image_mode else None
                runtime_record = (runtimes.get(cell.get("runtime_sif") or spec.get("runtime_sif"))
                                  if cell["condition"] == "sif_only" else None)
                source_record = frozen.get(
                    str(Path(cell_source).resolve())) if cell_source else None
                if source_record:
                    origin = Path(source_record["origin"])
                    cell_source = source_record["frozen"]
                    # bin/mdclaw normally lives in the checkout; follow it in.
                    if cell_cli:
                        cli = Path(cell_cli).resolve()
                        if cli.is_relative_to(origin):
                            cell_cli = str(Path(cell_source) / cli.relative_to(origin))
                environment_spec = {
                    "sif": cell.get("sif") or spec.get("sif"),
                    "runtime_sif": cell.get("runtime_sif") or spec.get("runtime_sif"),
                    "mdclaw_cli": cell_cli,
                    "mdclaw_source": cell_source,
                    "mddatabench_source": str(Path(__file__).resolve().parents[1]),
                    "source_mode": ("none" if cell["condition"] == "sif_only"
                                    else cell["source_mode"]),
                    "source_overlay_required": (cell["condition"] != "sif_only"
                                                and not image_mode),
                    "image_mdclaw_module": image["mdclaw_module"] if image else None,
                    "image_mdclaw_version": image["mdclaw_version"] if image else None,
                    "container_binds": list(container_binds or []) if image_mode else None,
                    "skills_dir": cell.get("skills_dir"),
                    "runtime_inventory": ({k: runtime_record[k] for k in
                                           ("python", "packages", "executables")}
                                          if runtime_record else None),
                    "agent_timeout_seconds": (int(cell.get("agent_timeout_seconds") or
                                                  spec["agent_timeout_seconds"])),
                    "md_time_limit": cell.get("md_time_limit") or spec["md_time_limit"],
                }
                bin_dir = workspace / ".mddatabench" / "bin"
                bin_dir.mkdir(parents=True)
                shim = bin_dir / "sbatch_shim.py"
                shutil.copy2(Path(__file__).with_name("sbatch_shim.py"), shim)
                shutil.copy2(Path(__file__).with_name("source_overlay.py"),
                             bin_dir / "source_overlay.py")
                # The shim is stdlib-only. In image mode it runs inside the SIF,
                # which has no /usr/bin/python3; the image's python3 is on PATH.
                (bin_dir / "sbatch").write_text(
                    "#!/bin/sh\n"
                    f"export MDDATABENCH_MANIFEST={shlex.quote(str(attempt / 'manifest.json'))}\n"
                    'PY="$(command -v python3 2>/dev/null || echo /usr/bin/python3)"\n'
                    f"exec \"$PY\" {shlex.quote(str(shim))} \"$@\"\n")
                (bin_dir / "sbatch").chmod(0o755)
                mdclaw_cli = environment_spec["mdclaw_cli"]
                if image_mode:
                    # No wrapper: the agent invokes the image directly, and the
                    # compute side runs the image's package as well.
                    _write_json(workspace / ".mdclaw_cluster.json", {
                        "container": {"image": environment_spec["sif"],
                                      "extra_flags": "--nv", "source_mode": "image"},
                    })
                if cell["condition"] != "sif_only" and mdclaw_cli:
                    _write_json(workspace / ".mdclaw_cluster.json", {
                        "container": {"image": environment_spec["sif"],
                                      "extra_flags": "--nv", "source_mode": "overlay"},
                    })
                    (bin_dir / "mdclaw").write_text(
                        "#!/bin/sh\n"
                        f"export CLAUDE_PLUGIN_ROOT={shlex.quote(str(Path(environment_spec['mdclaw_source']).resolve()))}\n"
                        f"exec {shlex.quote(str(Path(mdclaw_cli).resolve()))} \"$@\"\n")
                    (bin_dir / "mdclaw").chmod(0o755)
                if cell["condition"] == "cli_skill_sif":
                    if cell["skill_source"] != "user":
                        project_skills = (Path(cell["skills_dir"]) if cell.get("skills_dir")
                                          else Path(environment_spec["mdclaw_source"]) / "skills")
                        agents_dir = workspace / ".agents"
                        agents_dir.mkdir()
                        os.symlink(project_skills.resolve(), agents_dir / "skills",
                                   target_is_directory=True)
                capabilities = [f"Condition: {cell['condition']}"]
                capabilities += [
                    f"Agent/preparation wall limit: {environment_spec['agent_timeout_seconds']} s",
                    f"Each MD Slurm job wall limit: {environment_spec['md_time_limit']}",
                ]
                if image_mode:
                    sif = environment_spec["sif"]
                    capabilities += [
                        f"MDClaw SIF: {sif} (sha256 {image['sha256']})",
                        "MDClaw runtime: the SIF image only. No MDClaw checkout, wrapper, "
                        "host CLI or source overlay is provided; the CLI is the package "
                        f"installed in the image (mdclaw {image['mdclaw_version'] or 'unknown'}).",
                        "Invoke MDClaw as: singularity exec --env PYTHONPATH= --env PYTHONHOME= "
                        f"{sif} mdclaw <tool> [arguments]   (add --nv only inside a GPU allocation)",
                        "Host Slurm clients, configuration, authentication socket and this "
                        "attempt directory are pre-bound through APPTAINER_BIND/SINGULARITY_BIND, "
                        "and MDCLAW_SLURM_PATH is preset inside the image, so mdclaw submit_job "
                        "works from that invocation. Do not bind, clone or import any other "
                        "MDClaw source; PYTHONPATH must stay empty.",
                        "SLURM container is preconfigured in image mode. Submit a direct mdclaw "
                        "command per job/array task using submit_job/submit_array_job; the "
                        "harness verifies that each job runs the image's own package before "
                        "submission."]
                elif cell["condition"] != "sif_only":
                    capabilities += ["MDClaw CLI command: mdclaw",
                                     f"MDClaw SIF: {environment_spec['sif']}",
                                     f"MDClaw source overlay: {environment_spec['mdclaw_source']}",
                                     "SLURM container is preconfigured in overlay mode. Submit a direct "
                                     "mdclaw command per job/array task using submit_job/submit_array_job; "
                                     "the harness checks the source binding before submission."]
                if cell["condition"] == "cli_skill_sif":
                    capabilities.append(
                        "MDClaw skills: pi user-wide discovery"
                        if cell["skill_source"] == "user" else
                        f"MDClaw skills: {cell['skills_dir']}" if cell.get("skills_dir") else
                        f"MDClaw project skills: {environment_spec['mdclaw_source']}/skills")
                if cell["condition"] == "sif_only":
                    capabilities += (_runtime_capabilities(runtime_record) if runtime_record
                                     else [f"Runtime SIF: {environment_spec['runtime_sif']}"])
                    capabilities.append("MDClaw CLI and MDClaw skills are not available.")
                (workspace / "CAPABILITIES.md").write_text("\n".join(capabilities) + "\n")
                cli_exposed = ["CAPABILITIES.md"] if image_mode else ["mdclaw_cli"]
                manifest = {
                    "schema_version": 1,
                    "attempt_id": attempt_id,
                    "experiment_id": spec["experiment_id"],
                    "task_id": task_id,
                    "axis": task.get("axis"),
                    "condition": cell["condition"],
                    "harness": cell["harness"],
                    "harness_version": (cell.get("harness_version") or
                                        _harness_version(cell["harness"])),
                    "model": cell["model"],
                    "thinking": cell.get("thinking"),
                    "skill_source": cell["skill_source"],
                    "replicate": replicate,
                    "pass_rule": PASS_RULE,
                    "created_at": _now(),
                    "paths": {
                        "task_file": str(task_file),
                        "prompt_file": str(prompt_file),
                        "workspace": str(workspace),
                    },
                    "hashes": {
                        "task_json": _sha256(task_file),
                        "prompt_md": _sha256(prompt_file),
                        "sif": (image["sha256"] if image else
                                cell.get("sif_sha256") or spec.get("sif_sha256")),
                        "runtime_sif": (runtime_record["sha256"] if runtime_record else
                                        cell.get("runtime_sif_sha256") or
                                        spec.get("runtime_sif_sha256")),
                    },
                    "revisions": {
                        "mddatabench": _git_revision(Path(__file__).resolve().parents[1]),
                        "mdclaw": source_record["revision"] if source_record else None,
                        "mdclaw_tree_sha256": (source_record["tree_sha256"]
                                               if source_record else None),
                        "mdclaw_image_sha256": image["sha256"] if image else None,
                    },
                    "reference": {
                        "node": task["reference"]["node"],
                        "accession": task["reference"]["accession"],
                        "bundle_sha256": task["reference"]["bundle"]["sha256"],
                    },
                    "environment": environment_spec,
                    "exposed": (["task_prompt.md", *cli_exposed,
                                 ("pi_user_skills" if cell["skill_source"] == "user"
                                  else "mdclaw_skill"), "sif"]
                                if cell["condition"] == "cli_skill_sif" else
                                ["task_prompt.md", *cli_exposed, "sif"]
                                if cell["condition"] == "cli_sif" else
                                ["task_prompt.md", "CAPABILITIES.md",
                                 "PORTABLE_SUBMISSION.md", "runtime_sif"]),
                }
                _write_json(attempt / "manifest.json", manifest)
                _append_event(attempt, "attempt_planned")
                attempts.append({"attempt_id": attempt_id, "attempt_dir": str(attempt)})
    return {"success": True, "experiment_dir": str(root),
            "attempts": len(attempts), "replicates": spec["replicates"],
            "cells": len(spec["cells"]), "tasks": len(spec["tasks"])}


def _harness_command(manifest: dict, workspace: Path) -> list[str]:
    harness, model = manifest["harness"], manifest["model"]
    condition, thinking = manifest["condition"], manifest.get("thinking")
    executable = _harness_executable(harness)
    environment = manifest["environment"]
    skill_root = (Path(environment["skills_dir"]) if environment.get("skills_dir")
                  else Path(environment.get("mdclaw_source") or "") / "skills")
    if harness == "pi":
        command = [executable, "--print", "--mode", "json", "--model", model,
                   "--session-dir", str(workspace.parent / "agent-session"), "--approve"]
        if thinking:
            command += ["--thinking", str(thinking)]
        if condition != "cli_skill_sif":
            command += ["--no-skills", "--no-extensions", "--no-prompt-templates",
                        "--no-context-files"]
        elif manifest.get("skill_source") != "user":
            command += ["--skill", str(skill_root)]
        return command
    if harness in {"claude", "claude-code"}:
        command = [executable, "--print", "--output-format", "stream-json",
                   "--model", model, "--permission-mode", "bypassPermissions"]
        if thinking:
            command += ["--effort", str(thinking)]
        if condition != "cli_skill_sif":
            command += ["--safe-mode", "--disable-slash-commands"]
        else:
            command += ["--plugin-dir", str(skill_root.parent)]
        return command
    if harness == "codex":
        command = [executable, "exec", "-", "--json", "--model", model,
                   "--cd", str(workspace), "--sandbox", "workspace-write",
                   "--skip-git-repo-check"]
        if thinking:
            command += ["--config", f'model_reasoning_effort="{thinking}"']
        if condition != "cli_skill_sif":
            command += ["--ignore-user-config", "--ignore-rules"]
        return command
    raise ValueError(f"unsupported harness {harness!r}; choose pi, claude-code, or codex")


def run_attempt_agent(attempt_dir: str, timeout_seconds: int = 0,
                      dry_run: bool = False) -> dict:
    """Run one pi/Claude Code/Codex attempt and capture its transcript and usage."""
    attempt = Path(attempt_dir).resolve()
    manifest = _json(attempt / "manifest.json")
    workspace = Path(manifest["paths"]["workspace"])
    effective_timeout = int(timeout_seconds or
                            manifest["environment"]["agent_timeout_seconds"])
    command = _harness_command(manifest, workspace)
    stdout_path, stderr_path = attempt / "agent.stdout.jsonl", attempt / "agent.stderr.log"
    attempt_tmp = workspace / ".mddatabench" / "tmp"
    attempt_tmp.mkdir(parents=True, exist_ok=True)
    environment = os.environ.copy()
    harness_path = Path(command[0])
    path_dirs = [str(workspace / ".mddatabench" / "bin")]
    singularity = shutil.which("singularity") or shutil.which("apptainer")
    if singularity:
        path_dirs.append(str(Path(singularity).parent))
    if manifest["harness"] == "pi" and harness_path.is_absolute():
        path_dirs.append(str(harness_path.parent))
        node = shutil.which("node")  # pi is a `#!/usr/bin/env node` script
        if node:
            path_dirs.append(str(Path(node).parent))
    if manifest["condition"] != "sif_only":
        # bin/mdclaw runs Slurm tools with the host python3; keep the operator's.
        host_python = shutil.which("python3")
        if host_python:
            path_dirs.append(str(Path(host_python).parent))
    path_dirs += ["/usr/local/sbin", "/usr/local/bin", "/usr/sbin", "/usr/bin",
                  "/sbin", "/bin"]
    environment.update({"MDDATABENCH_EVENT_LOG": str(
                            workspace / ".mddatabench" / "sbatch-events.jsonl"),
                        "MDDATABENCH_MANIFEST": str(attempt / "manifest.json"),
                        "MDDATABENCH_CONDITION": manifest["condition"],
                        "MDDATABENCH_MD_TIME_LIMIT": manifest["environment"]["md_time_limit"],
                        "PATH": os.pathsep.join(dict.fromkeys(path_dirs)),
                        "PYTHONNOUSERSITE": "1",
                        "TMPDIR": str(attempt_tmp),
                        "TMP": str(attempt_tmp),
                        "TEMP": str(attempt_tmp)})
    environment.pop("PYTHONPATH", None)
    # The sbatch shim forwards to the real binary; not every cluster keeps it
    # in /usr/bin (the laboratory cluster installs Slurm under /usr/local).
    environment.setdefault("MDDATABENCH_REAL_SBATCH",
                           shutil.which("sbatch") or "/usr/bin/sbatch")
    if manifest["harness"] == "codex" and manifest["condition"] != "cli_skill_sif":
        isolated_home = workspace / ".mddatabench" / "home"
        isolated_home.mkdir(exist_ok=True)
        environment["CODEX_HOME"] = environment.get(
            "CODEX_HOME", str(Path.home() / ".codex"))
        environment["HOME"] = str(isolated_home)
    if manifest["condition"] != "sif_only" and manifest["environment"].get("sif"):
        environment["MDCLAW_SIF"] = manifest["environment"]["sif"]
        if manifest["environment"].get("mdclaw_source"):
            environment["MDCLAW_SOURCE"] = manifest["environment"]["mdclaw_source"]
            environment["CLAUDE_PLUGIN_ROOT"] = manifest["environment"]["mdclaw_source"]
        if manifest["environment"].get("source_mode") == "image":
            # The agent reaches MDClaw only through `singularity exec` on the
            # image. Apptainer reads these variables on every invocation, so
            # the host Slurm clients and this attempt directory (manifest,
            # sbatch shim, source-checked scripts) are visible inside without
            # the agent naming them, and the image's Slurm tools resolve the
            # shim first through the host search path.
            binds = [str(attempt), *(manifest["environment"].get("container_binds") or [])]
            environment["APPTAINER_BIND"] = environment["SINGULARITY_BIND"] = ",".join(binds)
            environment["APPTAINERENV_MDCLAW_SLURM_PATH"] = environment["PATH"]
            environment["SINGULARITYENV_MDCLAW_SLURM_PATH"] = environment["PATH"]
            launchers = _host_launchers(environment["PATH"])
            if launchers and not dry_run:
                _append_event(attempt, "image_mode_preflight", host_launchers=launchers)
                sys.stderr.write("warning: image mode, but a host mdclaw launcher is reachable: "
                                 + ", ".join(launchers) + "\n")
    if manifest["condition"] == "sif_only":
        environment["MDDATABENCH_RUNTIME_SIF"] = manifest["environment"]["runtime_sif"]
    if dry_run:
        exposed = {key: value for key, value in environment.items()
                   if key == "PATH" or key.startswith(("APPTAINER", "SINGULARITY",
                                                       "MDCLAW", "MDDATABENCH"))}
        return {"success": True, "attempt_id": manifest["attempt_id"],
                "command": command, "cwd": str(workspace),
                "timeout_seconds": effective_timeout,
                "md_time_limit": manifest["environment"]["md_time_limit"],
                "environment": exposed}
    _append_event(attempt, "agent_start", command=command)
    started = time.monotonic()
    exit_reason, returncode = "completed", None
    with stdout_path.open("w") as stdout, stderr_path.open("w") as stderr:
        try:
            limited_command = ["/usr/bin/timeout", "--signal=TERM", "--kill-after=10s",
                               f"{effective_timeout}s", *command]
            completed = subprocess.run(
                limited_command, cwd=workspace, env=environment,
                input=(workspace / "agent_prompt.md").read_text(), text=True,
                stdout=stdout, stderr=stderr, timeout=effective_timeout + 30, check=False,
            )
            returncode = completed.returncode
            if returncode in {124, 137}:
                exit_reason = "timeout"
            elif returncode:
                exit_reason = "error"
        except subprocess.TimeoutExpired:
            exit_reason = "timeout"
        except OSError as exc:
            exit_reason = "launch_error"
            stderr.write(f"{type(exc).__name__}: {exc}\n")
    wall = time.monotonic() - started
    usage = token_usage(_safe_calls(stdout_path, manifest["harness"]))
    audit = (_image_mode_audit(stdout_path)
             if manifest["environment"].get("source_mode") == "image" else None)
    _append_event(attempt, "agent_end", exit_reason=exit_reason,
                  returncode=returncode, wall_seconds=wall, usage=usage,
                  source_audit=audit)
    return {"success": exit_reason == "completed" and returncode == 0,
            "attempt_id": manifest["attempt_id"], "exit_reason": exit_reason,
            "returncode": returncode, "agent_wall_seconds": wall, "usage": usage,
            "stdout": str(stdout_path), "stderr": str(stderr_path)}


_AUDIT_PATTERNS = {
    # The shim proves what compute jobs ran; login-node commands are only
    # observable in the transcript. These counts flag an attempt that reached
    # for a checkout wrapper or a source overlay so it can be inspected; they
    # are diagnostics and change no score.
    "launcher_mentions": re.compile(r"bin/mdclaw\b"),
    "pythonpath_mentions": re.compile(r"PYTHONPATH=/"),
    "source_bind_mentions": re.compile(r"--bind[^\n]*mdclaw(?!\S*\.sif)"),
    # A bare `mdclaw` resolves to whatever launcher the harness put on PATH;
    # the 2026-09-09 pilot found one in ~/.pi/agent/bin that overlaid an old
    # checkout. Image-mode commands go through `singularity exec` instead.
    "bare_cli_mentions": re.compile(r"(?m)(?:^|[;&|(]\s*)mdclaw\s"),
}


def _agent_shell_commands(transcript: Path) -> list[str]:
    """Shell commands the agent issued, from a pi/Claude/Codex JSON transcript.

    Only the agent's own tool calls are audited. Tool *results* repeat skill
    pages and the shim's source, whose text mentions ``bin/mdclaw`` and
    ``PYTHONPATH`` legitimately: measured on the 2026-09-09 pilot, a raw
    text scan reported 58 launcher mentions for an attempt that ran every
    MDClaw command through the image.
    """
    commands: dict[str, str] = {}

    def walk(value):
        if isinstance(value, dict):
            if value.get("type") in {"toolCall", "tool_use"} or "input" in value and "name" in value:
                arguments = value.get("arguments") or value.get("input") or {}
                command = None
                if isinstance(arguments, dict):
                    for key in ("command", "cmd"):
                        if isinstance(arguments.get(key), str):
                            command = arguments[key]
                    if isinstance(arguments.get("command"), list):
                        command = " ".join(map(str, arguments["command"]))
                if command is not None:
                    # pi repeats a call in message_start/update/end; count once.
                    commands.setdefault(str(value.get("id") or f"text:{command}"), command)
            if value.get("role") == "toolResult" or value.get("type") in {"tool_result", "toolResult"}:
                return
            for item in value.values():
                walk(item)
        elif isinstance(value, list):
            for item in value:
                walk(item)

    for line in transcript.read_text(errors="replace").splitlines() if transcript.exists() else []:
        try:
            walk(json.loads(line))
        except json.JSONDecodeError:
            continue
    return list(commands.values())


def _host_launchers(path: str) -> list[str]:
    """`mdclaw` executables an image-mode agent could reach without the image.

    The runner controls PATH, but pi prepends its own ``~/.pi/agent/bin``;
    a launcher there is invisible to the runner's PATH and was measured on
    the 2026-09-09 pilot (it overlaid an old checkout). Recorded so an
    operator can remove it; not an error, since the shim still proves what
    compute jobs ran and the transcript audit shows login-node use.
    """
    found = []
    for candidate in [shutil.which("mdclaw", path=path),
                      Path.home() / ".pi" / "agent" / "bin" / "mdclaw"]:
        if candidate and Path(candidate).is_file() and str(candidate) not in found:
            found.append(str(candidate))
    return found


def _image_mode_audit(transcript: Path) -> dict:
    commands = _agent_shell_commands(transcript)
    text = "\n".join(commands)
    return {name: len(pattern.findall(text)) for name, pattern in _AUDIT_PATTERNS.items()}


def record_sbatch(attempt_dir: str, argv: list[str], stdout: str,
                  returncode: int) -> str | None:
    """Record one transparent sbatch invocation; used by the console shim."""
    from .sbatch_shim import job_id_from_stdout

    attempt = Path(attempt_dir).resolve()
    job_id = job_id_from_stdout(stdout)
    _append_event(attempt, "sbatch", argv=argv, job_id=job_id,
                  returncode=returncode)
    return job_id


def _events(attempt: Path) -> list[dict]:
    rows = []
    paths = [attempt / "events.jsonl"]
    manifest_path = attempt / "manifest.json"
    if manifest_path.is_file():
        workspace = Path(_json(manifest_path)["paths"]["workspace"])
        paths.append(workspace / ".mddatabench" / "sbatch-events.jsonl")
    for path in paths:
        for line in path.read_text().splitlines() if path.is_file() else []:
            try:
                rows.append(json.loads(line))
            except json.JSONDecodeError:
                continue
    rows.sort(key=lambda row: row.get("at", ""))
    return rows


def md_job_ids(attempt: Path) -> list[str]:
    """Every successful agent-submitted Slurm job, in submission order."""
    return [str(row["job_id"]) for row in _events(attempt)
            if row.get("event") == "sbatch" and row.get("returncode") == 0
            and row.get("job_id")]


def last_md_job_id(attempt: Path) -> str | None:
    jobs = md_job_ids(attempt)
    return jobs[-1] if jobs else None


def _last_scorer_job_id(attempt: Path) -> str | None:
    jobs = [row.get("scorer_job_id") for row in _events(attempt)
            if row.get("event") == "scorer_submitted" and row.get("returncode") == 0
            and row.get("scorer_job_id")]
    return jobs[-1] if jobs else None


def _slurm_job_state(job_id: str) -> str | None:
    """Return an allocation's normalized sacct state when it is available."""
    try:
        completed = subprocess.run(
            ["sacct", "-X", "-n", "-P", "-j", str(job_id), "--format=State"],
            text=True, capture_output=True, check=False, timeout=15,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    if completed.returncode:
        return None
    first = next((line.strip() for line in completed.stdout.splitlines() if line.strip()), "")
    return first.split("|", 1)[0].split()[0].split("+", 1)[0].upper() or None


def _reconcile_scorer(attempt: Path) -> dict | None:
    """Seal a scorer allocation that terminated before writing its result."""
    if (attempt / "result.json").is_file():
        return None
    job_id = _last_scorer_job_id(attempt)
    if not job_id:
        return None
    state = _slurm_job_state(job_id)
    if state not in TERMINAL_SLURM_STATES:
        return None
    code = ("scorer_completed_without_result" if state == "COMPLETED" else
            f"scorer_job_{state.lower()}")
    return finalize_attempt(
        str(attempt), failure_stage="infra", failure_code=code,
        failure_detail=f"scorer Slurm job {job_id} ended in {state} without result.json",
    )


def _safe_calls(transcript: Path, harness: str) -> list[dict]:
    try:
        return iter_calls(transcript, harness)
    except (OSError, ValueError):
        return []


def _skill_roots(manifest: dict) -> list[str]:
    environment = manifest.get("environment") or {}
    roots = [environment.get("skills_dir"),
             str(Path(environment["mdclaw_source"]) / "skills") if environment.get("mdclaw_source") else None]
    if manifest.get("skill_source") == "user" and manifest.get("harness") == "pi":
        home = Path(os.environ.get("PI_CODING_AGENT_DIR", Path.home() / ".pi" / "agent"))
        roots += [str(home / "skills"), *map(str, home.glob("git/*/*/*/skills"))]
    return [root for root in roots if root]


def transcript_metrics(attempt: Path, manifest: dict, md_jobs: list[dict],
                       exit_reason: str | None, write_timeline: bool = True) -> dict:
    """Tokens, skill reads, MDClaw error codes and recovery episodes of one attempt.

    Everything here is derived from the harness transcript and the DAG the
    agent left behind; it can be recomputed later and never changes a score.
    """
    calls = _safe_calls(attempt / "agent.stdout.jsonl", manifest["harness"])
    results = mdclaw_results(calls)
    roots = _skill_roots(manifest)
    job_dir = None
    if manifest["condition"] != "sif_only":
        job_dir = _submission_dir(Path(manifest["paths"]["workspace"]), manifest["condition"])
    report = recovery_report(calls, results, job_dir, md_jobs, exit_reason)
    rows = timeline(calls, results, roots)
    timeline_file = None
    if write_timeline and rows:
        timeline_file = attempt / "timeline.jsonl"
        with timeline_file.open("w") as handle:
            for row in rows:
                handle.write(json.dumps(row, sort_keys=True) + "\n")
    return {"token_usage": token_usage(calls), "skill_reads": skill_reads(calls, roots),
            "mdclaw_error_codes": error_codes(results), "mdclaw_results": len(results),
            "recovery": report, "timeline": str(timeline_file) if timeline_file else None,
            "phases": _phase_summary(rows)}


def _phase_summary(rows: list[dict]) -> dict:
    """Calls, seconds and prompt tokens per timeline stage."""
    phases: dict[str, dict] = {}
    for index, row in enumerate(rows):
        stage = row["stage"]
        entry = phases.setdefault(stage, {"calls": 0, "prompt_total": 0, "output": 0, "seconds": 0.0})
        entry["calls"] += 1
        usage = row.get("usage") or {}
        entry["prompt_total"] += int(usage.get("prompt_total") or 0)
        entry["output"] += int(usage.get("output") or 0)
        nxt = rows[index + 1]["elapsed_seconds"] if index + 1 < len(rows) else None
        if row.get("elapsed_seconds") is not None and nxt is not None:
            entry["seconds"] += max(0.0, nxt - row["elapsed_seconds"])
    return phases


def finalize_attempt(attempt_dir: str, score_file: str = None,
                     failure_stage: str = None, failure_code: str = None,
                     failure_detail: str = None) -> dict:
    """Seal an attempt as binary one/zero, preserving partial checks for diagnosis."""
    attempt = Path(attempt_dir).resolve()
    result_file = attempt / "result.json"
    if result_file.is_file():
        return {"success": True, **_json(result_file), "already_finalized": True}
    manifest = _json(attempt / "manifest.json")
    report = _json(Path(score_file)) if score_file and Path(score_file).is_file() else None
    connectivity = ((report or {}).get("diagnostics") or {}).get(
        "submitted_backbone_connectivity")
    connectivity_file = None
    if isinstance(connectivity, dict):
        # The submitted System is up to 85 MB for one membrane attempt and may
        # be reclaimed after sealing.  Preserve the small evaluator-derived
        # C--N/O3'--P bond record so the scientific basis of the connectivity
        # score survives without retaining every OpenMM force parameter.
        connectivity_file = attempt / "evaluation" / "backbone_connectivity.json"
        _write_json(connectivity_file, connectivity)
    total = int((report or {}).get("total") or 0)
    passed_checks = int((report or {}).get("passed") or 0)
    passed = bool(total and passed_checks == total)
    events = _events(attempt)
    agent_end = next((row for row in reversed(events) if row.get("event") == "agent_end"), {})
    slurm_metrics = _slurm_metrics(attempt / "md_sacct.txt", md_job_ids(attempt))
    enrichment = transcript_metrics(attempt, manifest, slurm_metrics["md_jobs"],
                                    agent_end.get("exit_reason"))
    explicit = ({"stage": failure_stage or "unknown", "code": failure_code or "reported_failure",
                 "detail": failure_detail} if failure_stage or failure_code or failure_detail else None)
    diagnosis = diagnose(_submission_dir(Path(manifest["paths"]["workspace"]), manifest["condition"]),
                         report, passed, slurm_metrics["md_jobs"], explicit, str(attempt / "md_sacct.txt"),
                         portable=manifest["condition"] == "sif_only")
    finished_at = _now()
    diagnosis["execution_diagnostics"]["mdclaw_error_codes"] = enrichment["mdclaw_error_codes"]
    diagnosis["execution_diagnostics"]["agent_exit_reason"] = agent_end.get("exit_reason")
    result = {
        "schema_version": 3,
        "attempt_id": manifest["attempt_id"],
        "experiment_id": manifest["experiment_id"],
        "task_id": manifest["task_id"],
        "axis": manifest.get("axis"),
        "condition": manifest["condition"],
        "harness": manifest["harness"],
        "model": manifest["model"],
        "replicate": manifest["replicate"],
        "pass_rule": PASS_RULE,
        "terminal": True,
        "passed": passed,
        "attempt_score": int(passed),
        "check_score": passed_checks / total if total else 0.0,
        "checks_passed": passed_checks,
        "checks_total": total,
        **diagnosis,
        "metrics": {
            "agent_wall_seconds": agent_end.get("wall_seconds"),
            **slurm_metrics,
            "total_wall_seconds": _elapsed_between(manifest.get("created_at"), finished_at),
            "node_wall_seconds": _node_wall_seconds(_submission_dir(
                Path(manifest["paths"]["workspace"]), manifest["condition"])),
            "token_usage": enrichment["token_usage"],
            "skill_reads": enrichment["skill_reads"],
            "phases": enrichment["phases"],
        },
        "recovery": enrichment["recovery"],
        "artifacts": {
            "score": str(Path(score_file).resolve()) if report else None,
            "backbone_connectivity": (
                str(connectivity_file.resolve()) if connectivity_file else None),
            "timeline": enrichment["timeline"],
        },
        "finished_at": finished_at,
    }
    _write_json(result_file, result)
    _append_event(attempt, "attempt_end", passed=passed, failure_stage=diagnosis["failure_stage"],
                  failure_code=diagnosis["failure_code"])
    return {"success": True, **result}


def _elapsed_between(start: str | None, end: str | None) -> float | None:
    try:
        return (datetime.fromisoformat(end) - datetime.fromisoformat(start)).total_seconds()
    except (TypeError, ValueError):
        return None


def _node_wall_seconds(job_dir: Path) -> dict:
    durations = {}
    for path in sorted((job_dir / "nodes").glob("*/node.json")):
        try:
            node = _json(path)
        except (OSError, json.JSONDecodeError):
            continue
        elapsed = _elapsed_between(node.get("created_at"), node.get("updated_at"))
        if elapsed is not None:
            durations[path.parent.name] = elapsed
    return durations


def _slurm_metrics(path: Path, expected_job_ids=()) -> dict:
    unavailable = {"md_queue_seconds": None, "md_run_seconds": None,
                   "gpu_seconds": None, "md_jobs": [],
                   "slurm_metrics_provenance": "unavailable",
                   **gpu_totals([None for _ in set(expected_job_ids)])}
    if not path.is_file():
        return unavailable
    rows = [line.split("|") for line in path.read_text().splitlines() if line.strip()]
    jobs = []
    for row in rows:
        if len(row) < 7:
            continue
        job_id, state, submitted, started, ended, elapsed, tres = row[:7]
        if not re.fullmatch(r"\d+(?:_\d+)?", job_id):
            continue
        try:
            runtime = float(elapsed)
            if not measured(runtime):
                runtime = None
        except ValueError:
            runtime = None
        queue = _elapsed_between(submitted, started)
        match = re.search(r"(?:gres/gpu|gpu)=(\d+)", tres)
        typed = re.findall(r"(?:^|,)gres/gpu:[^=,]+=(\d+)", tres)
        gpus = (int(match.group(1)) if match else sum(map(int, typed)) if typed else
                0 if re.search(r"(?:^|,)cpu=\d+", tres) else None)
        jobs.append({
            "job_id": job_id,
            "state": state.split("+", 1)[0].split()[0].upper() if state.strip() else None,
            "submitted_at": submitted or None,
            "started_at": started or None,
            "ended_at": ended or None,
            "queue_seconds": queue,
            "run_seconds": runtime,
            "gpus": gpus,
            "gpu_seconds": (runtime * gpus
                            if runtime is not None and gpus is not None else None),
        })
    if not jobs:
        return unavailable

    # sacct -X rows are allocations; do not double-count repeated rows or steps.
    jobs = list({j["job_id"]: j for j in jobs if "." not in j["job_id"]}.values())
    present = {j["job_id"] for j in jobs}
    for missing in sorted(set(expected_job_ids) - present):
        jobs.append({"job_id": missing, "state": None, "queue_seconds": None,
                     "run_seconds": None, "gpu_seconds": None})

    def total(key):
        values = [job[key] for job in jobs]
        return sum(values) if values and all(measured(v) for v in values) else None

    return {"md_queue_seconds": total("queue_seconds"),
            "md_run_seconds": total("run_seconds"),
            **gpu_totals(job["gpu_seconds"] for job in jobs), "md_jobs": jobs,
            "slurm_metrics_provenance": "sacct"}


def _submission_dir(workspace: Path, condition: str) -> Path:
    """Resolve the submission inside an attempt workspace.

    MDClaw's canonical layout is a study whose jobs live at
    ``<study>/jobs/<job_id>``; ``bootstrap_md_workflow`` names the first one
    ``main``.  A bare job outside a study works but MDClaw warns
    ``study_context_missing`` and its skills steer every agent to the study
    form, so the study path is what the prompt asks for and what is scored.

    The prompt names that path as ``workspace/...``, which an agent already
    sitting in the workspace can equally read as a literal subdirectory to
    create.  Measured 2026-08-25 the cast split almost evenly, 14 attempts
    flat against 15 nested, so both roots are searched: which reading an agent
    took says nothing about the molecular dynamics being graded.
    """
    roots = (workspace, workspace / "workspace")
    if condition == "sif_only":
        for root in roots:
            if (root / "submission").is_dir():
                return root / "submission"
        return workspace / "submission"
    # Canonical first across every root, then the looser forms. Exhausting one
    # root before trying the next let a stale outer `job/` win over a nested
    # `study/jobs/main` that was the actual submission.
    for root in roots:
        canonical = root / "study" / "jobs" / "main"
        if canonical.is_dir():
            return canonical
    for root in roots:
        jobs = sorted(p for p in (root / "study" / "jobs").glob("*") if p.is_dir())
        if len(jobs) == 1:
            return jobs[0]
    for root in roots:
        if (root / "job").is_dir():
            return root / "job"
    return workspace / "study" / "jobs" / "main"


def submit_attempt_scorer(attempt_dir: str, bundle_root: str, sif: str,
                          partition: str = None, time_limit: str = "00:15:00",
                          memory: str = "32G", cpus_per_task: int = 4,
                          md_job_id: str = None) -> dict:
    """Submit an evaluator-owned scorer with ``afterany`` on the agent's MD job.

    ``partition`` defaults to ``$MDDATABENCH_SCORER_PARTITION``, then ``gpu``.
    """
    partition = partition or os.environ.get("MDDATABENCH_SCORER_PARTITION", "gpu")
    attempt = Path(attempt_dir).resolve()
    manifest = _json(attempt / "manifest.json")
    job_id = md_job_id or last_md_job_id(attempt)
    if not job_id:
        return finalize_attempt(str(attempt), failure_stage="agent",
                                failure_code="agent_no_submission",
                                failure_detail="the agent submitted no Slurm job")
    if not re.fullmatch(r"\d+(?:_\d+)?", str(job_id)):
        raise ValueError(f"unsafe Slurm job id {job_id!r}")
    accounting_job_ids = md_job_ids(attempt)
    if str(job_id) not in accounting_job_ids:
        accounting_job_ids.append(str(job_id))
    if any(not re.fullmatch(r"\d+(?:_\d+)?", value)
           for value in accounting_job_ids):
        raise ValueError(f"unsafe Slurm job ids {accounting_job_ids!r}")
    accounting_jobs = ",".join(accounting_job_ids)
    task_file = Path(manifest["paths"]["task_file"])
    reference = manifest["reference"]
    bundle = Path(bundle_root).resolve() / f"{reference['node']}_{reference['accession']}"
    source = Path(__file__).resolve().parents[1]
    workspace = Path(manifest["paths"]["workspace"])
    submission = _submission_dir(workspace, manifest["condition"])
    raw_score = attempt / "score.json"
    logs = attempt / "slurm"
    logs.mkdir(exist_ok=True)
    score_tool = ("score_portable_submission" if manifest["condition"] == "sif_only"
                  else "score_benchmark_submission")
    score_flag = "--submission-dir" if manifest["condition"] == "sif_only" else "--job-dir"
    q = shlex.quote
    bind_arg = ",".join(sorted({str(attempt), str(bundle), str(source),
                                str(task_file.parent)}))
    script = logs / "scorer.sbatch"
    script.write_text(f"""#!/bin/bash
#SBATCH --job-name=mdbscore_{_slug(manifest['attempt_id'])[:48]}
#SBATCH --partition={partition}
#SBATCH --nodes=1
#SBATCH --ntasks=1
#SBATCH --cpus-per-task={int(cpus_per_task)}
#SBATCH --time={time_limit}
#SBATCH --mem={memory}
#SBATCH --dependency=afterany:{job_id}
#SBATCH --output={logs}/scorer_%j.out
#SBATCH --error={logs}/scorer_%j.err

set +e
sacct -X -n -P -j {accounting_jobs} --format=JobIDRaw,State,Submit,Start,End,ElapsedRaw,AllocTRES > {q(str(attempt / 'md_sacct.txt'))}
singularity exec --bind {q(bind_arg)} --env PYTHONPATH={q(str(source))} \\
  --env OPENBLAS_NUM_THREADS=1 --env OMP_NUM_THREADS=1 {q(str(Path(sif).resolve()))} \\
  python -m mddatabench {score_tool} {score_flag} {q(str(submission))} \\
  --bundle {q(str(bundle))} --task-file {q(str(task_file))} --out {q(str(raw_score))}
score_rc=$?
if [ "$score_rc" -eq 0 ]; then
  singularity exec --bind {q(bind_arg)} --env PYTHONPATH={q(str(source))} \\
    {q(str(Path(sif).resolve()))} python -m mddatabench finalize_attempt \\
    --attempt-dir {q(str(attempt))} --score-file {q(str(raw_score))}
else
  singularity exec --bind {q(bind_arg)} --env PYTHONPATH={q(str(source))} \\
    {q(str(Path(sif).resolve()))} python -m mddatabench finalize_attempt \\
    --attempt-dir {q(str(attempt))} --failure-stage scorer \\
    --failure-code scorer_error --failure-detail "scorer exited $score_rc"
fi
""")
    script.chmod(0o755)
    completed = subprocess.run(["sbatch", "--parsable", str(script)], text=True,
                               capture_output=True, check=False)
    scorer_job = completed.stdout.strip().split(";", 1)[0] if completed.returncode == 0 else None
    _append_event(attempt, "scorer_submitted", md_job_id=str(job_id),
                  md_job_ids=accounting_job_ids,
                  scorer_job_id=scorer_job, dependency=f"afterany:{job_id}",
                  returncode=completed.returncode)
    if completed.returncode:
        sealed = finalize_attempt(
            str(attempt), failure_stage="infra", failure_code="scorer_submit_failed",
            failure_detail=completed.stderr.strip() or completed.stdout.strip(),
        )
        return {**sealed, "success": False, "md_job_id": str(job_id),
                "scorer_job_id": None, "script": str(script),
                "stdout": completed.stdout, "stderr": completed.stderr}
    return {"success": completed.returncode == 0, "attempt_id": manifest["attempt_id"],
            "md_job_id": str(job_id), "scorer_job_id": scorer_job,
            "script": str(script), "stdout": completed.stdout, "stderr": completed.stderr}


def run_experiment(experiment_dir: str, bundle_root: str, scorer_sif: str,
                   max_agents: int = 1, timeout_seconds: int = 0,
                   limit: int = 0) -> dict:
    """Run pending agents and attach evaluator-owned scorers to their final jobs.

    The command submits work and returns; scorer jobs finish asynchronously.
    Re-running is safe: completed agents are not rerun, while an interrupted
    handoff can still attach its missing scorer.
    ``limit`` bounds newly launched attempts (zero means all pending).
    """
    root = Path(experiment_dir).resolve()
    pending = []
    for manifest_path in sorted((root / "attempts").glob("*/*/manifest.json")):
        attempt = manifest_path.parent
        if (attempt / "result.json").exists():
            continue
        events = _events(attempt)
        if any(row.get("event") == "scorer_submitted" and row.get("returncode") == 0
               for row in events):
            _reconcile_scorer(attempt)
            continue
        pending.append((attempt, not any(row.get("event") == "agent_end"
                                         for row in events)))
    if limit > 0:
        pending = pending[:limit]
    workers = max(1, int(max_agents))

    def execute(item):
        attempt, needs_agent = item
        try:
            agent = (run_attempt_agent(str(attempt), timeout_seconds=timeout_seconds)
                     if needs_agent else None)
            scorer = submit_attempt_scorer(str(attempt), bundle_root, scorer_sif)
        except Exception as exc:
            _append_event(attempt, "harness_error", error=type(exc).__name__, detail=str(exc))
            agent = None
            scorer = finalize_attempt(
                str(attempt), failure_stage="infra", failure_code="harness_error",
                failure_detail=f"{type(exc).__name__}: {exc}",
            )
        return {"attempt_id": _json(attempt / "manifest.json")["attempt_id"],
                "agent": agent, "scorer": scorer}

    launched = []
    with ThreadPoolExecutor(max_workers=workers) as pool:
        futures = [pool.submit(execute, item) for item in pending]
        for future in as_completed(futures):
            launched.append(future.result())
    return {"success": all(row["scorer"].get("success") for row in launched),
            "experiment_dir": str(root), "launched": len(launched), "attempts": launched}


def _attempt_rows(root: Path) -> tuple[list[dict], list[str]]:
    rows, incomplete = [], []
    for manifest_path in sorted((root / "attempts").glob("*/*/manifest.json")):
        attempt = manifest_path.parent
        result = attempt / "result.json"
        if result.is_file():
            rows.append(_json(result))
        else:
            incomplete.append(_json(manifest_path)["attempt_id"])
    return rows, incomplete


def _mean(values: list[float]) -> float | None:
    return sum(values) / len(values) if values else None


def _wilson(successes: int, total: int, z: float = 1.959963984540054) -> tuple[float, float]:
    """Wilson 95% interval for the binary per-attempt success rate."""
    if total == 0:
        return 0.0, 0.0
    proportion = successes / total
    denominator = 1 + z * z / total
    centre = (proportion + z * z / (2 * total)) / denominator
    half = z * math.sqrt((proportion * (1 - proportion) + z * z / (4 * total)) / total)
    half /= denominator
    return max(0.0, centre - half), min(1.0, centre + half)


def collect_experiment(experiment_dir: str, out_dir: str = None,
                       refresh_diagnostics: bool = False) -> dict:
    """Rebuild attempt, failure, and paper-summary tables from sealed results."""
    root = Path(experiment_dir).resolve()
    out = Path(out_dir).resolve() if out_dir else root / "summary"
    if refresh_diagnostics and (not out_dir or out == root or out == root / "summary"
                                or out.is_relative_to(root / "attempts") or out.exists()):
        raise ValueError("diagnostic refresh requires a new, separate output directory")
    out.mkdir(parents=True, exist_ok=True)
    if not refresh_diagnostics:
        for manifest_path in sorted((root / "attempts").glob("*/*/manifest.json")):
            _reconcile_scorer(manifest_path.parent)
    rows, incomplete = _attempt_rows(root)
    for row in rows:
        metrics = row.setdefault("metrics", {})
        if "gpu_expected_count" not in metrics:
            # Old totals may already hide missing jobs. Preserve their known
            # subtotal, but never certify completeness without accounting data.
            old_gpu = metrics.get("gpu_seconds")
            metrics.update(gpu_totals(j.get("gpu_seconds") for j in metrics.get("md_jobs", [])))
            if metrics["gpu_seconds_known"] is None and measured(old_gpu):
                metrics["gpu_seconds_known"] = old_gpu
            metrics["gpu_seconds"] = None
            metrics["gpu_completeness"] = "legacy_unverified"
    if refresh_diagnostics:
        sources = {read_record(p).get("attempt_id"): p.parent
                   for p in (root / "attempts").glob("*/*/manifest.json")}
        for row in rows:
            attempt = sources[row["attempt_id"]]
            manifest = _json(attempt / "manifest.json")
            report = read_record(attempt / "score.json")
            if not report and row.get("artifacts", {}).get("score"):
                report = read_record(Path(row["artifacts"]["score"]))
            row["diagnostic_revision"] = {"source_result": str(attempt / "result.json"),
                "source_sha256": _sha256(attempt / "result.json"),
                "original_failure_stage": row.get("failure_stage"),
                "original_failure_code": row.get("failure_code")}
            # Version-2 records already preserve evidence at sealing time;
            # cleanup of raw files must not erase that snapshot on refresh.
            metrics = (row["metrics"] if row.get("schema_version", 1) >= 2 else
                       _slurm_metrics(attempt / "md_sacct.txt", md_job_ids(attempt)))
            row["metrics"] = {**row.get("metrics", {}), **metrics}
            if (not row.get("execution_diagnostics")
                    or row.get("failure_code") == "execution_evidence_unavailable"):
                # Legacy infra/agent/scorer reasons were explicitly supplied;
                # prep/md check IDs were inferred from score order, not causes.
                # A sealed "no evidence" verdict is re-read too: scored portable
                # attempts were classified that way before 2026-09-10.
                explicit = ({"stage": row["failure_stage"], "code": row.get("failure_code"),
                             "detail": row.get("failure_detail")}
                            if row.get("failure_stage") in {"infra", "agent", "scorer"} else None)
                row.update(diagnose(_submission_dir(Path(manifest["paths"]["workspace"]),
                                                    manifest["condition"]),
                                    report, row["passed"], metrics["md_jobs"], explicit, str(attempt / "md_sacct.txt"),
                                    portable=manifest["condition"] == "sif_only"))
            row["schema_version"] = 2
    sources = {read_record(p).get("attempt_id"): p.parent
               for p in (root / "attempts").glob("*/*/manifest.json")}
    for row in rows:
        if row.get("schema_version", 1) >= 3 or row["attempt_id"] not in sources:
            continue
        # Older seals predate transcript metrics; derive them now without
        # rewriting the sealed result.
        attempt = sources[row["attempt_id"]]
        manifest = _json(attempt / "manifest.json")
        exit_reason = next((e.get("exit_reason") for e in reversed(_events(attempt))
                            if e.get("event") == "agent_end"), None)
        enrichment = transcript_metrics(attempt, manifest, row.get("metrics", {}).get("md_jobs", []),
                                        exit_reason, write_timeline=False)
        metrics = row.setdefault("metrics", {})
        if (metrics.get("token_usage") or {}).get("provenance", "unavailable") == "unavailable":
            metrics["token_usage"] = enrichment["token_usage"]
        metrics.setdefault("skill_reads", enrichment["skill_reads"])
        metrics.setdefault("phases", enrichment["phases"])
        row.setdefault("recovery", {**enrichment["recovery"], "provenance": "collect_time"})
        row.setdefault("execution_diagnostics", {}).setdefault(
            "mdclaw_error_codes", enrichment["mdclaw_error_codes"])
    with (out / "attempts.jsonl").open("w") as handle:
        for row in rows:
            handle.write(json.dumps(row, sort_keys=True) + "\n")

    by_cell = defaultdict(list)
    for row in rows:
        by_cell[(row["condition"], row["harness"], row["model"], row.get("axis"))].append(row)
        by_cell[(row["condition"], row["harness"], row["model"], "all")].append(row)
    summaries = []
    for key, attempts in sorted(by_cell.items()):
        per_task = defaultdict(list)
        for row in attempts:
            per_task[row["task_id"]].append(row)
        task_any = [int(any(run["passed"] for run in runs)) for runs in per_task.values()]
        task_all = [int(all(run["passed"] for run in runs)) for runs in per_task.values()]
        usage_rows = [row.get("metrics", {}).get("token_usage", {}) for row in attempts]
        measured_usage = [item for item in usage_rows if item.get("prompt_total") is not None]
        input_tokens = [item.get("input_tokens") for item in usage_rows
                        if item.get("input_tokens") is not None]
        output_tokens = [item.get("output_tokens") for item in usage_rows
                         if item.get("output_tokens") is not None]
        recoveries = [row.get("recovery") or {} for row in attempts]
        episodes = [e for item in recoveries for e in item.get("episodes", [])]
        recovered = sum(e.get("outcome") == "recovered" for e in episodes)
        prompt_total_sum = sum(item["prompt_total"] for item in measured_usage)
        cache_read_sum = sum(item.get("cache_read") or 0 for item in measured_usage)
        successes = sum(int(row["attempt_score"]) for row in attempts)
        ci_low, ci_high = _wilson(successes, len(attempts))
        gpu = gpu_totals(row.get("metrics", {}).get("gpu_seconds") for row in attempts)
        known_gpu = [row.get("metrics", {}).get("gpu_seconds_known",
                     row.get("metrics", {}).get("gpu_seconds")) for row in attempts]
        gpu["gpu_seconds_known"] = sum(v for v in known_gpu if measured(v)) if any(measured(v) for v in known_gpu) else None

        def metrics(name):
            return [float(row["metrics"][name]) for row in attempts
                    if row.get("metrics", {}).get(name) is not None]

        summaries.append({
            "condition": key[0], "harness": key[1], "model": key[2], "axis": key[3],
            "tasks": len(per_task), "attempts": len(attempts),
            "successes": successes,
            "success_rate": successes / len(attempts),
            "success_rate_ci95_low": ci_low,
            "success_rate_ci95_high": ci_high,
            "mean_check_score": _mean([float(row["check_score"]) for row in attempts]),
            "any_pass_at_k": _mean(task_any),
            "reliability_at_k": _mean(task_all),
            "k_min": min((len(runs) for runs in per_task.values()), default=0),
            "k_max": max((len(runs) for runs in per_task.values()), default=0),
            "mean_agent_wall_seconds": _mean(metrics("agent_wall_seconds")),
            "mean_md_queue_seconds": _mean(metrics("md_queue_seconds")),
            "mean_md_run_seconds": _mean(metrics("md_run_seconds")),
            "mean_total_wall_seconds": _mean(metrics("total_wall_seconds")),
            "total_gpu_seconds": gpu["gpu_seconds"],
            "known_gpu_seconds": gpu["gpu_seconds_known"],
            "gpu_observed_attempts": gpu["gpu_observed_count"],
            "gpu_expected_attempts": gpu["gpu_expected_count"],
            "gpu_coverage": gpu["gpu_coverage"],
            "mean_input_tokens": _mean([float(value) for value in input_tokens]),
            "mean_output_tokens": _mean([float(value) for value in output_tokens]),
            "token_coverage": len(input_tokens) / len(attempts) if attempts else 0.0,
            "mean_calls": _mean([float(item["calls"]) for item in usage_rows if item.get("calls") is not None]),
            "mean_prompt_total": _mean([float(item["prompt_total"]) for item in measured_usage]),
            "mean_prompt_uncached": _mean([float(item.get("prompt_uncached") or 0) for item in measured_usage]),
            "mean_cache_read": _mean([float(item.get("cache_read") or 0) for item in measured_usage]),
            "mean_cache_write": _mean([float(item.get("cache_write") or 0) for item in measured_usage]),
            "mean_output_tokens_measured": _mean([float(item.get("output") or 0) for item in measured_usage]),
            "mean_reasoning_tokens": _mean([float(item.get("reasoning") or 0) for item in measured_usage]),
            "cache_hit_ratio": (cache_read_sum / prompt_total_sum) if prompt_total_sum else None,
            "tokens_per_success": ((prompt_total_sum + sum(item.get("output") or 0 for item in measured_usage))
                                   / successes if successes and measured_usage else None),
            "mean_skill_read_chars": _mean([float(row["metrics"]["skill_reads"]["chars"]) for row in attempts
                                            if row.get("metrics", {}).get("skill_reads")]),
            "recovery_episodes": len(episodes),
            "recovery_rate": (recovered / len(episodes)) if episodes else None,
            "failure_free_rate": _mean([float(item.get("failure_free", True)) for item in recoveries]),
        })
    columns = ["condition", "harness", "model", "axis", "tasks", "attempts",
               "successes", "success_rate", "success_rate_ci95_low",
               "success_rate_ci95_high", "mean_check_score", "any_pass_at_k",
               "reliability_at_k", "k_min", "k_max"]
    columns += ["mean_agent_wall_seconds", "mean_md_queue_seconds", "mean_md_run_seconds",
                "mean_total_wall_seconds", "total_gpu_seconds", "known_gpu_seconds",
                "gpu_observed_attempts", "gpu_expected_attempts", "gpu_coverage", "mean_input_tokens",
                "mean_output_tokens", "token_coverage", "mean_calls", "mean_prompt_total",
                "mean_prompt_uncached", "mean_cache_read", "mean_cache_write",
                "mean_output_tokens_measured", "mean_reasoning_tokens", "cache_hit_ratio",
                "tokens_per_success", "mean_skill_read_chars", "recovery_episodes",
                "recovery_rate", "failure_free_rate"]
    with (out / "summary.csv").open("w", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=columns)
        writer.writeheader()
        writer.writerows(summaries)
    failures = Counter((row["condition"], row["harness"], row["model"], row.get("axis"),
                        row.get("failure_stage"), row.get("failure_code"))
                       for row in rows if not row["passed"])
    failure_rows = [{"condition": condition, "harness": harness, "model": model,
                     "axis": axis, "failure_stage": stage, "failure_code": code,
                     "count": count}
                    for (condition, harness, model, axis, stage, code), count
                    in sorted(failures.items(), key=lambda item: tuple(str(v) for v in item[0]))]
    with (out / "failures.csv").open("w", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=["condition", "harness", "model", "axis",
                                                        "failure_stage", "failure_code", "count"])
        writer.writeheader()
        writer.writerows(failure_rows)
    scoring = Counter((row["condition"], row["harness"], row["model"], row.get("axis"),
                       check.get("category"), check.get("check_id"))
                      for row in rows for check in row.get("scoring_failures", []))
    scoring_rows = [dict(zip(("condition", "harness", "model", "axis", "category", "check_id"), key), count=count)
                    for key, count in sorted(scoring.items(), key=lambda item: tuple(str(v) for v in item[0]))]
    with (out / "scoring_failures.csv").open("w", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=["condition", "harness", "model", "axis",
                                                    "category", "check_id", "count"])
        writer.writeheader()
        writer.writerows(scoring_rows)
    recovery_rows = _recovery_rows(rows)
    with (out / "recovery.csv").open("w", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=["condition", "harness", "model", "stage", "kind",
                                                    "code", "episodes", "recovered", "abandoned",
                                                    "timed_out", "recovery_rate", "mean_calls",
                                                    "mean_prompt_total", "mean_seconds",
                                                    "diagnostic_tool_share", "argument_change_share"])
        writer.writeheader()
        writer.writerows(recovery_rows)
    codes = Counter((row["condition"], row["harness"], row["model"], code)
                    for row in rows
                    for code, count in (row.get("execution_diagnostics", {}).get("mdclaw_error_codes") or {}).items()
                    for _ in range(int(count)))
    code_rows = [dict(zip(("condition", "harness", "model", "code"), key), count=count)
                 for key, count in sorted(codes.items(), key=lambda item: tuple(str(v) for v in item[0]))]
    with (out / "error_codes.csv").open("w", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=["condition", "harness", "model", "code", "count"])
        writer.writeheader()
        writer.writerows(code_rows)
    digests = out / "failure_digest"
    digests.mkdir(exist_ok=True)
    for row in rows:
        if not row["passed"]:
            (digests / f"{_slug(row['attempt_id'])}.md").write_text(_failure_digest(row, sources.get(row["attempt_id"])))
    payload = {"schema_version": 3, "generated_at": _now(), "attempts": len(rows),
               "diagnostics_refreshed": refresh_diagnostics,
               "incomplete_attempts": incomplete, "summary": summaries,
               "failures": failure_rows, "scoring_failures": scoring_rows,
               "recovery": recovery_rows, "error_codes": code_rows}
    _write_json(out / "summary.json", payload)
    return {"success": not incomplete, "out_dir": str(out), **payload}


def _recovery_rows(rows: list[dict]) -> list[dict]:
    groups: dict[tuple, list[dict]] = defaultdict(list)
    for row in rows:
        for episode in (row.get("recovery") or {}).get("episodes", []):
            groups[(row["condition"], row["harness"], row["model"], episode.get("stage"),
                    episode.get("kind"), episode.get("code"))].append(episode)
    table = []
    for key, episodes in sorted(groups.items(), key=lambda item: tuple(str(v) for v in item[0])):
        outcomes = Counter(e.get("outcome") for e in episodes)
        costs = [e.get("cost") or {} for e in episodes]
        table.append({"condition": key[0], "harness": key[1], "model": key[2], "stage": key[3],
                      "kind": key[4], "code": key[5], "episodes": len(episodes),
                      "recovered": outcomes.get("recovered", 0),
                      "abandoned": outcomes.get("abandoned", 0),
                      "timed_out": outcomes.get("timed_out", 0),
                      "recovery_rate": outcomes.get("recovered", 0) / len(episodes),
                      "mean_calls": _mean([float(c["calls"]) for c in costs if c.get("calls") is not None]),
                      "mean_prompt_total": _mean([float(c["prompt_total"]) for c in costs
                                                  if c.get("prompt_total") is not None]),
                      "mean_seconds": _mean([float(c["seconds"]) for c in costs if c.get("seconds") is not None]),
                      "diagnostic_tool_share": _mean([float("diagnostic_tool" in (e.get("means") or []))
                                                      for e in episodes]),
                      "argument_change_share": _mean([float("argument_change" in (e.get("means") or []))
                                                      for e in episodes])})
    return table


def _failure_digest(row: dict, attempt: Path | None) -> str:
    """A human-readable digest of one failed attempt, from sealed evidence only."""
    lines = [f"# {row['attempt_id']}", "",
             f"- condition: {row['condition']}  harness: {row['harness']}  model: {row['model']}",
             f"- failure stage: {row.get('failure_stage')}  code: {row.get('failure_code')}",
             f"- detail: {row.get('failure_detail')}",
             f"- checks: {row.get('checks_passed')}/{row.get('checks_total')}",
             f"- agent exit: {(row.get('execution_diagnostics') or {}).get('agent_exit_reason')}",
             f"- agent wall: {(row.get('metrics') or {}).get('agent_wall_seconds')} s", ""]
    usage = (row.get("metrics") or {}).get("token_usage") or {}
    lines += ["## Tokens", "",
              f"- calls: {usage.get('calls')}  prompt_total: {usage.get('prompt_total')}  "
              f"uncached: {usage.get('prompt_uncached')}  cache_read: {usage.get('cache_read')}  "
              f"output: {usage.get('output')}  reasoning: {usage.get('reasoning')}  "
              f"({usage.get('provenance')})", ""]
    checks = row.get("scoring_failures") or []
    if checks:
        lines += ["## Failed checks", ""] + [f"- {c.get('check_id')} ({c.get('category')}): "
                                             f"{str(c.get('detail') or c.get('reason') or '')[:200]}"
                                             for c in checks] + [""]
    codes = (row.get("execution_diagnostics") or {}).get("mdclaw_error_codes") or {}
    if codes:
        lines += ["## MDClaw error codes", ""] + [f"- {code}: {count}" for code, count in
                                                  sorted(codes.items())] + [""]
    episodes = (row.get("recovery") or {}).get("episodes") or []
    if episodes:
        lines += ["## Recovery episodes", ""]
        for e in episodes:
            cost = e.get("cost") or {}
            lines.append(f"- [{e.get('kind')}] {e.get('stage')} {e.get('code')} -> {e.get('outcome')}"
                         f"; means: {', '.join(e.get('means') or []) or 'none'}"
                         f"; calls {cost.get('calls')}, prompt {cost.get('prompt_total')}, "
                         f"{cost.get('seconds')} s"
                         + (f"; changed: {' '.join(e.get('argument_changes') or [])}"
                            if e.get('argument_changes') else ""))
            if e.get("message"):
                lines.append(f"  {str(e['message'])[:200]}")
        lines.append("")
    phases = (row.get("metrics") or {}).get("phases") or {}
    if phases:
        lines += ["## Phases", ""] + [f"- {stage}: {v['calls']} calls, {v['prompt_total']} prompt tokens, "
                                      f"{round(v['seconds'])} s" for stage, v in phases.items()] + [""]
    if attempt and (attempt / "agent.stdout.jsonl").exists():
        calls = _safe_calls(attempt / "agent.stdout.jsonl", row["harness"])
        tail = calls[-5:]
        if tail:
            lines += ["## Last tool calls", ""]
            for call in tail:
                for tool in call["tool_calls"]:
                    arguments = tool.get("arguments") or {}
                    text = arguments.get("command") or arguments.get("path") or json.dumps(arguments)
                    lines.append(f"- #{call['index']} {tool.get('name')}: {str(text)[:160]}")
            lines.append("")
    return "\n".join(lines)


def model_inventory(harness: str = "pi", out: str = None) -> dict:
    """Snapshot locally configured models without copying credentials."""
    if harness != "pi":
        payload = {"success": True, "harness": harness, "models": [],
                   "note": "select a fully-qualified model and record it in the experiment spec"}
    else:
        root = Path(os.environ.get("PI_CODING_AGENT_DIR", Path.home() / ".pi/agent"))
        models_file, settings_file = root / "models.json", root / "settings.json"
        configured = _json(models_file) if models_file.is_file() else {}
        providers = configured.get("providers") or configured
        models = []
        for provider_name, provider in providers.items() if isinstance(providers, dict) else []:
            if not isinstance(provider, dict):
                continue
            for model in provider.get("models") or []:
                if isinstance(model, dict) and model.get("id"):
                    models.append({"id": f"{provider_name}/{model['id']}",
                                   "name": model.get("name"),
                                   "reasoning": model.get("reasoning"),
                                   "context_window": model.get("contextWindow"),
                                   "max_tokens": model.get("maxTokens"),
                                   "cost": model.get("cost")})
        payload = {"success": True, "harness": harness, "models": models,
                   "sources": {
                       "models_json_sha256": _sha256(models_file) if models_file.is_file() else None,
                       "settings_json_sha256": (_sha256(settings_file)
                                                if settings_file.is_file() else None),
                   }}
    if out:
        _write_json(Path(out), payload)
    return payload
