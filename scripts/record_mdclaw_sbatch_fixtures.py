"""Record the sbatch scripts MDClaw's generators write, for the shim's tests.

Run inside an MDClaw image (its own package, nothing on PYTHONPATH but this
checkout) so the recorded bytes are what that image's submit_job and
submit_array_job would hand the sbatch shim:

    singularity exec --no-home --bind "$PWD:$PWD" --pwd "$PWD" \\
        --env PYTHONPATH="$PWD" <image.sif> /opt/mdclaw/bin/python \\
        scripts/record_mdclaw_sbatch_fixtures.py tests/test_benchmark/fixtures/mdclaw_sbatch \
        <label> [<image sha256> <image source commit>]

Inputs are neutral (image /images/mdclaw.sif, job dir /work/study/jobs/main,
frozen source /frozen/src). MDClaw also binds the working directory and writes
its static binds sorted, so the working directory is written as /work and the
static binds re-sorted after that; fixtures from different images and
checkout locations then differ only where the generators do. tests/test_benchmark/test_mdclaw_sbatch_fixtures.py feeds
every fixture through guard_script without importing MDClaw, and, where MDClaw
is importable, checks that the generators still write one of the recorded
forms. Record a new label whenever the campaign image changes.
"""

from __future__ import annotations

import json
import os
import re
import sys
from pathlib import Path

os.environ.pop("MDCLAW_MODULE_LOADS", None)

JOB = "/work/study/jobs/main"
IMAGE = "/images/mdclaw.sif"


def generate() -> dict[str, str]:
    from mdclaw.slurm import sbatch

    common = dict(job_name="probe", partition="gpu", cpus_per_task=4, gpus=1, gres=None,
                  time_limit="00:20:00", memory="32G", dependency=None, output_dir=JOB,
                  account=None, qos=None, extra_sbatch=None, environment=None,
                  stdout_log=JOB + "/probe_%j.out", stderr_log=JOB + "/probe_%j.err")
    command = f"mdclaw --job-dir {JOB} --node-id min_001 run_minimization --platform CUDA"
    tasks = [{"command": command.replace("min_001", f"min_00{i}"), "job_dir": JOB,
              "node_id": f"min_00{i}"} for i in (1, 2)]
    image = {"image": IMAGE, "source_mode": "image", "extra_flags": "--nv"}
    overlay = {"image": IMAGE, "source_mode": "overlay", "source_root": "/frozen/src",
               "extra_flags": "--nv"}
    variants = {
        "image_single": ("single", image, {}),
        "image_array": ("array", image, {}),
        "image_single_dependency": ("single", image, {"dependency": "afterok:1"}),
        "image_array_dependency": ("array", image, {"dependency": "afterok:1"}),
        "overlay_single": ("single", overlay, {}),
        "overlay_array": ("array", overlay, {}),
        "image_single_resolved": ("single", {**image, "runtime": "singularity",
                                             "runtime_resolved": "/usr/bin/singularity"}, {}),
        "image_array_resolved": ("array", {**image, "runtime": "singularity",
                                           "runtime_resolved": "/usr/bin/singularity"}, {}),
        "image_single_apptainer": ("single", {**image, "runtime": "apptainer"}, {}),
        "image_mps": ("mps", image, {}),
    }
    out = {}
    for name, (kind, container, extra) in variants.items():
        arguments = {**common, **extra, "container": dict(container)}
        if kind == "single":
            out[name] = sbatch._generate_sbatch_script(command=command, nodes=1, ntasks=1,
                                                       nodelist=None, **arguments)
        elif kind == "array":
            out[name] = sbatch._generate_array_sbatch_script(tasks=tasks, max_concurrent=None,
                                                             **arguments)
        elif hasattr(sbatch, "_generate_mps_sbatch_script"):
            out[name] = sbatch._generate_mps_sbatch_script(tasks=tasks,
                                                           active_thread_percentage=100,
                                                           **arguments)
    cwd = str(Path.cwd().resolve())
    return {name: normalise(text, cwd) for name, text in out.items()}


def normalise(text: str, cwd: str) -> str:
    """Write the working-directory bind as /work and keep MDClaw's bind order.

    MDClaw joins sorted(static binds) + runtime binds (``$``-prefixed shell
    expressions, MPS only), so re-sorting after the rename gives the same
    bytes wherever the checkout lives.
    """
    def rebind(match: re.Match) -> str:
        entries = ["/work" if entry == cwd else entry for entry in match.group(1).split(",")]
        static = sorted({entry for entry in entries if not entry.startswith("$")})
        runtime = [entry for entry in entries if entry.startswith("$")]
        return "--bind " + ",".join(static + runtime)

    return re.sub(r"--bind (\S+)", rebind, text)


def main(argv: list[str]) -> int:
    import mdclaw

    outdir = Path(argv[0]) / argv[1]
    outdir.mkdir(parents=True, exist_ok=True)
    scripts = generate()
    for name, text in scripts.items():
        (outdir / f"{name}.sbatch").write_text(text)
    provenance = {"label": argv[1], "mdclaw_module": mdclaw.__file__,
                  "mdclaw_version": getattr(mdclaw, "__version__", None)}
    if len(argv) >= 4:
        provenance.update(image_sha256=argv[2], image_source_commit=argv[3])
    (outdir / "SOURCE.json").write_text(json.dumps(provenance, sort_keys=True) + "\n")
    print(outdir, sorted(scripts))
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
