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
import tempfile
import time
from collections import Counter, defaultdict
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
from pathlib import Path


CONDITIONS = frozenset({"cli_skill_sif", "cli_sif", "sif_only"})
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
    # Run output that happens to live inside the checkout. What is frozen is
    # the source an attempt imports; a study workspace is data. Measured
    # 2026-08-27: a checkout carrying 37 GB of trajectories under `studies/`
    # was copied whole into the experiment and then hashed file by file, which
    # exhausted the 1 TB project quota before the first attempt dispatched.
    "studies", "runs",
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
        cell_limit = str(cell.get("md_time_limit") or md_time_limit)
        if not re.fullmatch(r"[0-9:-]+", cell_limit):
            raise ValueError("cell md_time_limit must be a Slurm time value")
        if condition != "sif_only":
            if not (cell.get("sif") or spec.get("sif")):
                raise ValueError(f"{condition} requires sif")
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
        normal_cells.append({**cell, "condition": condition, "harness": harness,
                             "model": model})
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
        if not source:
            continue
        origin = Path(source).resolve()
        if str(origin) in frozen:
            continue
        dest = root / "frozen-source" / f"mdclaw-{len(frozen)}"
        dest.parent.mkdir(parents=True, exist_ok=True)
        frozen[str(origin)] = _freeze_source(origin, dest)

    _write_json(root / "experiment.json", {
        **spec, "created_at": _now(), "spec_sha256": _sha256(spec_path),
        "mddatabench_revision": _git_revision(Path(__file__).resolve().parents[1]),
        "frozen_sources": list(frozen.values()),
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
                cell_source = cell.get("mdclaw_source") or spec.get("mdclaw_source")
                cell_cli = cell.get("mdclaw_cli") or spec.get("mdclaw_cli")
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
                    "source_overlay_required": True,
                    "agent_timeout_seconds": (int(cell.get("agent_timeout_seconds") or
                                                  spec["agent_timeout_seconds"])),
                    "md_time_limit": cell.get("md_time_limit") or spec["md_time_limit"],
                }
                bin_dir = workspace / ".mddatabench" / "bin"
                bin_dir.mkdir(parents=True)
                shim = bin_dir / "sbatch_shim.py"
                shutil.copy2(Path(__file__).with_name("sbatch_shim.py"), shim)
                (bin_dir / "sbatch").write_text(
                    "#!/bin/sh\n"
                    f"exec /usr/bin/python3 {shlex.quote(str(shim))} \"$@\"\n")
                (bin_dir / "sbatch").chmod(0o755)
                mdclaw_cli = environment_spec["mdclaw_cli"]
                if cell["condition"] != "sif_only" and mdclaw_cli:
                    (bin_dir / "mdclaw").write_text(
                        "#!/bin/sh\n"
                        f"export CLAUDE_PLUGIN_ROOT={shlex.quote(str(Path(environment_spec['mdclaw_source']).resolve()))}\n"
                        f"exec {shlex.quote(str(Path(mdclaw_cli).resolve()))} \"$@\"\n")
                    (bin_dir / "mdclaw").chmod(0o755)
                if cell["condition"] == "cli_skill_sif":
                    project_skills = Path(environment_spec["mdclaw_source"]) / "skills"
                    agents_dir = workspace / ".agents"
                    agents_dir.mkdir()
                    os.symlink(project_skills.resolve(), agents_dir / "skills",
                               target_is_directory=True)
                capabilities = [f"Condition: {cell['condition']}"]
                capabilities += [
                    f"Agent/preparation wall limit: {environment_spec['agent_timeout_seconds']} s",
                    f"Each MD Slurm job wall limit: {environment_spec['md_time_limit']}",
                ]
                if cell["condition"] != "sif_only":
                    capabilities += ["MDClaw CLI command: mdclaw",
                                     f"MDClaw SIF: {environment_spec['sif']}",
                                     f"MDClaw source overlay: {environment_spec['mdclaw_source']}"]
                    if cell["condition"] == "cli_skill_sif":
                        capabilities.append(
                            f"MDClaw project skills: {environment_spec['mdclaw_source']}/skills")
                else:
                    capabilities += [f"Runtime SIF: {environment_spec['runtime_sif']}",
                                     "MDClaw CLI and MDClaw skills are not available."]
                (workspace / "CAPABILITIES.md").write_text("\n".join(capabilities) + "\n")
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
                        "sif": cell.get("sif_sha256") or spec.get("sif_sha256"),
                        "runtime_sif": (cell.get("runtime_sif_sha256") or
                                        spec.get("runtime_sif_sha256")),
                    },
                    "revisions": {
                        "mddatabench": _git_revision(Path(__file__).resolve().parents[1]),
                        "mdclaw": source_record["revision"] if source_record else None,
                        "mdclaw_tree_sha256": (source_record["tree_sha256"]
                                               if source_record else None),
                    },
                    "reference": {
                        "node": task["reference"]["node"],
                        "accession": task["reference"]["accession"],
                        "bundle_sha256": task["reference"]["bundle"]["sha256"],
                    },
                    "environment": environment_spec,
                    "exposed": (["task_prompt.md", "mdclaw_cli", "mdclaw_skill", "sif"]
                                if cell["condition"] == "cli_skill_sif" else
                                ["task_prompt.md", "mdclaw_cli", "sif"]
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
    skill_root = Path(manifest["environment"]["mdclaw_source"] or "") / "skills"
    if harness == "pi":
        command = [executable, "--print", "--mode", "json", "--model", model,
                   "--session-dir", str(workspace.parent / "agent-session"), "--approve"]
        if thinking:
            command += ["--thinking", str(thinking)]
        if condition != "cli_skill_sif":
            command += ["--no-skills", "--no-extensions", "--no-prompt-templates",
                        "--no-context-files"]
        else:
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


def _sum_usage(value, totals: Counter) -> None:
    if isinstance(value, dict):
        for key, item in value.items():
            normal = key.lower().replace("-", "_")
            if isinstance(item, (int, float)):
                if normal in {"input_tokens", "inputtokens", "prompt_tokens"}:
                    totals["input_tokens"] += int(item)
                elif normal in {"output_tokens", "outputtokens", "completion_tokens"}:
                    totals["output_tokens"] += int(item)
                elif normal in {"reasoning_tokens", "thinking_tokens"}:
                    totals["reasoning_tokens"] += int(item)
            elif normal in {"usage", "token_usage", "modelusage"}:
                _sum_usage(item, totals)
            else:
                _sum_usage(item, totals)
    elif isinstance(value, list):
        for item in value:
            _sum_usage(item, totals)


def _usage_from_jsonl(path: Path) -> dict:
    totals, parsed = Counter(), 0
    for line in path.read_text(errors="replace").splitlines() if path.exists() else []:
        try:
            payload = json.loads(line)
        except json.JSONDecodeError:
            continue
        parsed += 1
        _sum_usage(payload, totals)
    return {"input_tokens": totals.get("input_tokens"),
            "output_tokens": totals.get("output_tokens"),
            "reasoning_tokens": totals.get("reasoning_tokens"),
            "provenance": "transcript" if parsed and totals else "unavailable"}


def run_attempt_agent(attempt_dir: str, timeout_seconds: int = 0,
                      dry_run: bool = False) -> dict:
    """Run one pi/Claude Code/Codex attempt and capture its transcript and usage."""
    attempt = Path(attempt_dir).resolve()
    manifest = _json(attempt / "manifest.json")
    workspace = Path(manifest["paths"]["workspace"])
    effective_timeout = int(timeout_seconds or
                            manifest["environment"]["agent_timeout_seconds"])
    command = _harness_command(manifest, workspace)
    if dry_run:
        return {"success": True, "attempt_id": manifest["attempt_id"],
                "command": command, "cwd": str(workspace),
                "timeout_seconds": effective_timeout,
                "md_time_limit": manifest["environment"]["md_time_limit"]}
    stdout_path, stderr_path = attempt / "agent.stdout.jsonl", attempt / "agent.stderr.log"
    environment = os.environ.copy()
    harness_path = Path(command[0])
    path_dirs = [str(workspace / ".mddatabench" / "bin")]
    singularity = shutil.which("singularity") or shutil.which("apptainer")
    if singularity:
        path_dirs.append(str(Path(singularity).parent))
    if manifest["harness"] == "pi" and harness_path.is_absolute():
        path_dirs.append(str(harness_path.parent))
    path_dirs += ["/usr/local/sbin", "/usr/local/bin", "/usr/sbin", "/usr/bin",
                  "/sbin", "/bin"]
    environment.update({"MDDATABENCH_EVENT_LOG": str(
                            workspace / ".mddatabench" / "sbatch-events.jsonl"),
                        "MDDATABENCH_CONDITION": manifest["condition"],
                        "MDDATABENCH_MD_TIME_LIMIT": manifest["environment"]["md_time_limit"],
                        "PATH": os.pathsep.join(dict.fromkeys(path_dirs)),
                        "PYTHONNOUSERSITE": "1"})
    environment.pop("PYTHONPATH", None)
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
    if manifest["condition"] == "sif_only":
        environment["MDDATABENCH_RUNTIME_SIF"] = manifest["environment"]["runtime_sif"]
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
    usage = _usage_from_jsonl(stdout_path)
    _append_event(attempt, "agent_end", exit_reason=exit_reason,
                  returncode=returncode, wall_seconds=wall, usage=usage)
    return {"success": exit_reason == "completed" and returncode == 0,
            "attempt_id": manifest["attempt_id"], "exit_reason": exit_reason,
            "returncode": returncode, "agent_wall_seconds": wall, "usage": usage,
            "stdout": str(stdout_path), "stderr": str(stderr_path)}


def record_sbatch(attempt_dir: str, argv: list[str], stdout: str,
                  returncode: int) -> str | None:
    """Record one transparent sbatch invocation; used by the console shim."""
    attempt = Path(attempt_dir).resolve()
    match = re.search(r"Submitted batch job\s+(\d+)", stdout)
    job_id = match.group(1) if match else None
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


def last_md_job_id(attempt: Path) -> str | None:
    jobs = [row.get("job_id") for row in _events(attempt)
            if row.get("event") == "sbatch" and row.get("job_id")]
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


def _failure_from_score(report: dict) -> tuple[str | None, str | None]:
    failed = [row for row in report.get("checks", [])
              if row.get("weight", 0) and not row.get("passed")]
    if not failed:
        return None, None
    first = failed[0]
    category = first.get("category")
    return ("prep" if category == "prep" else "md" if category == "md" else "scorer",
            first.get("check_id"))


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
    inferred_stage, inferred_code = _failure_from_score(report or {})
    stage = None if passed else failure_stage or inferred_stage or "agent"
    code = None if passed else failure_code or inferred_code or "no_scorable_submission"
    events = _events(attempt)
    agent_end = next((row for row in reversed(events) if row.get("event") == "agent_end"), {})
    slurm_metrics = _slurm_metrics(attempt / "md_sacct.txt")
    finished_at = _now()
    result = {
        "schema_version": 1,
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
        "failure_stage": stage,
        "failure_code": code,
        "failure_detail": None if passed else failure_detail,
        "metrics": {
            "agent_wall_seconds": agent_end.get("wall_seconds"),
            **slurm_metrics,
            "total_wall_seconds": _elapsed_between(manifest.get("created_at"), finished_at),
            "node_wall_seconds": _node_wall_seconds(_submission_dir(
                Path(manifest["paths"]["workspace"]), manifest["condition"])),
            "token_usage": agent_end.get("usage") or {
                "input_tokens": None, "output_tokens": None,
                "reasoning_tokens": None, "provenance": "unavailable"},
        },
        "artifacts": {
            "score": str(Path(score_file).resolve()) if report else None,
            "backbone_connectivity": (
                str(connectivity_file.resolve()) if connectivity_file else None),
        },
        "finished_at": finished_at,
    }
    _write_json(result_file, result)
    _append_event(attempt, "attempt_end", passed=passed, failure_stage=stage,
                  failure_code=code)
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


def _slurm_metrics(path: Path) -> dict:
    if not path.is_file():
        return {"md_queue_seconds": None, "md_run_seconds": None,
                "gpu_seconds": None, "slurm_metrics_provenance": "unavailable"}
    rows = [line.split("|") for line in path.read_text().splitlines() if line.strip()]
    if not rows or len(rows[0]) < 7:
        return {"md_queue_seconds": None, "md_run_seconds": None,
                "gpu_seconds": None, "slurm_metrics_provenance": "unavailable"}
    _, _, submitted, started, _, elapsed, tres = rows[0][:7]
    try:
        runtime = float(elapsed)
    except ValueError:
        runtime = None
    queue = None
    try:
        queue = (datetime.fromisoformat(started) - datetime.fromisoformat(submitted)).total_seconds()
    except ValueError:
        pass
    match = re.search(r"(?:gres/gpu|gpu)=(\d+)", tres)
    gpus = int(match.group(1)) if match else None
    return {"md_queue_seconds": queue, "md_run_seconds": runtime,
            "gpu_seconds": runtime * gpus if runtime is not None and gpus is not None else None,
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
                          partition: str = "gpu", time_limit: str = "00:15:00",
                          memory: str = "32G", cpus_per_task: int = 4,
                          md_job_id: str = None) -> dict:
    """Submit an evaluator-owned scorer with ``afterany`` on the agent's MD job."""
    attempt = Path(attempt_dir).resolve()
    manifest = _json(attempt / "manifest.json")
    job_id = md_job_id or last_md_job_id(attempt)
    if not job_id:
        return finalize_attempt(str(attempt), failure_stage="agent",
                                failure_code="agent_no_submission",
                                failure_detail="the agent submitted no Slurm job")
    if not re.fullmatch(r"\d+(?:_\d+)?", str(job_id)):
        raise ValueError(f"unsafe Slurm job id {job_id!r}")
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
sacct -X -n -P -j {job_id} --format=JobIDRaw,State,Submit,Start,End,ElapsedRaw,AllocTRES > {q(str(attempt / 'md_sacct.txt'))}
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


def collect_experiment(experiment_dir: str, out_dir: str = None) -> dict:
    """Rebuild attempt, failure, and paper-summary tables from sealed results."""
    root = Path(experiment_dir).resolve()
    out = Path(out_dir).resolve() if out_dir else root / "summary"
    out.mkdir(parents=True, exist_ok=True)
    for manifest_path in sorted((root / "attempts").glob("*/*/manifest.json")):
        _reconcile_scorer(manifest_path.parent)
    rows, incomplete = _attempt_rows(root)
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
        token_usage = [row.get("metrics", {}).get("token_usage", {}) for row in attempts]
        input_tokens = [item.get("input_tokens") for item in token_usage
                        if item.get("input_tokens") is not None]
        output_tokens = [item.get("output_tokens") for item in token_usage
                         if item.get("output_tokens") is not None]
        successes = sum(int(row["attempt_score"]) for row in attempts)
        ci_low, ci_high = _wilson(successes, len(attempts))

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
            "total_gpu_seconds": sum(metrics("gpu_seconds")),
            "mean_input_tokens": _mean([float(value) for value in input_tokens]),
            "mean_output_tokens": _mean([float(value) for value in output_tokens]),
            "token_coverage": len(input_tokens) / len(attempts) if attempts else 0.0,
        })
    columns = ["condition", "harness", "model", "axis", "tasks", "attempts",
               "successes", "success_rate", "success_rate_ci95_low",
               "success_rate_ci95_high", "mean_check_score", "any_pass_at_k",
               "reliability_at_k", "k_min", "k_max"]
    columns += ["mean_agent_wall_seconds", "mean_md_queue_seconds", "mean_md_run_seconds",
                "mean_total_wall_seconds", "total_gpu_seconds", "mean_input_tokens",
                "mean_output_tokens", "token_coverage"]
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
                    in sorted(failures.items())]
    with (out / "failures.csv").open("w", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=["condition", "harness", "model", "axis",
                                                        "failure_stage", "failure_code", "count"])
        writer.writeheader()
        writer.writerows(failure_rows)
    payload = {"schema_version": 1, "generated_at": _now(), "attempts": len(rows),
               "incomplete_attempts": incomplete, "summary": summaries,
               "failures": failure_rows}
    _write_json(out / "summary.json", payload)
    return {"success": not incomplete, "out_dir": str(out), **payload}


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
