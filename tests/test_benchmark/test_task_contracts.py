"""Contract-level tests: no OpenMM, no fetched bundle, no MD."""

from __future__ import annotations

import json
import re
from pathlib import Path

import pytest

DATASET = Path(__file__).resolve().parents[2] / "benchmarks" / "mddatabench"
TASKS = sorted(DATASET.glob("tasks/*/task.json"))
CC = re.compile(r"CC BY|CC0|Creative Commons", re.I)


def load(path: Path) -> dict:
    return json.loads(path.read_text())


def test_dataset_lists_every_task_directory():
    listed = {t["task_id"] for t in load(DATASET / "dataset.json")["tasks"]}
    assert listed == {load(p)["task_id"] for p in TASKS}


@pytest.mark.parametrize("path", TASKS, ids=lambda p: p.parent.name)
def test_reference_is_cc_licensed_and_pinned(path):
    reference = load(path)["reference"]
    assert CC.search(reference["license"]), "only CC BY / CC0 projects are eligible"
    assert reference["accession"] and reference["retrieved"] and reference["pdb_ids"]
    assert set(reference["bundle"]["sha256"]) == {
        "reference.pdb", "reference_frames.f32", "pca_atom_indices.json"}
    for digest in reference["bundle"]["sha256"].values():
        assert re.fullmatch(r"[0-9a-f]{64}", digest)


@pytest.mark.parametrize("path", TASKS, ids=lambda p: p.parent.name)
def test_every_check_is_categorised_and_versioned(path):
    checks = load(path)["scoring"]["deterministic_checks"]
    assert checks
    for check in checks:
        assert check["category"] in ("prep", "md", "precondition"), check["check_id"]
        assert check["check_type"].endswith("@1"), (
            f"{check['check_id']}: check types are versioned so a scorer fix "
            "does not silently rescore old submissions")
    assert any(c["category"] == "prep" for c in checks)
    assert any(c["category"] == "md" for c in checks)
    for check in checks:
        if check["category"] == "precondition":
            assert check["weight"] == 0.0, (
                f"{check['check_id']}: a precondition measures the scorer, not the "
                "agent, so it is reported and never scored")


@pytest.mark.parametrize("path", TASKS, ids=lambda p: p.parent.name)
def test_md_side_keeps_both_gates(path):
    """The structure-only test and the clock caught different baselines."""
    ids = {c["check_id"] for c in load(path)["scoring"]["deterministic_checks"]}
    assert "subspace_beyond_structure_only_model" in ids
    assert "elapsed_simulated_time_is_physical" in ids


@pytest.mark.parametrize("path", TASKS, ids=lambda p: p.parent.name)
def test_prompt_does_not_leak_the_reference(path):
    """The agent must not be able to look the reference up from the prompt."""
    task = load(path)
    prompt = (path.parent / "prompt.md").read_text()
    reference = task["reference"]
    forbidden = [reference["accession"], "MDDB", "mddbr", "MoDEL"]
    if reference.get("citation"):
        forbidden.append(reference["citation"].split()[-1])
    for token in forbidden:
        assert token.lower() not in prompt.lower(), f"prompt leaks {token!r}"
    assert any(pdb.lower() in prompt.lower() for pdb in reference["pdb_ids"])


@pytest.mark.parametrize("path", TASKS, ids=lambda p: p.parent.name)
def test_prompt_states_the_conditions_that_are_scored(path):
    """Conditions checked against the reference have to be stated; nothing else."""
    task = load(path)
    prompt = (path.parent / "prompt.md").read_text().lower()
    conditions = task["reference"]["reference_conditions"]
    assert conditions["WAT"].lower() in prompt
    assert str(int(conditions["TEMP"])) in prompt
    assert conditions["ENSEMBLE"].lower() in prompt
    assert "rmsip" not in prompt, "the evaluator does the analysis, not the agent"
