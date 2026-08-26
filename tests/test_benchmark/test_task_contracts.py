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
    # The licence string MDDB returns, recorded verbatim. Most are CC BY 4.0.
    # The DynaRepo node returns Apache 2.0 for its own collection and nothing at
    # all for Dynabench, while its paper states CC BY-NC 4.0; that discrepancy is
    # the reason the invariant is "openly licensed and recorded" rather than
    # "CC BY or CC0", and it is recorded per task rather than papered over.
    licence = reference["license"]
    if licence is None:
        # 14 of the hundred: 12 from DynaRepo and 2 from Cineca. MDDB returns
        # nothing for them, so nothing here shows they are openly licensed. The
        # absence is recorded rather than assumed away, which is the only honest
        # option while the reference is fetched and never redistributed.
        assert reference.get("license_note"), (
            "a missing licence has to say so in the contract, not be a null")
    else:
        assert CC.search(licence) or "Apache" in licence, licence
    assert reference["accession"] and reference["retrieved"] and reference["pdb_ids"]
    # The topology's format is whichever the node deposited: Amber prmtop on
    # mmb, cin and rpbs, GROMACS tpr on bsc, oxf and inr, CHARMM psf on part of
    # inr. The rest of the bundle is fixed.
    files = set(reference["bundle"]["sha256"])
    assert {"reference.pdb", "pca_atom_indices.json",
            "reference_fluctuation.json"} <= files
    assert any(name.startswith("reference.") and name.split(".")[-1] in
               ("prmtop", "parm7", "tpr", "psf", "top") for name in files), files
    for digest in reference["bundle"]["sha256"].values():
        assert re.fullmatch(r"[0-9a-f]{64}", digest)


@pytest.mark.parametrize("path", TASKS, ids=lambda p: p.parent.name)
def test_every_check_is_categorised_and_versioned(path):
    checks = load(path)["scoring"]["deterministic_checks"]
    assert checks
    for check in checks:
        assert check["category"] in ("prep", "md", "precondition", "diagnostic"), \
            check["check_id"]
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
        if check["category"] == "diagnostic":
            assert check["weight"] == 0.0, (
                f"{check['check_id']}: a diagnostic is recorded until its threshold has "
                "been measured, and this suite does not score uncalibrated thresholds")


@pytest.mark.parametrize("path", TASKS, ids=lambda p: p.parent.name)
def test_md_side_keeps_the_gates_that_catch_different_things(path):
    """No one of these catches what the others do.

    Measured 2026-08-22 against the negative controls: shuffled frames keep the
    right magnitude and lose the ranks, an over-restrained run keeps the ranks
    (rho 0.872 at a tenth of the motion) and loses the magnitude, a threefold
    expansion keeps the ranks too, and the clock is the only reference-free
    evidence that time passed at all.
    """
    checks = load(path)["scoring"]["deterministic_checks"]
    ids = {c["check_id"] for c in checks}
    for required in ("elapsed_simulated_time_is_physical",
                     "fluctuation_profile_matches_reference",
                     "fluctuation_magnitude_is_physical",
                     "radius_of_gyration_matches_reference",
                     "measured_temperature_matches_reference",
                     "solvent_box_is_physical"):
        assert required in ids, required
    assert "subspace_beyond_structure_only_model" not in ids, (
        "the structure-only test decided nothing: an elastic-network ensemble "
        "scored RMSIP 0.749 against the real run's 0.704")


@pytest.mark.parametrize("path", TASKS, ids=lambda p: p.parent.name)
def test_window_bands_are_measured_and_recorded(path):
    """A band is a measurement, and it travels with the numbers behind it."""
    calibration = load(path)["reference"]["md_calibration"]
    # Thirty, not a hundred: min-to-max over n windows is a tolerance interval
    # whose expected coverage is (n-1)/(n+1), so fewer windows give a tighter
    # band -- and the slack that compensates was measured at thirty by
    # leave-one-replica-out, not assumed. A hundred windows per task costs half
    # an hour of downloads each.
    assert calibration["windows"] >= 30, "a range needs windows to be a range"
    for name in ("rank_correlation", "total_fluctuation_angstrom",
                 "radius_of_gyration_angstrom"):
        low, high = calibration[name]
        assert low < high, name
    assert calibration["estimator"] and calibration["window_fetch"], (
        "the recipe that produced the band belongs with it")


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
    from mddatabench._task_builder import WATERS
    water = WATERS.get(str(conditions["WAT"]).upper(), conditions["WAT"])
    assert water.lower() in prompt
    assert str(int(conditions["TEMP"])) in prompt
    assert conditions["ENSEMBLE"].lower() in prompt
    assert "rmsip" not in prompt, "the evaluator does the analysis, not the agent"

@pytest.mark.parametrize("path", TASKS, ids=lambda p: p.parent.name)
def test_stored_selection_mirrors_the_prompt(path):
    """`reference.selection.ranges` must say what the prompt says.

    Nothing reads the field today -- the scorer recomputes from the bundle and
    the harness hands the agent `prompt.md` -- so a disagreement mis-scores
    nothing now, which is exactly why six of them survived unnoticed: 008 had
    one of chain E's ranges duplicated, chain B reduced to a single span and
    chain D collapsed to one range spanning both, while 011, 015, 043, 076 and
    080 each started a chain a few residues late. The generation driver that
    produced these files is not in the repository, so this test, not the
    generator, is what keeps the mirror honest.
    """
    from mddatabench.contract_audit import selection_range_findings

    spec = json.loads(path.read_text())
    findings = selection_range_findings(
        (path.parent / "prompt.md").read_text(), spec["reference"]["selection"])
    assert not findings, "; ".join(f["detail"] for f in findings)


def test_an_insertion_code_range_is_compared_as_written():
    """036 declares 1A-79; reading that as 1-79 would report a false mismatch."""
    from mddatabench.contract_audit import declared_range_tokens

    prompt = (DATASET / "tasks" / "036_ligand_1ceb" / "prompt.md").read_text()
    assert declared_range_tokens(prompt) == {"A": [("1A", "79")]}


@pytest.mark.parametrize("stored,why", [
    ({"A": [["1", "10"], ["1", "10"]]}, "a duplicated range"),
    ({"A": [["1", "10"]]}, "a dropped second range"),
    ({"A": [["20", "30"], ["1", "10"]]}, "ranges out of declared order"),
])
def test_range_comparison_rejects_the_shapes_that_hid_008(stored, why):
    """Set comparison would accept all three; 008 carried the first two."""
    from mddatabench.contract_audit import selection_range_findings

    prompt = ("Simulate X, PDB entry **1XYZ**, chain **A** residues **1–10** "
              "and **20–30**, in explicit solvent.\n")
    assert selection_range_findings(prompt, {"ranges": stored}), why
