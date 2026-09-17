"""Dataset v0.5: the standard-protonation sentence leaves every prompt, once."""

import json
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "scripts"))

import apply_dataset_v05 as v05  # noqa: E402

V04_FREE = (
    "# Task 001_x\n\nSimulate X, PDB entry **1ABC**, chain **A** residues **1–9**, in explicit solvent.\n\n"
    "- **TIP3P** water, neutralised\n- **300 K**, **NPT** at **1 bar**\n"
    "- at least **1 ns** of production MD\n\n"
    "The deposit's **ZN** is not part of the reference. Simulate the protein without it.\n\n"
    "Simulate every ionisable side chain in its standard state at pH 7: charged aspartate, "
    "glutamate, lysine and arginine, and neutral histidine and cysteine.\n\n"
    "Leave the prepared structure, the topology, the minimised state and the production\n"
    "trajectory as artifacts. The evaluator recomputes everything it needs from them.\n")
V04_NAMED = V04_FREE.replace("# Task 001_x", "# Task 100_y").replace(
    "The deposit's **ZN**",
    "Residue 3 of chain A is a protonated histidine.\n\nResidue 93 of chain A is a protonated "
    "histidine.\n\nThe deposit's **ZN**").replace("Simulate every ionisable", "Simulate every other ionisable")
STATED = [{"chain": "A", "residue": "3", "name": "HIP", "meaning": "protonated histidine",
           "reference_residue": "3"},
          {"chain": "A", "residue": "93", "name": "HIP", "meaning": "protonated histidine",
           "reference_residue": "93"}]


def _dataset(tmp_path):
    dataset = tmp_path / "dataset"
    for task_id, prompt, stated in (("001_x", V04_FREE, []), ("100_y", V04_NAMED, STATED)):
        (dataset / "tasks" / task_id).mkdir(parents=True)
        (dataset / "tasks" / task_id / "prompt.md").write_text(prompt)
        (dataset / "tasks" / task_id / "task.json").write_text(json.dumps(
            {"task_id": task_id, "reference": {"selection": {"stated_protonation": stated}}}))
    (dataset / "dataset.json").write_text(json.dumps({"dataset_id": "MDDataBench-v0.4"}))
    return dataset


def test_the_sentence_goes_and_the_bullet_or_the_named_residues_come(tmp_path):
    dataset = _dataset(tmp_path)
    result = v05.apply(dataset)
    assert result["changed"] == ["001_x", "100_y"] and result["dataset_id"] == "MDDataBench-v0.5"
    free = (dataset / "tasks/001_x/prompt.md").read_text()
    assert "standard state" not in free
    assert "- at least **1 ns** of production MD\n- neutral pH; ionisation states of the side chains are your choice\n\n" in free
    assert "The deposit's **ZN** is not part of the reference." in free
    named = (dataset / "tasks/100_y/prompt.md").read_text()
    assert "standard state" not in named and "is a protonated histidine." not in named
    assert ("Residues 3 and 93 of chain A are doubly protonated histidines (HIP); keep them that way.\n\n"
            "Ionisation states of the other side chains are your choice.\n\n"
            "The deposit's **ZN**") in named
    assert "neutral pH; ionisation states" not in named
    meta = json.loads((dataset / "dataset.json").read_text())
    assert meta["dataset_id"] == "MDDataBench-v0.5" and meta["changelog"]


def test_it_is_idempotent(tmp_path):
    dataset = _dataset(tmp_path)
    v05.apply(dataset)
    before = {p: p.read_text() for p in dataset.rglob("*")if p.is_file()}
    result = v05.apply(dataset)
    assert result["changed"] == [] and result["unchanged"] == 2
    assert {p: p.read_text() for p in dataset.rglob("*") if p.is_file()} == before


def test_the_shipped_dataset_is_already_v05():
    dataset = REPO / "benchmarks" / "mddatabench"
    result = v05.apply(dataset, dry_run=True)
    assert result["changed"] == [] and result["unchanged"] == 98
    for prompt in (dataset / "tasks").glob("*/prompt.md"):
        text = prompt.read_text()
        assert "standard state at pH 7" not in text
        assert "your choice" in text
