"""The CLI surface must stay importable without the scientific stack."""

from __future__ import annotations

import json


def test_tools_are_registered():
    import mddatabench
    assert set(mddatabench.TOOLS) == {
        "list_benchmark_tasks",
        "fetch_benchmark_reference",
        "calibrate_benchmark_task",
        "score_benchmark_submission",
        "run_benchmark_negative_controls",
        "score_portable_submission",
        "init_experiment",
        "run_attempt_agent",
        "submit_attempt_scorer",
        "run_experiment",
        "finalize_attempt",
        "collect_experiment",
        "model_inventory",
        "audit_task_contract",
        "audit_task_cast",
    }


def test_list_benchmark_tasks_reports_the_dataset(tmp_path, capsys):
    from mddatabench import list_benchmark_tasks
    result = list_benchmark_tasks("benchmarks/mddatabench")
    assert result["success"] and result["total"] >= 2
    for task in result["tasks"]:
        assert task["checks"]["prep"] and task["checks"]["md"]
        assert task["accession"]


def test_dispatcher_lists_tools(capsys):
    from mddatabench.__main__ import main
    assert main(["--list"]) == 0
    payload = json.loads(capsys.readouterr().out)
    assert {t["name"] for t in payload["tools"]} == set(
        __import__("mddatabench").TOOLS)
