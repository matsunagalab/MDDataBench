"""A submission whose pipeline errored out scores zero, rather than not scoring.

Until 2026-08-23 a failed prep stage raised ``SystemExit`` out of the scorer:
``find_node`` refuses when no completed node of a type exists.  The run then had
no entry in the results at all, which reads as "not attempted" rather than
"attempted and failed", and a batch of 100 tasks would lose it silently.

Both axes go to zero together on purpose.  A prep stage that failed leaves no
structure to compare against the reference and no system that was simulated, so
an md score computed anyway would be describing a different molecule.
"""

from __future__ import annotations

import json

import pytest

from mddatabench import scoring as sc


TASK = {
    "task_id": "TEST",
    "scoring": {"deterministic_checks": [
        {"check_id": "a", "category": "prep", "weight": 1.0},
        {"check_id": "b", "category": "prep", "weight": 1.0},
        {"check_id": "c", "category": "md", "weight": 1.0},
        {"check_id": "d", "category": "precondition", "weight": 0.0},
        {"check_id": "e", "category": "diagnostic", "weight": 0.0},
    ]},
}


def test_an_unrunnable_submission_scores_zero_on_both_axes():
    report = sc._unrunnable(TASK, "the prep node failed")
    assert report["scores"]["prep"] == 0.0
    assert report["scores"]["md"] == 0.0
    assert report["passed"] == 0
    assert report["total"] == 3          # the two zero-weight checks are not graded
    assert report["unrunnable"] == "the prep node failed"


def test_the_reason_reaches_every_check_so_a_report_is_self_explaining():
    report = sc._unrunnable(TASK, "the prod node produced no trajectory")
    assert {c["detail"] for c in report["checks"]} == {
        "the prod node produced no trajectory"}
    assert all(c["passed"] is False for c in report["checks"])


def test_zero_weight_categories_keep_scoring_none_not_zero():
    """A precondition measures the scorer, not the agent, so it must not be
    turned into a zero the agent is charged for."""
    report = sc._unrunnable(TASK, "x")
    assert report["scores"]["precondition"] is None
    assert report["scores"]["diagnostic"] is None


def test_a_job_with_no_nodes_directory_is_unrunnable_not_an_exception(tmp_path):
    nodes, reason = sc._resolve_stages(tmp_path)
    assert nodes is None and "nodes" in reason


def test_a_job_with_no_completed_prep_node_is_unrunnable_not_an_exception(tmp_path):
    (tmp_path / "nodes").mkdir()
    nodes, reason = sc._resolve_stages(tmp_path)
    assert nodes is None
    assert "prep" in reason


def test_scoring_such_a_job_returns_a_report_rather_than_raising(tmp_path):
    report = sc.score(tmp_path, tmp_path, TASK)
    assert report["scores"]["prep"] == 0.0 and report["scores"]["md"] == 0.0
    assert report["unrunnable"]


def _dag(root, stages=("prep", "topo", "prod"), artifacts=True):
    """The smallest node layout find_node accepts."""
    previous = None
    (root / "nodes").mkdir(exist_ok=True)
    for i, stage in enumerate(stages):
        node = root / "nodes" / f"{stage}_{i:03d}"
        (node / "artifacts").mkdir(parents=True)
        (node / "node.json").write_text(json.dumps({
            "node_type": stage, "status": "completed",
            "parent_node_ids": [previous] if previous else []}))
        previous = node.name
        if artifacts and stage == "topo":
            for name in ("system.topology.pdb", "system.system.xml",
                         "amber_metadata.json"):
                (node / "artifacts" / name).write_text("{}")
        if artifacts and stage == "prod":
            (node / "artifacts" / "run.dcd").write_bytes(b"")
    return root


@pytest.mark.parametrize("missing, expected", [
    ("system.topology.pdb", "system.topology.pdb"),
    ("system.system.xml", "system.system.xml"),
    ("amber_metadata.json", "amber_metadata.json"),
])
def test_a_topo_node_missing_an_artifact_is_unrunnable(tmp_path, missing, expected):
    _dag(tmp_path)
    node = next(p for p in (tmp_path / "nodes").iterdir() if p.name.startswith("topo"))
    (node / "artifacts" / missing).unlink()
    nodes, reason = sc._resolve_stages(tmp_path)
    assert nodes is None and expected in reason


def test_a_prod_node_with_no_trajectory_is_unrunnable(tmp_path):
    _dag(tmp_path)
    node = next(p for p in (tmp_path / "nodes").iterdir() if p.name.startswith("prod"))
    (node / "artifacts" / "run.dcd").unlink()
    nodes, reason = sc._resolve_stages(tmp_path)
    assert nodes is None and "trajectory" in reason


def test_a_complete_dag_resolves(tmp_path):
    _dag(tmp_path)
    nodes, reason = sc._resolve_stages(tmp_path)
    assert reason is None and set(nodes) == {"prep", "topo", "prod"}
