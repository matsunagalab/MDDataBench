"""Dataset v0.4: the audit's undecided components reach task.json and prompt.md, once."""

import csv
import json
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "scripts"))

import apply_nonpolymer_audit as apply_audit  # noqa: E402


def _dataset(tmp_path):
    src = REPO / "benchmarks" / "mddatabench"
    dataset = tmp_path / "dataset"
    (dataset / "tasks").mkdir(parents=True)
    for task in ("030_complex_1ffw", "062_metal_6w9c", "069_soluble_1aol"):
        (dataset / "tasks" / task).mkdir()
        for name in ("task.json", "prompt.md"):
            (dataset / "tasks" / task / name).write_text((src / "tasks" / task / name).read_text())
    meta = json.loads((src / "dataset.json").read_text())
    meta["dataset_id"] = "MDDataBench-v0.3"
    meta.pop("changelog", None)
    (dataset / "dataset.json").write_text(json.dumps(meta))
    # strip what v0.4 added so the fixture starts from the v0.3 state
    for task in ("062_metal_6w9c", "069_soluble_1aol"):
        path = dataset / "tasks" / task
        spec = json.loads((path / "task.json").read_text())
        spec["reference"]["selection"].pop("excluded_components", None)
        spec["reference"]["selection"].pop("kept_components", None)
        (path / "task.json").write_text(json.dumps(spec))
        prompt = (path / "prompt.md").read_text()
        (path / "prompt.md").write_text("\n".join(
            line for line in prompt.splitlines()
            if "not part of the reference" not in line and "Keep the one at residue" not in line) + "\n")
    audit = tmp_path / "audit.csv"
    with audit.open("w", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=["task", "unaddressed", "in_reference"])
        writer.writeheader()
        writer.writerow({"task": "030_complex_1ffw", "unaddressed": "", "in_reference": ""})
        writer.writerow({"task": "062_metal_6w9c", "unaddressed": "CL", "in_reference": "ZN"})
        writer.writerow({"task": "069_soluble_1aol", "unaddressed": "NAG ZN", "in_reference": ""})
    return dataset, audit


def test_the_audit_writes_exclusions_once_and_bumps_the_dataset_version(tmp_path):
    dataset, audit = _dataset(tmp_path)
    result = apply_audit.apply(dataset, audit)
    assert [c["task"] for c in result["changed"]] == ["062_metal_6w9c", "069_soluble_1aol"]
    assert result["dataset_id"] == "MDDataBench-v0.4"
    prompt_069 = (dataset / "tasks/069_soluble_1aol/prompt.md").read_text()
    assert "The deposit's **ZN** is not part of the reference. Simulate the protein without it." in prompt_069
    assert "**NAG**" not in prompt_069                      # the glycan sentence already covers the sugar
    assert prompt_069.index("**ZN** is not part") < prompt_069.index("Leave the prepared structure")
    spec_069 = json.loads((dataset / "tasks/069_soluble_1aol/task.json").read_text())
    assert spec_069["reference"]["selection"]["excluded_components"] == ["ZN"]
    prompt_062 = (dataset / "tasks/062_metal_6w9c/prompt.md").read_text()
    assert "Keep the one at residue 402, bound by Cys189 and Cys224" in prompt_062
    assert "The deposit's **CL** is not part of the reference." in prompt_062
    spec_062 = json.loads((dataset / "tasks/062_metal_6w9c/task.json").read_text())
    assert spec_062["reference"]["selection"]["kept_components"][0]["keep"] == "402"
    meta = json.loads((dataset / "dataset.json").read_text())
    assert meta["dataset_id"] == "MDDataBench-v0.4" and meta["changelog"]
    # a second run changes nothing
    again = apply_audit.apply(dataset, audit)
    assert again["changed"] == []
    assert (dataset / "tasks/069_soluble_1aol/prompt.md").read_text() == prompt_069


def test_a_later_dataset_is_never_downgraded(tmp_path):
    """v0.6 added the test split after this step; rerunning it must not reset the id."""
    dataset, audit = _dataset(tmp_path)
    apply_audit.apply(dataset, audit)
    meta = json.loads((dataset / "dataset.json").read_text())
    meta["dataset_id"] = "MDDataBench-v0.6"
    (dataset / "dataset.json").write_text(json.dumps(meta))
    lines = len(meta["changelog"])
    result = apply_audit.apply(dataset, audit)
    meta = json.loads((dataset / "dataset.json").read_text())
    assert result["dataset_id"] == "MDDataBench-v0.6"
    assert meta["dataset_id"] == "MDDataBench-v0.6" and len(meta["changelog"]) == lines
    assert result["changed"] == []


def _one_task(tmp_path, task_id, row):
    """A one-task dataset copied from the shipped one, and a one-row audit."""
    src = REPO / "benchmarks" / "mddatabench"
    dataset = tmp_path / "dataset"
    (dataset / "tasks" / task_id).mkdir(parents=True)
    for name in ("task.json", "prompt.md"):
        (dataset / "tasks" / task_id / name).write_text((src / "tasks" / task_id / name).read_text())
    (dataset / "dataset.json").write_text((src / "dataset.json").read_text())
    audit = tmp_path / "audit.csv"
    with audit.open("w", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=["task", "unaddressed", "in_reference"])
        writer.writeheader()
        writer.writerow(dict(row, task=task_id))
    return dataset, audit


def test_a_cation_kept_bound_is_never_excluded(tmp_path):
    """114's audit row predates v0.6.1 and lists K; the task keeps it as bound_ions."""
    dataset, audit = _one_task(tmp_path, "114_nucleic_1jrn", {"unaddressed": "K", "in_reference": ""})
    before = (dataset / "tasks/114_nucleic_1jrn/prompt.md").read_text()
    assert apply_audit.apply(dataset, audit)["changed"] == []
    assert (dataset / "tasks/114_nucleic_1jrn/prompt.md").read_text() == before
    assert "not part of the reference" not in before


def test_an_exclusion_sentence_that_names_a_sugar_too_counts_as_present(tmp_path):
    """A sugar off any glycosylation site is excluded with the rest ("NAG and PG4")."""
    task_id = "138_complex_5gy2"
    if not (REPO / "benchmarks" / "mddatabench" / "tasks" / task_id).is_dir():
        import pytest
        pytest.skip("test_v7 not built")
    dataset, audit = _one_task(tmp_path, task_id, {"unaddressed": "NAG PG4", "in_reference": ""})
    before = (dataset / "tasks" / task_id / "prompt.md").read_text()
    assert "The deposit's **NAG** and **PG4** are not part of the reference." in before
    assert apply_audit.apply(dataset, audit)["changed"] == []
    assert (dataset / "tasks" / task_id / "prompt.md").read_text() == before


def test_the_shipped_dataset_is_a_fixed_point():
    """Rerun over the shipped audit CSV, the step changes no task (dry run)."""
    dataset = REPO / "benchmarks" / "mddatabench"
    result = apply_audit.apply(dataset, dataset / "_audits" / "nonpolymer-20260914.csv",
                               dry_run=True)
    assert result["changed"] == []
    assert result["unchanged"] == len(list((dataset / "tasks").glob("*/task.json")))
