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
}
