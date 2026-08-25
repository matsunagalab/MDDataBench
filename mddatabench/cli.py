"""Tool functions exposed through the ``mddatabench`` command line.

Each function returns a JSON-serialisable dict; the dispatcher in
``__main__`` derives its flags from the signature and prints the result.
"""

from __future__ import annotations

import json
from pathlib import Path

from mddatabench._common import __version__


def list_benchmark_tasks(dataset_dir: str = "benchmarks/mddatabench") -> dict:
    """List the tasks in a dataset directory with their reference accessions."""
    tasks = []
    for path in sorted(Path(dataset_dir).glob("tasks/*/task.json")):
        task = json.loads(path.read_text())
        checks = task["scoring"]["deterministic_checks"]
        tasks.append({
            "task_id": task["task_id"],
            "accession": task["reference"]["accession"],
            "pdb_ids": task["reference"]["pdb_ids"],
            "license": task["reference"]["license"],
            "checks": {"prep": sum(1 for c in checks if c.get("category") == "prep"),
                       "md": sum(1 for c in checks if c.get("category") == "md")},
            "task_file": str(path),
            "prompt_file": str(path.parent / "prompt.md"),
        })
    return {"success": True, "version": __version__, "total": len(tasks), "tasks": tasks}


def fetch_benchmark_reference(accession: str, out: str, n_frames: int = 0,
                              frames: str = None, node: str = "mmb",
                              replica: int = None) -> dict:
    """Download one MDDB reference bundle and record its provenance.

    ``node`` names the MDDB node (accessions are node-local; see
    ``mddatabench.reference.NODES``).  ``replica`` selects one MD of a
    multi-replica project.
    """
    from mddatabench.reference import fetch_reference
    provenance = fetch_reference(accession, out, n_frames=n_frames, frames=frames,
                                 node=node, replica=replica)
    return {"success": True, "out": out, **{k: provenance[k] for k in
            ("node", "accession", "md", "replica", "replica_count", "topology_file",
             "license", "n_frames", "frame_bytes", "sha256")}}


def score_benchmark_submission(job_dir: str, bundle: str, task_file: str,
                               out: str = None) -> dict:
    """Score one submission against its task contract."""
    from mddatabench.scoring import score
    report = score(Path(job_dir), Path(bundle), json.loads(Path(task_file).read_text()))
    if out:
        Path(out).write_text(json.dumps(report, indent=2))
    return {"success": True, **report}


def score_portable_submission(submission_dir: str, bundle: str, task_file: str,
                              out: str = None) -> dict:
    """Score a fixed portable layout produced without the MDClaw CLI."""
    from mddatabench.portable import score_portable
    report = score_portable(Path(submission_dir), Path(bundle),
                            json.loads(Path(task_file).read_text()))
    if out:
        Path(out).write_text(json.dumps(report, indent=2))
    return {"success": True, **report}


def init_experiment(experiment_dir: str, spec_file: str,
                    dataset_dir: str = "benchmarks/mddatabench") -> dict:
    """Create manifests and isolated workspaces for a multi-attempt campaign."""
    from mddatabench.experiments import init_experiment as run
    return run(experiment_dir, spec_file, dataset_dir)


def run_attempt_agent(attempt_dir: str, timeout_seconds: int = 0,
                      dry_run: bool = False) -> dict:
    """Run one configured pi/Claude Code/Codex attempt."""
    from mddatabench.experiments import run_attempt_agent as run
    return run(attempt_dir, timeout_seconds, dry_run)


def submit_attempt_scorer(attempt_dir: str, bundle_root: str, sif: str,
                          partition: str = "gpu", time_limit: str = "00:15:00",
                          memory: str = "32G", cpus_per_task: int = 4,
                          md_job_id: str = None) -> dict:
    """Submit an afterany scorer/collector for an attempt's final MD job."""
    from mddatabench.experiments import submit_attempt_scorer as run
    return run(attempt_dir, bundle_root, sif, partition, time_limit, memory,
               cpus_per_task, md_job_id)


def run_experiment(experiment_dir: str, bundle_root: str, scorer_sif: str,
                   max_agents: int = 1, timeout_seconds: int = 0,
                   limit: int = 0) -> dict:
    """Run pending agents and submit afterany scorer jobs for a campaign."""
    from mddatabench.experiments import run_experiment as run
    return run(experiment_dir, bundle_root, scorer_sif, max_agents,
               timeout_seconds, limit)


def finalize_attempt(attempt_dir: str, score_file: str = None,
                     failure_stage: str = None, failure_code: str = None,
                     failure_detail: str = None) -> dict:
    """Seal an attempt as strict binary pass or zero."""
    from mddatabench.experiments import finalize_attempt as run
    return run(attempt_dir, score_file, failure_stage, failure_code, failure_detail)


def audit_task_contract(task_dir: str, bundle: str, deposit_cache: str = None) -> dict:
    """Report reference or deposit components one task's prompt never names."""
    from mddatabench.contract_audit import audit_task_contract as run
    return run(task_dir, bundle, deposit_cache)


def audit_task_cast(dataset_dir: str, bundle_root: str,
                    deposit_cache: str = None) -> dict:
    """Run the contract audit over every task in a dataset directory."""
    from mddatabench.contract_audit import audit_task_cast as run
    return run(dataset_dir, bundle_root, deposit_cache)


def collect_experiment(experiment_dir: str, out_dir: str = None) -> dict:
    """Build paper-ready summary and failure tables from attempt results."""
    from mddatabench.experiments import collect_experiment as run
    return run(experiment_dir, out_dir)


def model_inventory(harness: str = "pi", out: str = None) -> dict:
    """Snapshot available model identifiers without copying credentials."""
    from mddatabench.experiments import model_inventory as run
    return run(harness, out)


def run_benchmark_negative_controls(job_dir: str, bundle: str, task_file: str) -> dict:
    """Run the adversarial baselines that must fail against the md-side checks."""
    from mddatabench.controls import run_negative_controls
    report = run_negative_controls(job_dir, bundle, task_file)
    return {"success": report["all_correct"], **report}


def calibrate_benchmark_task(accession: str, bundle: str, node: str = "mmb",
                             window_ns: float = None, slack_window_sd: float = 2.0,
                             target_windows: int = 100, out: str = None) -> dict:
    """Measure the md bands for one project from its own windows.

    Windows are pooled across every replica the project has, because a band
    measured inside one trajectory is narrower than the spread between
    independent runs -- and a submission is an independent run.  Where there are
    at least two replicas the result also carries a held-out false-rejection
    rate: calibrate without one replica, score every window of it.
    """
    from mddatabench.calibration import calibrate
    block = calibrate(accession, bundle, node=node, window_ns=window_ns,
                      slack_window_sd=slack_window_sd, target_windows=target_windows)
    if out:
        Path(out).write_text(json.dumps(block, indent=2))
    return {"success": True, **block}


TOOLS = {
    "list_benchmark_tasks": list_benchmark_tasks,
    "fetch_benchmark_reference": fetch_benchmark_reference,
    "calibrate_benchmark_task": calibrate_benchmark_task,
    "score_benchmark_submission": score_benchmark_submission,
    "run_benchmark_negative_controls": run_benchmark_negative_controls,
    "score_portable_submission": score_portable_submission,
    "init_experiment": init_experiment,
    "run_attempt_agent": run_attempt_agent,
    "submit_attempt_scorer": submit_attempt_scorer,
    "run_experiment": run_experiment,
    "finalize_attempt": finalize_attempt,
    "collect_experiment": collect_experiment,
    "model_inventory": model_inventory,
    "audit_task_contract": audit_task_contract,
    "audit_task_cast": audit_task_cast,
}
