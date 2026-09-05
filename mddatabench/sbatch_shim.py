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
    from .source_overlay import prepare_submission
else:
    from source_overlay import prepare_submission


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


def _record(path: Path, arguments: list[str], stdout: str, returncode: int,
            source_overlay: dict | None = None) -> None:
    match = re.search(r"Submitted batch job\s+(\d+)", stdout)
    row = {"at": datetime.now(timezone.utc).isoformat(), "event": "sbatch",
           "argv": arguments, "job_id": match.group(1) if match else None,
           "returncode": returncode}
    if source_overlay is not None:
        row["source_overlay"] = source_overlay
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a") as handle:
        handle.write(json.dumps(row, sort_keys=True) + "\n")


def main(argv=None) -> int:
    arguments = list(sys.argv[1:] if argv is None else argv)
    real = os.environ.get("MDDATABENCH_REAL_SBATCH", "/usr/bin/sbatch")
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
            detail = (f"mddatabench_source_overlay_invalid: {exc}. "
                      "Use configure_container --source-mode overlay and submit_job/"
                      "submit_array_job with a direct mdclaw payload.\n")
            sys.stderr.write(detail)
            event_log = os.environ.get("MDDATABENCH_EVENT_LOG")
            if event_log:
                _record(Path(event_log), submitted, "", 2, {"error": detail.strip()})
            return 2
    completed = subprocess.run([real, *submitted], text=True, capture_output=True,
                               check=False)
    sys.stdout.write(completed.stdout)
    sys.stderr.write(completed.stderr)
    event_log = os.environ.get("MDDATABENCH_EVENT_LOG")
    if event_log:
        _record(Path(event_log), submitted, completed.stdout, completed.returncode, overlay)
    return completed.returncode


if __name__ == "__main__":
    raise SystemExit(main())
