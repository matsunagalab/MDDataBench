"""Transparent ``sbatch`` wrapper that records the submitted job id."""

from __future__ import annotations

import json
import os
import re
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path


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


def _record(path: Path, arguments: list[str], stdout: str, returncode: int) -> None:
    match = re.search(r"Submitted batch job\s+(\d+)", stdout)
    row = {"at": datetime.now(timezone.utc).isoformat(), "event": "sbatch",
           "argv": arguments, "job_id": match.group(1) if match else None,
           "returncode": returncode}
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a") as handle:
        handle.write(json.dumps(row, sort_keys=True) + "\n")


def main(argv=None) -> int:
    arguments = list(sys.argv[1:] if argv is None else argv)
    real = os.environ.get("MDDATABENCH_REAL_SBATCH", "/usr/bin/sbatch")
    limit = os.environ.get("MDDATABENCH_MD_TIME_LIMIT", "01:00:00")
    submitted = [f"--time={limit}", *_without_time_limit(arguments)]
    completed = subprocess.run([real, *submitted], text=True, capture_output=True,
                               check=False)
    sys.stdout.write(completed.stdout)
    sys.stderr.write(completed.stderr)
    event_log = os.environ.get("MDDATABENCH_EVENT_LOG")
    if event_log:
        _record(Path(event_log), submitted, completed.stdout, completed.returncode)
    return completed.returncode


if __name__ == "__main__":
    raise SystemExit(main())
