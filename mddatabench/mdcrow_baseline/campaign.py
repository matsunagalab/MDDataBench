"""Plan, submit, seal and count an MDCrow baseline campaign.

One attempt is one Slurm job with one GPU. Inside it, the attempt sandbox
(``mddatabench/sandbox.py``) shows only the attempt's workspace and record
directories, MDCrow's environment, the runner, and the gateway key file; the
reference bundles, ``task.json``, the harness checkout and other attempts do
not exist there. MDCrow runs its LLM loop and its MD in that one process, so
the agent and MD share one wall-clock budget (``deadline_seconds``, default
5400 s = the MDClaw agent limit of 1800 s plus three 20-minute MD jobs).

An evaluator job with ``afterany`` on the attempt's job then converts
(``convert.py``), scores the portable layout with the unchanged scorer, and
seals ``result.json``.

Commands (``python -m mddatabench.mdcrow_baseline.campaign <command> --help``):

    init      plan attempts and freeze the inputs
    dispatch  submit attempts, at most ``--max-running`` at a time
    finalize  seal one attempt (run by the evaluator job)
    reset     retire an attempt's run after an infrastructure failure
    status    count attempt states
    collect   pass^k, pass@1 with Wilson intervals, failures, GPU time, tokens

Host Python, stdlib plus mddatabench.
"""

from __future__ import annotations

import argparse
import datetime as _dt
import hashlib
import json
import math
import os
import re
import shlex
import shutil
import subprocess
import sys
import time
from pathlib import Path

from mddatabench import sandbox as sb

HERE = Path(__file__).resolve().parent
PACKAGE_ROOT = HERE.parents[1]          # the checkout holding mddatabench/

DEFAULT_BASE_URL = "https://api.rikyu.r-ccs.riken.jp/v1"
INFRA_STATES = {"NODE_FAIL", "PREEMPTED", "BOOT_FAIL", "OUT_OF_MEMORY", "DEADLINE"}
GATEWAY_ERRORS = ("APIConnectionError", "APITimeoutError", "InternalServerError",
                  "RateLimitError", "ServiceUnavailableError", "BadGatewayError",
                  "Connection error", "502 Bad Gateway", "503 Service", "504 Gateway")


# ---- small helpers -----------------------------------------------------------

def _now() -> str:
    return _dt.datetime.now().astimezone().isoformat(timespec="seconds")


def _json(path: Path):
    return json.loads(Path(path).read_text())


def _write_json(path: Path, value) -> None:
    path = Path(path)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(value, indent=2, sort_keys=True, default=str) + "\n")
    os.replace(tmp, path)


def _event(attempt: Path, kind: str, **fields) -> None:
    with open(attempt / "events.jsonl", "a") as handle:
        handle.write(json.dumps({"t": _now(), "event": kind, **fields}, default=str) + "\n")


def _slug(value: str) -> str:
    return re.sub(r"[^A-Za-z0-9._-]+", "-", value).strip("-")


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _git(path: Path, *args: str) -> str | None:
    completed = subprocess.run(["git", "-C", str(path), *args], capture_output=True,
                               text=True, check=False)
    return completed.stdout.strip() if completed.returncode == 0 else None


def wilson(successes: int, total: int, z: float = 1.959963984540054) -> tuple[float, float]:
    if total == 0:
        return (0.0, 0.0)
    p = successes / total
    denominator = 1 + z * z / total
    centre = (p + z * z / (2 * total)) / denominator
    half = z * math.sqrt(p * (1 - p) / total + z * z / (4 * total * total)) / denominator
    return (max(0.0, centre - half), min(1.0, centre + half))


def attempt_dirs(root: Path) -> list[Path]:
    return sorted(p.parent for p in Path(root).glob("attempts/*/*/manifest.json"))


# ---- init ----------------------------------------------------------------------

def _tasks(dataset: Path, splits: list[str], task_ids: list[str]) -> list[dict]:
    entries = _json(dataset / "dataset.json")["tasks"]
    chosen = [e for e in entries
              if (task_ids and e["task_id"] in task_ids)
              or (not task_ids and e["split"] in splits)]
    missing = sorted(set(task_ids) - {e["task_id"] for e in chosen})
    if missing:
        raise SystemExit(f"tasks not in the dataset: {missing}")
    return chosen


def _sandbox_plan(attempt: Path, spec: dict) -> dict:
    """Everything the attempt's process may see; nothing else exists inside."""
    home = os.path.expanduser("~")
    workspace = attempt / "workspace"
    ops = sb._system_ops()
    ops.append(sb._op("bind", home, src=str(attempt / "sandbox" / "home"), ro=False))
    ops.append(sb._op("bind", workspace, src=str(workspace), ro=False))
    ops.append(sb._op("bind", attempt / "record", src=str(attempt / "record"), ro=False))
    ops.append(sb._op("bind", spec["mdcrow_env"], src=spec["mdcrow_env"], ro=True))
    ops.append(sb._op("bind", spec["frozen_runner"], src=spec["frozen_runner"], ro=True))
    ops.append(sb._op("bind", spec["key_file_inside"], src=spec["key_file"], ro=True))
    return {"schema": sb.PLAN_SCHEMA, "role": "job", "attempt_id": attempt.name,
            "uid": os.getuid(), "gid": os.getgid(), "home": home,
            "newroot": str(attempt / "sandbox" / "root"), "cwd": str(workspace), "ops": ops}


def _agent_script(attempt: Path, manifest: dict, spec: dict) -> str:
    q = shlex.quote
    env = spec["mdcrow_env"]
    workspace = attempt / "workspace"
    inner = [
        "/usr/bin/env", "-i",
        f"PATH={env}/bin:/usr/bin:/bin", f"HOME={os.path.expanduser('~')}",
        "TMPDIR=/tmp", "LANG=C.UTF-8", "PYTHONNOUSERSITE=1", "PYTHONDONTWRITEBYTECODE=1",
        "CUDA_VISIBLE_DEVICES=${CUDA_VISIBLE_DEVICES}",
        f"OPENMM_CPU_THREADS={spec['cpus_per_task']}", f"OMP_NUM_THREADS={spec['cpus_per_task']}",
        f"{env}/bin/python", f"{spec['frozen_runner']}/runner.py",
        "--workspace", str(workspace),
        "--prompt-file", str(workspace / "task_prompt.md"),
        "--record-dir", str(attempt / "record"),
        "--model", manifest["model"],
        "--base-url", spec["base_url"],
        "--key-file", spec["key_file_inside"],
        "--key-provider", spec["key_provider"],
        "--max-tokens", str(spec["max_tokens"]),
        "--deadline-seconds", str(spec["deadline_seconds"]),
        "--platform", spec["platform"],
    ]
    command = " ".join(part if part.startswith("CUDA_VISIBLE_DEVICES=") else q(part)
                       for part in inner)
    return f"""#!/bin/bash
#SBATCH --job-name=mdcrow_{_slug(manifest['attempt_id'])[:60]}
#SBATCH --partition={spec['partition']}
#SBATCH --nodes=1
#SBATCH --ntasks=1
#SBATCH --cpus-per-task={spec['cpus_per_task']}
#SBATCH --gpus=1
#SBATCH --time={spec['slurm_time']}
#SBATCH --output={attempt}/slurm/agent_%j.out
#SBATCH --error={attempt}/slurm/agent_%j.err

cd {q(str(workspace))}
exec /usr/bin/python3 {q(str(attempt / 'sandbox' / 'sandbox.py'))} --plan {q(str(attempt / 'sandbox' / 'plan.json'))} -- \\
  {command}
"""


def init(experiment_dir: str, dataset_dir: str, mdcrow_env: str, mdcrow_source: str,
         models: str, splits: str = "test_v7,test_v7_membrane", tasks: str = "",
         replicates: int = 3, key_file: str = "~/.pi/agent/auth.json",
         key_provider: str = "rikyu", base_url: str = DEFAULT_BASE_URL,
         max_tokens: int = 32768, deadline_seconds: int = 5400,
         slurm_time: str = "01:40:00", cpus_per_task: int = 16, partition: str = "gpu",
         platform: str = "CUDA", expected_mdcrow_commit: str = "") -> dict:
    """Plan every task x model x replicate and freeze the inputs."""
    root = Path(experiment_dir).resolve()
    if root.exists() and any(root.iterdir()):
        raise SystemExit(f"{root} exists and is not empty")
    if root.is_relative_to(PACKAGE_ROOT):
        raise SystemExit("the experiment directory must be outside the checkout")
    dataset = Path(dataset_dir).resolve()
    env = Path(mdcrow_env).resolve()
    source = Path(mdcrow_source).resolve()
    commit = _git(source, "rev-parse", "HEAD")
    dirty = _git(source, "status", "--porcelain")
    if expected_mdcrow_commit and commit != expected_mdcrow_commit:
        raise SystemExit(f"MDCrow checkout is at {commit}, expected {expected_mdcrow_commit}")
    if dirty:
        raise SystemExit(f"MDCrow checkout has local changes:\n{dirty}")
    key = Path(os.path.expanduser(key_file)).resolve()
    if not key.is_file():
        raise SystemExit(f"no key file at {key}")
    root.mkdir(parents=True, exist_ok=True)

    frozen = root / "frozen"
    shutil.copytree(PACKAGE_ROOT / "mddatabench", frozen / "source" / "mddatabench",
                    ignore=shutil.ignore_patterns("__pycache__"))
    runner_dir = frozen / "runner"
    runner_dir.mkdir(parents=True)
    for name in ("runner.py", "recorder.py"):
        shutil.copy2(HERE / name, runner_dir / name)
    freeze_files = {name: str(path) for name, path in
                    (("pip_freeze", env.parent / "env-pip-freeze.txt"),
                     ("conda_list", env.parent / "env-conda-list.txt"),
                     ("environment_yaml", env.parent / "env-mdcrow.yaml"))
                    if path.is_file()}
    for name, path in freeze_files.items():
        shutil.copy2(path, frozen / Path(path).name)
    spec = {
        "schema_version": 1, "created": _now(), "experiment_dir": str(root),
        "dataset_dir": str(dataset), "dataset_id": _json(dataset / "dataset.json")["dataset_id"],
        "mddatabench_revision": _git(PACKAGE_ROOT, "rev-parse", "HEAD"),
        "mddatabench_dirty": bool(_git(PACKAGE_ROOT, "status", "--porcelain")),
        "mdcrow_source": str(source), "mdcrow_commit": commit,
        "mdcrow_remote": _git(source, "remote", "get-url", "origin"),
        "mdcrow_env": str(env),
        "mdcrow_env_files": {name: {"path": path, "sha256": _sha256(Path(path))}
                             for name, path in freeze_files.items()},
        "frozen_runner": str(runner_dir), "frozen_source": str(frozen / "source"),
        "models": [m for m in models.split(",") if m], "replicates": int(replicates),
        "splits": [s for s in splits.split(",") if s],
        "tasks": [t for t in tasks.split(",") if t],
        "key_file": str(key), "key_file_inside": "/.mddatabench-key/auth.json",
        "key_provider": key_provider, "base_url": base_url, "max_tokens": int(max_tokens),
        "deadline_seconds": int(deadline_seconds), "slurm_time": slurm_time,
        "cpus_per_task": int(cpus_per_task), "partition": partition, "platform": platform,
        "agent": {"agent_type": "Structured", "top_k_tools": "all", "use_memory": False,
                  "temperature": "MDCrow default (0.1)", "max_iterations": "LangChain default (15)",
                  "langchain_patches": ["empty reply -> parse error before OutputFixingParser "
                                        "(handle_parsing_errors retry)",
                                        "unfenced JSON action read as the fenced form",
                                        "JSON-string action_input decoded to an object",
                                        "tool TypeError returned as the observation"]},
    }
    _write_json(root / "experiment.json", spec)

    planned = []
    for entry in _tasks(dataset, spec["splits"], spec["tasks"]):
        task_file = dataset / entry["path"]
        prompt_file = dataset / entry["prompt"]
        task = _json(task_file)
        for model in spec["models"]:
            for replicate in range(1, spec["replicates"] + 1):
                cell = f"mdcrow__{_slug(model)}"
                attempt = root / "attempts" / entry["task_id"] / f"{cell}__r{replicate}"
                planned.append(_plan_attempt(attempt, spec, entry, task, task_file,
                                             prompt_file, model, replicate))
    return {"success": True, "experiment_dir": str(root), "attempts": len(planned),
            "mdcrow_commit": commit}


def _plan_attempt(attempt: Path, spec: dict, entry: dict, task: dict, task_file: Path,
                  prompt_file: Path, model: str, replicate: int) -> str:
    workspace = attempt / "workspace"
    workspace.mkdir(parents=True)
    (attempt / "record").mkdir()
    (attempt / "slurm").mkdir()
    shutil.copy2(prompt_file, workspace / "task_prompt.md")
    # MDCrow walks up from the cwd to a directory holding setup.py and puts
    # its ckpt/ there; without one it refuses to import.
    (workspace / "setup.py").write_text("")
    attempt_id = f"{entry['task_id']}__mdcrow__{_slug(model)}__r{replicate}"
    manifest = {
        "schema_version": 1, "attempt_id": attempt_id, "task_id": entry["task_id"],
        "axis": entry.get("axis"), "split": entry.get("split"), "condition": "mdcrow",
        "harness": "mdcrow", "model": model, "replicate": replicate,
        "reference": {"node": task["reference"]["node"],
                      "accession": task["reference"]["accession"]},
        "paths": {"task_file": str(task_file), "prompt_file": str(prompt_file),
                  "workspace": str(workspace), "record": str(attempt / "record")},
        "prompt_sha256": _sha256(prompt_file),
    }
    _write_json(attempt / "manifest.json", manifest)
    sandbox_dir = attempt / "sandbox"
    for name in ("home", "root"):
        (sandbox_dir / name).mkdir(parents=True)
    shutil.copy2(Path(sb.__file__), sandbox_dir / "sandbox.py")
    _write_json(sandbox_dir / "plan.json", _sandbox_plan(attempt, spec))
    script = attempt / "slurm" / "agent.sbatch"
    script.write_text(_agent_script(attempt, manifest, spec))
    script.chmod(0o755)
    _event(attempt, "planned", attempt_id=attempt_id)
    return attempt_id


# ---- submission ------------------------------------------------------------------

def _scorer_script(attempt: Path, manifest: dict, spec: dict, agent_job: str,
                   bundle_root: Path, scorer_sif: Path) -> str:
    q = shlex.quote
    bundle = bundle_root / f"{manifest['reference']['node']}_{manifest['reference']['accession']}"
    task_file = Path(manifest["paths"]["task_file"])
    source = spec["frozen_source"]
    binds = ",".join(sorted({str(attempt), str(bundle), source, str(task_file.parent)}))
    return f"""#!/bin/bash
#SBATCH --job-name=mdcrowscore_{_slug(manifest['attempt_id'])[:52]}
#SBATCH --partition={spec['partition']}
#SBATCH --nodes=1
#SBATCH --ntasks=1
#SBATCH --cpus-per-task=4
#SBATCH --time=00:30:00
#SBATCH --mem=32G
#SBATCH --dependency=afterany:{agent_job}
#SBATCH --output={attempt}/slurm/scorer_%j.out
#SBATCH --error={attempt}/slurm/scorer_%j.err

set +e
cd {q(str(attempt))}
sacct -X -n -P -j {agent_job} --format=JobIDRaw,State,Submit,Start,End,ElapsedRaw,AllocTRES,NodeList > md_sacct.txt
PYTHONPATH={q(source)} /usr/bin/python3 -m mddatabench.mdcrow_baseline.convert --attempt-dir {q(str(attempt))} > slurm/convert.json
score_rc=none
if [ -f submission/production.json ]; then
  singularity exec --bind {q(binds)} --env PYTHONPATH={q(source)} \\
    --env OPENBLAS_NUM_THREADS=1 --env OMP_NUM_THREADS=1 {q(str(scorer_sif))} \\
    python -m mddatabench score_portable_submission --submission-dir {q(str(attempt / 'submission'))} \\
    --bundle {q(str(bundle))} --task-file {q(str(task_file))} --out {q(str(attempt / 'score.json'))}
  score_rc=$?
fi
PYTHONPATH={q(source)} /usr/bin/python3 -m mddatabench.mdcrow_baseline.campaign finalize \\
  --attempt-dir {q(str(attempt))} --scorer-rc "$score_rc"
"""


def _sbatch(script: Path) -> tuple[str | None, str]:
    completed = subprocess.run(["sbatch", "--parsable", str(script)], capture_output=True,
                               text=True, check=False)
    if completed.returncode:
        return None, (completed.stderr or completed.stdout).strip()
    return completed.stdout.strip().split(";", 1)[0], ""


def submit_attempt(attempt: Path, spec: dict, bundle_root: Path, scorer_sif: Path) -> dict:
    manifest = _json(attempt / "manifest.json")
    jobs_file = attempt / "slurm" / "jobs.json"
    if jobs_file.exists():
        return _json(jobs_file)
    agent_job, error = _sbatch(attempt / "slurm" / "agent.sbatch")
    if agent_job is None:
        _event(attempt, "agent_submit_failed", error=error)
        raise RuntimeError(f"{attempt}: sbatch failed: {error}")
    scorer = attempt / "slurm" / "scorer.sbatch"
    scorer.write_text(_scorer_script(attempt, manifest, spec, agent_job, bundle_root,
                                     scorer_sif))
    scorer.chmod(0o755)
    scorer_job, error = _sbatch(scorer)
    jobs = {"agent_job": agent_job, "scorer_job": scorer_job, "submitted": _now(),
            "scorer_sif": str(scorer_sif), "scorer_sif_sha256": None,
            "bundle_root": str(bundle_root)}
    _write_json(jobs_file, jobs)
    _event(attempt, "submitted", **jobs, scorer_error=error or None)
    if scorer_job is None:
        raise RuntimeError(f"{attempt}: scorer sbatch failed: {error}")
    return jobs


def _queued(job_ids: list[str]) -> set[str]:
    if not job_ids:
        return set()
    completed = subprocess.run(["squeue", "-h", "-o", "%i", "-j", ",".join(job_ids)],
                               capture_output=True, text=True, check=False)
    return {line.strip() for line in completed.stdout.splitlines() if line.strip()}


def dispatch(experiment_dir: str, bundle_root: str, scorer_sif: str, max_running: int = 2,
             poll_seconds: int = 60, attempts: str = "", once: bool = False) -> dict:
    """Submit attempts in plan order, keeping at most ``max_running`` agent jobs queued or running.

    Each attempt's agent job holds one gateway stream, so ``max_running`` is
    also the number of concurrent LLM requests this campaign adds.
    """
    root = Path(experiment_dir).resolve()
    spec = _json(root / "experiment.json")
    sif = Path(scorer_sif).resolve()
    bundles = Path(bundle_root).resolve()
    wanted = {a for a in attempts.split(",") if a}
    todo = [a for a in attempt_dirs(root)
            if (not wanted or _json(a / "manifest.json")["attempt_id"] in wanted)]
    submitted = []
    while True:
        live = []
        for attempt in todo:
            jobs_file = attempt / "slurm" / "jobs.json"
            if jobs_file.exists() and not (attempt / "result.json").exists():
                live.append(_json(jobs_file)["agent_job"])
        running = _queued(live)
        waiting = [a for a in todo if not (a / "slurm" / "jobs.json").exists()]
        while waiting and len(running) < int(max_running):
            attempt = waiting.pop(0)
            jobs = submit_attempt(attempt, spec, bundles, sif)
            running.add(jobs["agent_job"])
            submitted.append({"attempt": str(attempt), **jobs})
            print(json.dumps({"t": _now(), "submitted": attempt.name,
                              "task": attempt.parent.name, **jobs}), flush=True)
        if not waiting or once:
            break
        time.sleep(int(poll_seconds))
    return {"success": True, "submitted": len(submitted), "jobs": submitted}


# ---- finalize ----------------------------------------------------------------------

def _sacct(path: Path, job_id: str | None) -> dict:
    if not job_id or not path.is_file():
        return {}
    for line in path.read_text().splitlines():
        fields = line.split("|")
        if len(fields) >= 7 and fields[0] == str(job_id):
            gpus = re.search(r"gres/gpu=(\d+)", fields[6])
            elapsed = int(fields[5]) if fields[5].isdigit() else None
            count = int(gpus.group(1)) if gpus else 0
            return {"state": fields[1].split()[0], "submit": fields[2], "start": fields[3],
                    "end": fields[4], "elapsed_seconds": elapsed, "gpus": count,
                    "gpu_seconds": elapsed * count if elapsed is not None else None,
                    "node": fields[7] if len(fields) > 7 else None}
    return {}


def classify(run: dict | None, sacct: dict, conversion: dict | None, score: dict | None,
             scorer_rc: str) -> dict:
    """The verdict and, for a failure, its stage and code.

    ``infra_*`` failures are the cluster's or the gateway's, not the agent's:
    they leave the denominator and the attempt is rerun. Everything else counts.
    """
    state = sacct.get("state")
    exit_reason = (run or {}).get("exit_reason")
    error = (run or {}).get("error") or ""
    scored = score is not None and scorer_rc == "0"
    checks_total = int(score.get("total") or 0) if scored else 0
    checks_passed = int(score.get("passed") or 0) if scored else 0
    passed = bool(scored and checks_total and checks_passed == checks_total)
    verdict = {"passed": passed, "checks_passed": checks_passed if scored else None,
               "checks_total": checks_total if scored else None,
               "failure_stage": None, "failure_code": None, "failure_detail": None}

    def fail(stage, code, detail):
        verdict.update(failure_stage=stage, failure_code=code, failure_detail=detail)
        return verdict

    if state in INFRA_STATES:
        return fail("infra", f"infra_{state.lower()}", f"agent job ended {state}")
    if run is None or exit_reason == "running":
        if state == "TIMEOUT":
            return fail("agent", "agent_timeout", "Slurm time limit; the runner wrote no exit")
        if state == "CANCELLED":
            return fail("infra", "infra_cancelled", "agent job cancelled before the runner ended")
        return fail("infra", "infra_runner_died",
                    f"runner left no exit record (job state {state})")
    if exit_reason == "exception" and any(name in error for name in GATEWAY_ERRORS):
        return fail("infra", "infra_gateway", error[:500])
    if passed:
        return verdict
    if scored:
        failed = [c.get("check_id") for c in score.get("checks") or [] if not c.get("passed")]
        if exit_reason == "deadline":
            return fail("agent", "agent_timeout", f"deadline; submitted run failed {failed}")
        return fail("evaluation", "checks_failed", f"failed: {failed}")
    if scorer_rc not in ("none", "0"):
        return fail("scorer", "scorer_error", f"scorer exited {scorer_rc}")
    if exit_reason == "deadline":
        return fail("agent", "agent_timeout", (conversion or {}).get("reason"))
    if exit_reason == "exception":
        return fail("agent", "agent_exception", error[:500])
    return fail("agent", "agent_no_submission", (conversion or {}).get("reason"))


def finalize(attempt_dir: str, scorer_rc: str = "none") -> dict:
    """Seal one attempt: ``result.json`` from run.json, conversion.json, score.json and sacct."""
    attempt = Path(attempt_dir).resolve()
    manifest = _json(attempt / "manifest.json")
    jobs = _json(attempt / "slurm" / "jobs.json") if (attempt / "slurm" / "jobs.json").exists() else {}
    run_path = attempt / "record" / "run.json"
    run = _json(run_path) if run_path.is_file() else None
    conversion = _json(attempt / "conversion.json") if (attempt / "conversion.json").is_file() else None
    score = _json(attempt / "score.json") if (attempt / "score.json").is_file() else None
    sacct = _sacct(attempt / "md_sacct.txt", jobs.get("agent_job"))
    verdict = classify(run, sacct, conversion, score, str(scorer_rc))
    chosen_meta = None
    if conversion and conversion.get("chosen"):
        meta_path = attempt / "record" / "openmm" / conversion["chosen"] / "meta.json"
        chosen_meta = _json(meta_path) if meta_path.is_file() else None
    substitutions = 0
    events = attempt / "record" / "openmm" / "events.jsonl"
    if events.is_file():
        substitutions = sum(1 for line in events.read_text().splitlines()
                            if '"platform_substituted"' in line)
    result = {
        "schema_version": 1, "sealed": _now(),
        **{k: manifest[k] for k in ("attempt_id", "task_id", "axis", "split", "condition",
                                    "harness", "model", "replicate")},
        **verdict,
        "metrics": {
            "exit_reason": (run or {}).get("exit_reason"),
            "agent_wall_seconds": (run or {}).get("wall_seconds"),
            "token_usage": (run or {}).get("token_usage"),
            "simulations_recorded": (run or {}).get("simulations_recorded"),
            "submitted_simulation": (conversion or {}).get("chosen"),
            "platform": (chosen_meta or {}).get("platform"),
            "platform_substitutions": substitutions,
            "agent_job": sacct,
            "gpu_seconds": sacct.get("gpu_seconds"),
        },
        "jobs": jobs,
    }
    _write_json(attempt / "result.json", result)
    _event(attempt, "sealed", passed=verdict["passed"], failure_code=verdict["failure_code"])
    return {"success": True, **result}


# ---- reset / status / collect -------------------------------------------------------

def reset(experiment_dir: str, attempts: str, reason: str) -> dict:
    """Retire the run of each named attempt (infrastructure failures only) and re-plan it."""
    root = Path(experiment_dir).resolve()
    spec = _json(root / "experiment.json")
    names = {a for a in attempts.split(",") if a}
    done = []
    for attempt in attempt_dirs(root):
        manifest = _json(attempt / "manifest.json")
        if manifest["attempt_id"] not in names:
            continue
        jobs_file = attempt / "slurm" / "jobs.json"
        if jobs_file.exists() and _queued([_json(jobs_file)["agent_job"]]):
            raise SystemExit(f"{manifest['attempt_id']}: its agent job is still queued")
        stamp = _dt.datetime.now().strftime("%Y%m%dT%H%M%S")
        retired = attempt.parent / ".retired" / f"{attempt.name}__{stamp}"
        retired.parent.mkdir(exist_ok=True)
        shutil.move(str(attempt), str(retired))
        (retired / "RETIRED").write_text(json.dumps({"t": _now(), "reason": reason}) + "\n")
        dataset = Path(spec["dataset_dir"])
        entry = next(e for e in _json(dataset / "dataset.json")["tasks"]
                     if e["task_id"] == manifest["task_id"])
        task_file = dataset / entry["path"]
        _plan_attempt(attempt, spec, entry, _json(task_file), task_file,
                      dataset / entry["prompt"], manifest["model"], manifest["replicate"])
        _event(attempt, "replanned_after_reset", reason=reason, retired=str(retired))
        done.append({"attempt_id": manifest["attempt_id"], "retired": str(retired)})
    return {"success": True, "reset": done}


def _rows(root: Path) -> list[dict]:
    rows = []
    for attempt in attempt_dirs(root):
        manifest = _json(attempt / "manifest.json")
        result = _json(attempt / "result.json") if (attempt / "result.json").exists() else None
        rows.append({"attempt": attempt, "manifest": manifest, "result": result,
                     "submitted": (attempt / "slurm" / "jobs.json").exists()})
    return rows


def status(experiment_dir: str) -> dict:
    """Count planned, submitted, sealed, passed and infra-failed attempts."""
    rows = _rows(Path(experiment_dir).resolve())
    sealed = [r for r in rows if r["result"]]
    return {"success": True, "attempts": len(rows),
            "submitted": sum(r["submitted"] for r in rows), "sealed": len(sealed),
            "passed": sum(bool(r["result"]["passed"]) for r in sealed),
            "infra": sorted(r["manifest"]["attempt_id"] for r in sealed
                            if r["result"]["failure_stage"] == "infra"),
            "failure_codes": _count(r["result"]["failure_code"] for r in sealed
                                    if r["result"]["failure_code"])}


def _count(values) -> dict:
    out = {}
    for value in values:
        out[value] = out.get(value, 0) + 1
    return dict(sorted(out.items()))


def collect(experiment_dir: str, out: str = "") -> dict:
    """Per model: pass^k over tasks, pass@1 with a Wilson 95% interval, failures, cost."""
    root = Path(experiment_dir).resolve()
    rows = [r for r in _rows(root) if r["result"]]
    infra = [r for r in rows if r["result"]["failure_stage"] == "infra"]
    counted = [r for r in rows if r["result"]["failure_stage"] != "infra"]
    models = {}
    for row in counted:
        model = row["manifest"]["model"]
        entry = models.setdefault(model, {"tasks": {}, "attempts": 0, "passed": 0,
                                          "failures": {}, "gpu_seconds": 0.0,
                                          "prompt_tokens": 0, "completion_tokens": 0,
                                          "reasoning_tokens": 0, "llm_calls": 0,
                                          "by_axis": {}})
        result = row["result"]
        task = row["manifest"]["task_id"]
        entry["tasks"].setdefault(task, []).append(bool(result["passed"]))
        entry["attempts"] += 1
        entry["passed"] += bool(result["passed"])
        axis = entry["by_axis"].setdefault(row["manifest"]["axis"], [0, 0])
        axis[0] += bool(result["passed"])
        axis[1] += 1
        if result["failure_code"]:
            entry["failures"][result["failure_code"]] = entry["failures"].get(
                result["failure_code"], 0) + 1
        entry["gpu_seconds"] += float(result["metrics"].get("gpu_seconds") or 0)
        usage = result["metrics"].get("token_usage") or {}
        entry["prompt_tokens"] += int(usage.get("prompt_tokens") or 0)
        entry["completion_tokens"] += int(usage.get("completion_tokens") or 0)
        entry["reasoning_tokens"] += int(usage.get("reasoning_tokens") or 0)
        entry["llm_calls"] += int(usage.get("calls") or 0)
    summary = {}
    for model, entry in sorted(models.items()):
        k = max((len(v) for v in entry["tasks"].values()), default=0)
        complete = {t: v for t, v in entry["tasks"].items() if len(v) == k}
        low, high = wilson(entry["passed"], entry["attempts"])
        summary[model] = {
            "replicates": k, "tasks": len(entry["tasks"]),
            "tasks_with_all_replicates": len(complete),
            "pass_k": sum(all(v) for v in complete.values()),
            "pass_k_tasks": sorted(t for t, v in complete.items() if all(v)),
            "attempts": entry["attempts"], "attempts_passed": entry["passed"],
            "pass_at_1": entry["passed"] / entry["attempts"] if entry["attempts"] else None,
            "pass_at_1_wilson95": [low, high],
            "failures": dict(sorted(entry["failures"].items())),
            "by_axis": {a: {"passed": v[0], "attempts": v[1]}
                        for a, v in sorted(entry["by_axis"].items())},
            "gpu_hours": entry["gpu_seconds"] / 3600.0,
            "prompt_tokens": entry["prompt_tokens"],
            "completion_tokens": entry["completion_tokens"],
            "reasoning_tokens": entry["reasoning_tokens"], "llm_calls": entry["llm_calls"],
        }
    report = {"success": True, "experiment": str(root), "collected": _now(),
              "sealed": len(rows), "counted": len(counted),
              "infra_excluded": sorted(r["manifest"]["attempt_id"] for r in infra),
              "models": summary}
    if out:
        _write_json(Path(out), report)
    return report


# ---- command line ------------------------------------------------------------------

COMMANDS = {"init": init, "dispatch": dispatch, "finalize": finalize, "reset": reset,
            "status": status, "collect": collect}


def main(argv=None) -> int:
    import inspect
    parser = argparse.ArgumentParser(prog="mddatabench.mdcrow_baseline.campaign",
                                     description=__doc__.split("\n")[0])
    sub = parser.add_subparsers(dest="command", required=True)
    for name, function in COMMANDS.items():
        p = sub.add_parser(name, help=(function.__doc__ or "").strip().split("\n")[0])
        for pname, parameter in inspect.signature(function).parameters.items():
            flag = "--" + pname.replace("_", "-")
            if parameter.default is inspect.Parameter.empty:
                p.add_argument(flag, required=True)
            elif isinstance(parameter.default, bool):
                p.add_argument(flag, action="store_true")
            elif isinstance(parameter.default, int):
                p.add_argument(flag, type=int, default=parameter.default)
            else:
                p.add_argument(flag, default=parameter.default)
    args = parser.parse_args(argv)
    function = COMMANDS[args.command]
    kwargs = {k: getattr(args, k) for k in inspect.signature(function).parameters}
    print(json.dumps(function(**kwargs), indent=2, default=str))
    return 0


if __name__ == "__main__":
    sys.exit(main())
