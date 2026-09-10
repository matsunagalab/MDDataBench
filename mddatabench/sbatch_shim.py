"""Transparent ``sbatch`` wrapper that records the submitted job id."""

from __future__ import annotations

import json
import os
import random
import re
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

if __package__:
    from .source_overlay import prepare_submission, source_mode
else:
    from source_overlay import prepare_submission, source_mode


def _without_time_limit(arguments: list[str]) -> list[str]:
    """Remove agent-provided limits so the campaign limit is authoritative."""
    result, skip = [], False
    for argument in arguments:
        if skip:
            skip = False
            continue
        if argument in {"--time", "-t"}:
            skip = True
            continue
        if argument.startswith("--time=") or (
                argument.startswith("-t") and len(argument) > 2):
            continue
        result.append(argument)
    return result


def _without_node_target(arguments: list[str]) -> list[str]:
    """Remove agent-provided partition/node choices when the operator pins them."""
    result, skip = [], False
    for argument in arguments:
        if skip:
            skip = False
            continue
        if argument in {"--partition", "-p", "--nodelist", "-w"}:
            skip = True
            continue
        if argument.startswith(("--partition=", "--nodelist=")) or (
                argument.startswith(("-p", "-w")) and len(argument) > 2):
            continue
        result.append(argument)
    return result


_JOB_ID = re.compile(r"Submitted batch job\s+(\d+)|^\s*(\d+)(?:;\S*)?\s*$", re.MULTILINE)


def job_id_from_stdout(stdout: str) -> str | None:
    """The job id from sbatch's normal or ``--parsable`` (``id;cluster``) output.

    Measured 2026-09-10: a sif_only agent submitted with ``--parsable``, the
    id was not recognised, and the attempt was sealed as ``agent_no_submission``
    although its jobs ran and no scorer was attached.
    """
    match = _JOB_ID.search(stdout or "")
    return (match.group(1) or match.group(2)) if match else None


def _record(path: Path, arguments: list[str], stdout: str, returncode: int,
            source_overlay: dict | None = None, stderr: str = "") -> None:
    row = {"at": datetime.now(timezone.utc).isoformat(), "event": "sbatch",
           "argv": arguments, "job_id": job_id_from_stdout(stdout),
           "returncode": returncode, "stdout": (stdout or "")[:500],
           "stderr": (stderr or "")[-1000:]}
    if source_overlay is not None:
        row["source_overlay"] = source_overlay
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a") as handle:
        handle.write(json.dumps(row, sort_keys=True) + "\n")


_IMAGE_ONLY_VARIABLES = ("LD_PRELOAD", "LD_LIBRARY_PATH", "PYTHONPATH", "PYTHONHOME")


def _worker_environment(environment) -> dict:
    """The environment sbatch hands to the job when the shim runs inside a SIF.

    Image-mode agents call ``mdclaw submit_job`` through ``singularity exec``,
    so this shim runs inside the image and ``sbatch`` would export the image's
    environment to the worker. Measured 2026-09-09 on Rikyu: the job's PATH
    lacked the host container runtime (``singularity: command not found``) and
    its LD_PRELOAD named a library the host cannot open. Outside a container
    the environment is returned unchanged.
    """
    environment = dict(environment)
    if not (environment.get("APPTAINER_CONTAINER") or environment.get("SINGULARITY_CONTAINER")):
        return environment
    for key in list(environment):
        if key.startswith(("APPTAINER", "SINGULARITY")) or key in _IMAGE_ONLY_VARIABLES:
            del environment[key]
    host_path = environment.get("MDCLAW_SLURM_PATH")
    if host_path:
        environment["PATH"] = host_path
    return environment


def _declared_source_mode(manifest_path: str) -> str:
    try:
        with open(manifest_path) as handle:
            return source_mode(json.load(handle))
    except (OSError, ValueError, KeyError):
        return "overlay"


_PASSTHROUGH = frozenset({"--version", "-V", "--help", "-h", "--usage"})


def main(argv=None) -> int:
    arguments = list(sys.argv[1:] if argv is None else argv)
    real = os.environ.get("MDDATABENCH_REAL_SBATCH", "/usr/bin/sbatch")
    if any(argument in _PASSTHROUGH for argument in arguments):
        # MDClaw probes `sbatch --version` before submitting; that is not a
        # job and must neither be guarded nor recorded as a submission.
        completed = subprocess.run([real, *arguments], text=True, capture_output=True, check=False)
        sys.stdout.write(completed.stdout)
        sys.stderr.write(completed.stderr)
        return completed.returncode
    limit = os.environ.get("MDDATABENCH_MD_TIME_LIMIT", "00:20:00")
    partition = os.environ.get("MDDATABENCH_MD_PARTITION")
    nodelist = os.environ.get("MDDATABENCH_MD_NODELIST")
    scheduler_args = [f"--time={limit}"]
    if partition:
        scheduler_args.append(f"--partition={partition}")
    if nodelist:
        # Slurm's --nodelist requires every listed host, so a two-node value
        # made each job wait for the first one: measured 2026-08-31, jobs sat
        # in ReqNodeNotAvail on a full n2 while n4 ran one job and idled.
        # One host per submission, drawn at random, spreads the campaign.
        choices = [host.strip() for host in nodelist.split(",") if host.strip()]
        scheduler_args.append(f"--nodelist={random.choice(choices)}")
    cleaned = _without_time_limit(arguments)
    if partition or nodelist:
        cleaned = _without_node_target(cleaned)
    submitted = [*scheduler_args, *cleaned]
    overlay = None
    manifest_path = os.environ.get("MDDATABENCH_MANIFEST")
    if manifest_path:
        try:
            submitted, overlay = prepare_submission(submitted, manifest_path)
        except (OSError, ValueError, KeyError) as exc:
            mode = _declared_source_mode(manifest_path)
            detail = (f"mddatabench_source_overlay_invalid: {exc}. "
                      f"Use configure_container --source-mode {mode} and submit_job/"
                      "submit_array_job with a direct mdclaw payload.\n")
            sys.stderr.write(detail)
            event_log = os.environ.get("MDDATABENCH_EVENT_LOG")
            if event_log:
                _record(Path(event_log), submitted, "", 2, {"error": detail.strip()})
            return 2
    completed = subprocess.run([real, *submitted], text=True, capture_output=True,
                               check=False, env=_worker_environment(os.environ))
    sys.stdout.write(completed.stdout)
    sys.stderr.write(completed.stderr)
    event_log = os.environ.get("MDDATABENCH_EVENT_LOG")
    if event_log:
        _record(Path(event_log), submitted, completed.stdout, completed.returncode, overlay,
                completed.stderr)
    return completed.returncode


if __name__ == "__main__":
    raise SystemExit(main())
