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


def _dag(root, stages=("prep", "topo", "min", "prod"), artifacts=True):
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
        if artifacts and stage == "min":
            (node / "artifacts" / "minimized_structure.pdb").write_text("END\n")
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
    assert reason is None and set(nodes) == {"prep", "topo", "min", "prod"}


# The minimised state is compared against, not merely required: a construct the
# reference ligated still carries the deposit's gap in the prepared structure, so
# the comparison has to be made on the first artifact in which the force field
# has been applied.

def test_a_job_with_no_minimised_state_is_unrunnable(tmp_path):
    _dag(tmp_path, stages=("prep", "topo", "prod"))
    nodes, reason = sc._resolve_stages(tmp_path)
    assert nodes is None and "min" in reason


def test_a_min_node_with_no_structure_is_unrunnable(tmp_path):
    _dag(tmp_path)
    node = next(p for p in (tmp_path / "nodes").iterdir() if p.name.startswith("min"))
    (node / "artifacts" / "minimized_structure.pdb").unlink()
    nodes, reason = sc._resolve_stages(tmp_path)
    assert nodes is None and "minimized_structure.pdb" in reason


# ---- chained production ---------------------------------------------------------

def _prod(root, name, parent, ns, **meta):
    node = root / "nodes" / name
    (node / "artifacts").mkdir(parents=True, exist_ok=True)
    (node / "node.json").write_text(json.dumps({
        "node_type": "prod", "status": "completed", "parent_node_ids": [parent],
        "metadata": {"simulation_time_ns": ns, "temperature_kelvin": 310.0, "pressure_bar": 1.0,
                     "timestep_fs": 4.0, "hmr": True, "system_signature": {"ensemble": "NPT"},
                     **meta}}))
    (node / "artifacts" / "trajectory.dcd").write_bytes(b"")
    (node / "artifacts" / "energy.dat").write_text(
        '#"Step","Temperature (K)","Density (g/mL)","Box Volume (nm^3)"\n'
        + "".join(f"{i},{309 + i},{1.0},{1000 + i}\n" for i in range(3)))
    return node


def test_chained_production_segments_are_graded_together(tmp_path):
    _dag(tmp_path, stages=("prep", "topo", "min", "eq"))
    for node in (tmp_path / "nodes").iterdir():
        if node.name.startswith("eq"):
            eq = node.name
    _prod(tmp_path, "prod_001", eq, 0.4)
    _prod(tmp_path, "prod_002", "prod_001", 0.4)
    head = _prod(tmp_path, "prod_003", "prod_002", 0.4)
    assert sc.find_node(tmp_path, "prod") == head
    segments = sc.production_segments(tmp_path, head)
    assert [n.name for n in segments] == ["prod_001", "prod_002", "prod_003"]
    summary = sc.production_summary(segments)
    assert summary["simulation_time_ns"] == pytest.approx(1.2)
    assert summary["consistent"] and summary["dropped"] == []
    log = sc.merge_energy_logs([n / "artifacts" / "energy.dat" for n in segments])
    assert len(log["Temperature (K)"]) == 9 and float(log["Box Volume (nm^3)"][-1]) == 1002.0
    # The prep and topo nodes are still found through the lineage of the head.
    assert sc.find_node(tmp_path, "topo").name.startswith("topo")


def test_a_restart_under_different_conditions_is_not_one_production(tmp_path):
    _dag(tmp_path, stages=("prep", "topo", "min", "eq"))
    eq = next(n.name for n in (tmp_path / "nodes").iterdir() if n.name.startswith("eq"))
    _prod(tmp_path, "prod_001", eq, 0.6, temperature_kelvin=300.0)
    head = _prod(tmp_path, "prod_002", "prod_001", 0.6)
    summary = sc.production_summary(sc.production_segments(tmp_path, head))
    assert summary["segments"] == ["prod_002"] and summary["dropped"] == ["prod_001"]
    assert summary["simulation_time_ns"] == pytest.approx(0.6) and not summary["consistent"]


def test_a_failed_or_trajectoryless_parent_ends_the_chain(tmp_path):
    _dag(tmp_path, stages=("prep", "topo", "min", "eq"))
    eq = next(n.name for n in (tmp_path / "nodes").iterdir() if n.name.startswith("eq"))
    first = _prod(tmp_path, "prod_001", eq, 0.5)
    (first / "artifacts" / "trajectory.dcd").unlink()
    head = _prod(tmp_path, "prod_002", "prod_001", 0.5)
    assert [n.name for n in sc.production_segments(tmp_path, head)] == ["prod_002"]
    single = _prod(tmp_path, "prod_009", eq, 2.0)
    assert [n.name for n in sc.production_segments(tmp_path, single)] == ["prod_009"]
