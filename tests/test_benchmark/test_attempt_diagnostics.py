import json

import pytest

from mddatabench.attempt_diagnostics import diagnose, gpu_totals
from mddatabench import experiments as ex


def node(root, nid, status, code=None):
    path = root / "nodes" / nid / "node.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"node_id": nid, "node_type": nid.split("_")[0],
                               "status": status, "metadata": {"failure_code": code,
                               "errors": ["declared 1.0, actual 2.0"] if code else []}}))


BAD_SCORE = {"passed": 0, "total": 1, "checks": [{"check_id": "monomer_count_matches_reference",
             "category": "prep", "weight": 1, "passed": False}]}


def test_090_failure_is_execution_not_first_scoring_check(tmp_path):
    node(tmp_path, "eq_001", "completed")
    node(tmp_path, "prod_001", "failed", "node_execution_context_invalid")
    result = diagnose(tmp_path, BAD_SCORE, False)
    assert result["failure_stage"] == "execution"
    assert result["failure_code"] == "node_execution_context_invalid"
    assert result["scoring_failures"] == BAD_SCORE["checks"]
    assert result["execution_diagnostics"]["evidence"][0]["source"].endswith("prod_001/node.json")


@pytest.mark.parametrize("passed", [True, False])
def test_completed_branch_does_not_inherit_old_failure(tmp_path, passed):
    node(tmp_path, "prod_001", "failed", "old_failure")
    node(tmp_path, "prod_002", "completed")
    result = diagnose(tmp_path, BAD_SCORE if not passed else {}, passed)
    assert result["failure_stage"] == (None if passed else "evaluation")
    assert result["execution_diagnostics"]["status"] == "completed"
    assert result["execution_diagnostics"]["evidence"]


def test_multiple_failures_and_pending_production_are_not_false_precise_causes(tmp_path):
    node(tmp_path, "prod_001", "pending")
    assert diagnose(tmp_path, BAD_SCORE, False)["failure_code"] == "production_incomplete"
    node(tmp_path, "min_001", "failed", "first")
    node(tmp_path, "min_002", "failed", "second")
    result = diagnose(tmp_path, BAD_SCORE, False)
    assert result["failure_code"] == "multiple_execution_failures"
    assert len(result["execution_diagnostics"]["evidence"]) == 2


def test_no_dag_uses_evidence_or_unknown_not_score_order(tmp_path):
    assert diagnose(tmp_path, BAD_SCORE, False)["failure_stage"] == "unknown"
    result = diagnose(tmp_path, BAD_SCORE, False, [{"job_id": "1", "state": "TIMEOUT"}])
    assert result["failure_code"] == "scheduler_failure_observed"


@pytest.mark.parametrize("values,total,known,observed", [
    ([None, None], None, None, 0), ([0, None], None, 0, 1),
    ([10, None], None, 10, 1), ([0, 0], 0, 0, 2), ([10, 20], 30, 30, 2),
    ([float("nan"), -1], None, None, 0), ([], None, None, 0)])
def test_gpu_missingness(values, total, known, observed):
    result = gpu_totals(values)
    assert result["gpu_seconds"] == total
    assert result["gpu_seconds_known"] == known
    assert result["gpu_observed_count"] == observed
    assert result["gpu_expected_count"] == len(values)


def test_missing_allocation_and_missing_gpu_field_do_not_produce_complete_total(tmp_path):
    path = tmp_path / "sacct.txt"
    path.write_text("1|COMPLETED||||10|gres/gpu=2\n2|COMPLETED||||20|\n")
    result = ex._slurm_metrics(path, ["1", "2", "3"])
    assert result["gpu_seconds"] is None
    assert result["gpu_seconds_known"] == 20
    assert result["gpu_expected_count"] == 3
    assert result["gpu_observed_count"] == 1


def experiment(tmp_path, gpu_values):
    root = tmp_path / "experiment"
    for i, gpu in enumerate(gpu_values):
        attempt = root / "attempts" / str(i) / "r1"
        attempt.mkdir(parents=True)
        manifest = {"attempt_id": str(i), "experiment_id": "test", "task_id": str(i),
                    "condition": "cli_skill_sif", "harness": "pi", "model": "test",
                    "replicate": 1, "axis": "soluble", "paths": {"workspace": str(attempt / "workspace")}}
        (attempt / "manifest.json").write_text(json.dumps(manifest))
        (attempt / "score.json").write_text(json.dumps(BAD_SCORE))
        if gpu is not None:
            (attempt / "md_sacct.txt").write_text(f"1|COMPLETED||||{gpu}|gres/gpu=1\n")
        node(attempt / "workspace/study/jobs/main", "prod_001", "failed", "node_execution_context_invalid")
        (attempt / "result.json").write_text(json.dumps({**manifest, "passed": False,
            "attempt_score": 0, "check_score": 0.0, "checks_passed": 0, "checks_total": 1,
            "failure_stage": "prep", "failure_code": "monomer_count_matches_reference",
            "metrics": {"gpu_seconds": gpu}}))
    return root


@pytest.mark.parametrize("values,total,known", [([None,None], None,None), ([10,None],None,10),
                                               ([0,0],0,0), ([10,20],30,30)])
def test_refresh_is_read_only_and_summary_keeps_missingness(tmp_path, monkeypatch, values, total, known):
    root = experiment(tmp_path, values)
    before = {str(p): p.read_bytes() for p in root.rglob("*") if p.is_file()}
    monkeypatch.setattr(ex, "_reconcile_scorer", lambda *_: pytest.fail("refresh must not reconcile"))
    out = tmp_path / "corrected"
    result = ex.collect_experiment(str(root), str(out), refresh_diagnostics=True)
    overall = next(r for r in result["summary"] if r["axis"] == "all")
    assert overall["total_gpu_seconds"] == total
    assert overall["known_gpu_seconds"] == known
    assert overall["gpu_expected_attempts"] == 2
    rows = [json.loads(line) for line in (out / "attempts.jsonl").read_text().splitlines()]
    assert all(r["failure_stage"] == "execution" and r["attempt_score"] == 0 for r in rows)
    assert {str(p): p.read_bytes() for p in root.rglob("*") if p.is_file()} == before
    assert (out / "scoring_failures.csv").is_file()
    for bad_out in (None, str(root / "summary"), str(out), str(root / "attempts/new")):
        with pytest.raises(ValueError):
            ex.collect_experiment(str(root), bad_out, refresh_diagnostics=True)


def test_sealed_diagnostics_and_metrics_survive_raw_cleanup(tmp_path):
    root = experiment(tmp_path, [10])
    attempt = root / "attempts/0/r1"
    (attempt / "result.json").unlink()  # replace this test's legacy fixture by normal sealing
    sealed = ex.finalize_attempt(str(attempt), str(attempt / "score.json"))
    assert sealed["failure_code"] == "node_execution_context_invalid"
    (attempt / "workspace/study/jobs/main/nodes/prod_001/node.json").unlink()
    (attempt / "md_sacct.txt").unlink()
    out = tmp_path / "corrected"
    ex.collect_experiment(str(root), str(out), refresh_diagnostics=True)
    row = json.loads((out / "attempts.jsonl").read_text())
    assert row["execution_diagnostics"] == sealed["execution_diagnostics"]
    assert row["metrics"]["gpu_seconds"] == 10


def test_legacy_partial_total_not_certified_without_refresh(tmp_path):
    root = experiment(tmp_path, [10])
    result = ex.collect_experiment(str(root))
    overall = next(r for r in result["summary"] if r["axis"] == "all")
    assert overall["total_gpu_seconds"] is None
    assert overall["known_gpu_seconds"] == 10


def test_zero_cpu_and_typed_gpu_allocations(tmp_path):
    path = tmp_path / "sacct.txt"
    path.write_text("1|COMPLETED||||10|cpu=1,mem=100M\n2|COMPLETED||||20|gres/gpu:a100=2\n")
    result = ex._slurm_metrics(path)
    assert result["gpu_seconds"] == 40
    assert result["gpu_coverage"] == 1
    assert result["md_jobs"][0]["gpu_seconds"] == 0
