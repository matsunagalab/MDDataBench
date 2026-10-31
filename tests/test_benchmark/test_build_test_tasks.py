"""The test-split builder reproduces what the cast carries beside ``calibrate``.

``scripts/build_test_tasks.py`` adds the per-check headroom, the held-out slack
requirement and the radius-of-gyration demotion to a fresh calibration. None of
that code was committed when the cast was built, so it is checked here against
the cast's own numbers: given a cast task's windows, it must give back that
task's ``per_check`` and scoring block exactly.
"""

import json
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "scripts"))

bt = pytest.importorskip("build_test_tasks")
TASKS = REPO / "benchmarks" / "mddatabench" / "tasks"


def _stripped(task_id):
    task = json.loads((TASKS / task_id / "task.json").read_text())
    block = dict(task["reference"]["md_calibration"])
    for key in ("slack_rationale", "per_check", "adversarial_headroom_note"):
        block.pop(key)
    block["slack_window_sd"] = 4.0
    return task, block


def _cast_ids():
    return sorted(p.parent.name for p in TASKS.glob("*/task.json")
                  if json.loads(p.read_text())["split"] != "test")


@pytest.mark.parametrize("task_id", _cast_ids())
def test_per_check_is_reproduced_from_the_windows(task_id):
    task, block = _stripped(task_id)
    finished = bt.finish_calibration(block)
    expected = task["reference"]["md_calibration"]
    for key, row in expected["per_check"].items():
        mine = finished["per_check"][key]
        assert mine["adversarial_headroom_window_sd"] == row["adversarial_headroom_window_sd"]
        assert mine["scored"] == row["scored"]
        assert mine == row
    assert finished["slack_window_sd"] == expected["slack_window_sd"]
    assert finished["slack_rationale"] == expected["slack_rationale"]


@pytest.mark.parametrize("task_id", ["031_nanobody_1kxv", "078_soluble_1dpt",
                                     "097_soluble_1dfw", "008_membrane_6i53"])
def test_the_scoring_block_follows_the_cast(task_id):
    """Shared block, with only the radius-of-gyration demotion carried (078, 097)."""
    task, block = _stripped(task_id)
    _, _, sample = bt.cast_texts()
    assert bt.scoring_block(sample, bt.finish_calibration(block)) == task["scoring"]
