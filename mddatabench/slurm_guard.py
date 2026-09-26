"""Slurm clients as a sandboxed attempt sees them: its own jobs, nothing else.

Why. Agents run as the campaign owner, so a Slurm client they call reaches every
job the owner has. On 2026-09-26 19:53 JST an agent of glm-5.3-flash-3cond-full-v3
(005_membrane_6a93 sif_only r2) meant to clear its own old chain and ran
``scancel $(squeue -u $USER -h -o '%i')``: it cancelled every job of the owner,
nine production segments of an unrelated project 14-22 h into their run, their
nine successors, four SST2 jobs, and three jobs of other attempts.

What. Inside the attempt sandbox (``mddatabench/sandbox.py``) ``/usr/bin/scancel``,
``scontrol``, ``squeue``, ``sacct`` and the allocation and scheduling clients are
replaced by launchers that run this module; the real binaries sit in
``/.mddatabench-slurm``. A job belongs to the attempt when the shim recorded it
(``sbatch-events.jsonl``) or its working directory lies inside the attempt.

- ``squeue`` and ``sacct`` list only the attempt's jobs.
- ``scancel`` takes job ids and cancels those of the attempt; selecting jobs by
  user, name, partition, state, account, QOS, node or reservation is refused.
- ``scontrol`` shows the cluster and the attempt's own jobs, and changes only the
  attempt's own jobs.
- ``srun``, ``salloc``, ``sattach``, ``scrontab`` and ``strigger`` are refused:
  MD runs through sbatch, and a crontab or trigger would outlive the attempt.

Like the sandbox, this stops what an agent does by accident, not an agent that
sets out to find the real binaries.

Stdlib only: it runs with the host python3 in the sandbox and with the image's
python inside the MDClaw container.
"""

from __future__ import annotations

import json
import os
import re
import subprocess
import sys
from pathlib import Path

REAL_DIR = os.environ.get("MDDATABENCH_SLURM_REAL_DIR", "/.mddatabench-slurm")
GUARDED = ("scancel", "scontrol", "squeue", "sacct", "srun", "salloc", "sattach",
           "scrontab", "strigger")
REFUSED = ("srun", "salloc", "sattach", "scrontab", "strigger")
# Help and version only; per tool, because `squeue -h` is --noheader (the
# incident's own `squeue -u $USER -h -o '%i'`) while `sacct -h` is help.
_HELP = {"--help", "--usage", "-V", "--version"}
_PASSTHROUGH = {"squeue": _HELP, "scancel": _HELP, "sacct": _HELP | {"-h"},
                "scontrol": _HELP | {"-h"}}
_JOB_ID = re.compile(r"^(\d+)(?:_(?:\d+|\[[\d,\-%]+\]))?(?:\.(?:\d+|batch|extern|interactive))?$")
_NO_MATCH = "--name=mddatabench-no-job-of-this-attempt"


def _real(tool: str) -> str:
    return str(Path(REAL_DIR) / tool)


def _say(tool: str, message: str) -> None:
    sys.stderr.write(f"{tool}: {message}\n")


class Attempt:
    """The attempt this process belongs to, and which jobs are its own."""

    def __init__(self, environ=os.environ):
        manifest = environ.get("MDDATABENCH_MANIFEST")
        self.root = Path(manifest).parent if manifest else None
        self.uid = str(os.getuid())
        self.recorded: set[str] = set()
        events = environ.get("MDDATABENCH_EVENT_LOG")
        if not events and self.root is not None:
            events = str(self.root / "workspace" / ".mddatabench" / "sbatch-events.jsonl")
        try:
            for line in Path(events).read_text().splitlines():
                try:
                    job = json.loads(line).get("job_id")
                except ValueError:
                    continue
                if job:
                    self.recorded.add(str(job).split("_")[0])
        except (OSError, TypeError):
            pass

    def inside(self, workdir: str) -> bool:
        if self.root is None or not workdir:
            return False
        root = str(self.root).rstrip("/") + "/"
        return workdir.rstrip("/") + "/" == root or workdir.startswith(root)

    def queued(self) -> set[str]:
        """Base ids of this attempt's jobs the controller still knows."""
        out = subprocess.run([_real("squeue"), "-h", "-u", self.uid, "-o", "%i|%Z"],
                             capture_output=True, text=True, check=False).stdout
        own = set()
        for line in out.splitlines():
            job, _, workdir = line.partition("|")
            base = job.strip().split("_")[0]
            if base and (base in self.recorded or self.inside(workdir.strip())):
                own.add(base)
        return own

    def history(self) -> set[str]:
        """Base ids of this attempt's jobs in accounting, recorded or run inside it."""
        out = subprocess.run([_real("sacct"), "-X", "-n", "-P", "-u", self.uid, "-S", "now-7days",
                              "-o", "JobIDRaw,WorkDir"], capture_output=True, text=True,
                             check=False).stdout
        own = set(self.recorded)
        for line in out.splitlines():
            job, _, workdir = line.partition("|")
            if self.inside(workdir.strip()):
                own.add(job.strip().split("_")[0].split(".")[0])
        return {job for job in own if job}

    def owns(self, job_ids: list[str]) -> set[str]:
        """The subset of these base ids that belong to the attempt."""
        own = {job for job in job_ids if job in self.recorded}
        unknown = [job for job in job_ids if job not in own]
        if unknown:
            out = subprocess.run([_real("squeue"), "-h", "-j", ",".join(unknown), "-o", "%i|%Z"],
                                 capture_output=True, text=True, check=False).stdout
            for line in out.splitlines():
                job, _, workdir = line.partition("|")
                if self.inside(workdir.strip()):
                    own.add(job.strip().split("_")[0])
        return own


def _split_jobs(arguments: list[str]) -> tuple[list[str], list[str]]:
    """Remove ``-j/--jobs`` from the arguments and return (arguments, job ids)."""
    kept, jobs, skip = [], [], False
    for index, argument in enumerate(arguments):
        if skip:
            skip = False
            continue
        if argument in {"-j", "--jobs"}:
            if index + 1 < len(arguments):
                jobs += [j for j in arguments[index + 1].split(",") if j]
            skip = True
        elif argument.startswith("--jobs="):
            jobs += [j for j in argument.split("=", 1)[1].split(",") if j]
        elif argument.startswith("-j") and len(argument) > 2:
            jobs += [j for j in argument[2:].split(",") if j]
        else:
            kept.append(argument)
    return kept, jobs


def _base(job: str) -> str | None:
    match = _JOB_ID.match(job.strip())
    return match.group(1) if match else None


def _listing(tool: str, arguments: list[str], own: set[str]) -> list[str]:
    arguments, requested = _split_jobs(arguments)
    if requested:
        chosen = [job for job in requested if _base(job) in own]
    else:
        chosen = sorted(own, key=int)
    return [_real(tool), *arguments, (f"--jobs={','.join(chosen)}" if chosen else _NO_MATCH)]


def squeue(arguments: list[str], attempt: Attempt) -> int:
    if _PASSTHROUGH["squeue"] & set(arguments):
        return subprocess.call([_real("squeue"), *arguments])
    return subprocess.call(_listing("squeue", arguments, attempt.queued()))


def sacct(arguments: list[str], attempt: Attempt) -> int:
    if _PASSTHROUGH["sacct"] & set(arguments):
        return subprocess.call([_real("sacct"), *arguments])
    return subprocess.call(_listing("sacct", arguments, attempt.history()))


_SCANCEL_SELECTORS = {"-u", "--user", "--me", "-n", "--name", "--jobname", "-p", "--partition",
                      "-t", "--state", "-A", "--account", "-q", "--qos", "-w", "--nodelist",
                      "-R", "--reservation", "-M", "--clusters", "--wckey", "-i", "--interactive",
                      "--sibling"}
_SCANCEL_VALUE = {"-s", "--signal", "-n", "--name", "--jobname", "-p", "--partition", "-t",
                  "--state", "-A", "--account", "-q", "--qos", "-w", "--nodelist", "-R",
                  "--reservation", "-M", "--clusters", "-u", "--user", "--wckey", "--sibling"}


def scancel(arguments: list[str], attempt: Attempt) -> int:
    if _PASSTHROUGH["scancel"] & set(arguments):
        return subprocess.call([_real("scancel"), *arguments])
    options, jobs, skip = [], [], False
    for index, argument in enumerate(arguments):
        if skip:
            skip = False
            continue
        name = argument.split("=", 1)[0]
        if name in _SCANCEL_SELECTORS or (argument.startswith("-") and len(argument) > 2
                                          and argument[:2] in _SCANCEL_SELECTORS
                                          and not argument.startswith("--")):
            _say("scancel", "in this benchmark attempt scancel cancels only the attempt's own jobs, "
                            "named by job id (for example `scancel 12345`); selecting jobs by user, "
                            f"name, partition, state, account, QOS, node or reservation ({name}) is "
                            "not available. `squeue` lists the attempt's jobs.")
            return 1
        if argument.startswith("-"):
            options.append(argument)
            if name in _SCANCEL_VALUE and "=" not in argument:
                if index + 1 < len(arguments):
                    options.append(arguments[index + 1])
                skip = True
            continue
        jobs += [job for job in re.split(r"[,\s]+", argument) if job]
    bases = {job: _base(job) for job in jobs}
    bad = [job for job, base in bases.items() if base is None]
    own = attempt.owns(sorted({b for b in bases.values() if b}))
    allowed = [job for job, base in bases.items() if base in own]
    refused = [job for job, base in bases.items() if base is not None and base not in own]
    for job in bad:
        _say("scancel", f"error: invalid job id {job}")
    for job in refused:
        _say("scancel", f"error: job {job} is not a job of this benchmark attempt; not cancelled")
    status = 0
    if allowed or not jobs:
        status = subprocess.call([_real("scancel"), *options, *allowed])
    return 1 if (bad or refused) else status


_SCONTROL_READ = {"show", "ping", "version", "help", "listpids", "pidinfo", "errnumstr",
                  "getaddrs", "hostlist", "hostlistsorted", "hostnames"}
_SCONTROL_JOB_ACTIONS = {"hold", "uhold", "release", "requeue", "requeuehold", "suspend",
                         "resume", "top", "notify", "wait_job"}


def scontrol(arguments: list[str], attempt: Attempt) -> int:
    if _PASSTHROUGH["scontrol"] & set(arguments) and not any(a for a in arguments if not a.startswith("-")):
        return subprocess.call([_real("scontrol"), *arguments])
    words = [a for a in arguments if not a.startswith("-")]
    options = [a for a in arguments if a.startswith("-")]
    command = words[0].lower() if words else ""
    rest = words[1:]
    if command == "show" and rest and rest[0].lower() in {"job", "jobs", "step", "steps"}:
        targets = [t for t in rest[1:]]
        bases = [(t, _base(t.split("=", 1)[-1])) for t in targets]
        if targets:
            own = attempt.owns(sorted({b for _, b in bases if b}))
            foreign = [t for t, b in bases if b not in own]
            if foreign:
                _say("scontrol", f"slurm_load_jobs error: Invalid job id specified ({', '.join(foreign)} "
                                 "is not a job of this benchmark attempt)")
                return 1
            return subprocess.call([_real("scontrol"), *options, *words])
        own = sorted(attempt.queued(), key=int)
        if not own:
            print("No jobs in the system")
            return 0
        status = 0
        for job in own:
            status |= subprocess.call([_real("scontrol"), *options, "show", rest[0], job])
        return status
    if command in _SCONTROL_READ:
        return subprocess.call([_real("scontrol"), *arguments])
    if command in _SCONTROL_JOB_ACTIONS or command == "update":
        if command == "update":
            keys = {w.split("=", 1)[0].lower(): w.split("=", 1)[1] for w in rest if "=" in w}
            jobs = [j for j in re.split(r"[,\s]+", keys.get("jobid", "") or keys.get("job", "")) if j]
            if not jobs or set(keys) & {"nodename", "partitionname", "reservationname",
                                        "frontendname"}:
                _say("scontrol", "update is available here only for the attempt's own jobs, "
                                 "as `scontrol update JobId=<id> ...`")
                return 1
        else:
            jobs = [j for w in rest for j in re.split(r"[,\s]+", w) if j and "=" not in j]
            if any("=" in w for w in rest) or not jobs:
                _say("scontrol", f"{command} is available here only for the attempt's own jobs, "
                                 "named by job id")
                return 1
        bases = {job: _base(job) for job in jobs}
        own = attempt.owns(sorted({b for b in bases.values() if b}))
        foreign = [job for job, base in bases.items() if base not in own]
        if foreign:
            _say("scontrol", f"{', '.join(foreign)} is not a job of this benchmark attempt; "
                             f"{command} refused")
            return 1
        return subprocess.call([_real("scontrol"), *arguments])
    _say("scontrol", f"`scontrol {command}` is not available in a benchmark attempt; `scontrol show` "
                     "and actions on the attempt's own jobs are")
    return 1


def refused(tool: str, arguments: list[str]) -> int:
    if (_HELP | {"-h"}) & set(arguments):
        return subprocess.call([_real(tool), *arguments])
    _say(tool, "not available in a benchmark attempt: run MD through sbatch (MDClaw submit_job), "
               "and run commands directly inside the batch script rather than through srun; "
               "allocations, crontabs and triggers would outlive the attempt.")
    return 1


def main(argv: list[str] | None = None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    if not argv or argv[0] not in GUARDED:
        sys.stderr.write(f"usage: slurm_guard.py {{{','.join(GUARDED)}}} [arguments]\n")
        return 2
    tool, arguments = argv[0], argv[1:]
    if tool in REFUSED:
        return refused(tool, arguments)
    attempt = Attempt()
    return {"squeue": squeue, "sacct": sacct, "scancel": scancel,
            "scontrol": scontrol}[tool](arguments, attempt)


if __name__ == "__main__":
    raise SystemExit(main())
