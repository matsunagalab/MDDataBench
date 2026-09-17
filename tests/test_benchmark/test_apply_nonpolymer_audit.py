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
