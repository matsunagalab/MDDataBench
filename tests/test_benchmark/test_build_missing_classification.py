"""Which build_missing tasks really build, and whether at a terminus.

The stored `selection.build_missing` cannot answer either question: it reports a
non-zero value for seven tasks whose reference added no residues at all. What
answers it is the composition difference between the bundle and the deposit
residues observed inside the ranges the prompt states -- no reference numbering
involved, because MDDB renumbers each bundle from one and renames its chains.

The classification matters because the two halves need different machinery.
MODELLER's loop modelling needs an anchor on both sides and so takes internal
gaps only; a terminus is PDBFixer's, and only when asked, since neither builds
one by default. Six tasks need terminal construction and four need only
internal, so a change to either path has a known set of tasks to answer for.

The fixture is checked in with each bundle's SHA-256 so the numbers stay
reviewable where the bundles, which are fetched and never vendored, are absent.
"""

from __future__ import annotations

import collections
import hashlib
import json
import os
import pathlib

import pytest

DATASET = pathlib.Path(__file__).resolve().parents[2] / "benchmarks" / "mddatabench"
FIXTURE = pathlib.Path(__file__).parent / "fixtures" / "build_missing_classification.json"
BUNDLE_ROOT = os.environ.get("MDDATABENCH_BUNDLE_ROOT")
needs_bundles = pytest.mark.skipif(
    not BUNDLE_ROOT or not pathlib.Path(BUNDLE_ROOT).is_dir(),
    reason="set MDDATABENCH_BUNDLE_ROOT to a fetched bundle tree")

RECORDED = json.loads(FIXTURE.read_text())

# What the fixture is expected to say, written out rather than derived from it,
# so a regenerated fixture that quietly changed its mind fails here.
BUILDS_AT_A_TERMINUS = {"029_complex_1e3u", "062_metal_6w9c", "065_soluble_1a62",
                        "068_soluble_1ail", "076_soluble_1ctf", "080_soluble_1ez3"}
BUILDS_ONLY_INTERNALLY = {"015_antibody_1ahw", "021_antibody_3eoa",
                          "022_antibody_3rvw", "023_antibody_3wd5"}
BUILDS_NOTHING = {"001_membrane_5yc8", "004_membrane_5zkb", "008_membrane_6i53",
                  "011_membrane_6kuy", "019_antibody_2dd8", "020_antibody_2vis",
                  "030_complex_1ffw", "043_ligand_5od1", "044_ligand_5oh3",
                  "045_ligand_6j3o"}


def _classes(task_id: str) -> collections.Counter:
    return collections.Counter(segment["class"]
                               for segment in RECORDED[task_id]["segments"])


def test_the_fixture_covers_every_task_that_declares_build_missing():
    declared = {
        path.parent.name
        for path in sorted(DATASET.glob("tasks/*/task.json"))
        if json.loads(path.read_text())["reference"]["selection"].get("build_missing")
    }
    assert set(RECORDED) == declared
    assert declared == BUILDS_AT_A_TERMINUS | BUILDS_ONLY_INTERNALLY | BUILDS_NOTHING


@pytest.mark.parametrize("task_id", sorted(BUILDS_NOTHING))
def test_a_task_whose_reference_built_nothing_has_no_sites(task_id):
    """The seven false positives, plus three more that never carried prose.

    Each still reports a non-zero selection.build_missing. If any of these ever
    gains a site, a prompt somewhere is about to be told to add residues the
    reference does not have.
    """
    assert RECORDED[task_id]["reference_delta"] == 0
    assert RECORDED[task_id]["build_sites"] == []


@pytest.mark.parametrize("task_id", sorted(BUILDS_ONLY_INTERNALLY))
def test_an_internal_only_task_needs_no_terminal_construction(task_id):
    classes = _classes(task_id)
    assert classes and set(classes) == {"internal"}
    assert RECORDED[task_id]["reference_delta"] == sum(classes.values())


@pytest.mark.parametrize("task_id", sorted(BUILDS_AT_A_TERMINUS))
def test_a_terminal_task_is_recorded_as_one(task_id):
    classes = _classes(task_id)
    assert classes["n_terminal"] or classes["c_terminal"]
    assert RECORDED[task_id]["reference_delta"] == sum(classes.values())


def test_the_mixed_case_is_not_flattened():
    """062 builds two internal residues and one at the C terminus.

    Recording it as either alone would hide half of what it needs.
    """
    assert _classes("062_metal_6w9c") == {"internal": 2, "c_terminal": 1}


def test_no_site_is_left_unclassified():
    for task_id, record in RECORDED.items():
        kinds = {segment["class"] for segment in record["segments"]}
        assert "unclassified" not in kinds, task_id


@needs_bundles
@pytest.mark.parametrize("task_id", sorted(RECORDED))
def test_the_recorded_bundle_is_the_one_measured(task_id):
    """A bundle refetched with different contents invalidates the numbers."""
    spec = json.loads(
        (DATASET / "tasks" / task_id / "task.json").read_text())["reference"]
    bundle = (pathlib.Path(BUNDLE_ROOT)
              / f"{spec['node']}_{spec['accession']}" / "reference.pdb")
    digest = hashlib.sha256(bundle.read_bytes()).hexdigest()
    assert digest == RECORDED[task_id]["bundle_reference_pdb_sha256"]


def test_build_sites_and_segments_agree():
    """A fixture whose two site lists disagree is describing nothing."""
    for task_id, record in RECORDED.items():
        assert record["build_sites"] == [s["site"] for s in record["segments"]], task_id


@needs_bundles
@pytest.mark.parametrize("task_id", sorted(RECORDED))
def test_the_delta_still_matches_the_bundle(task_id):
    """Recompute from the real files: the fixture is a record, not the source."""
    from mddatabench import contract_audit as ca

    spec = json.loads(
        (DATASET / "tasks" / task_id / "task.json").read_text())["reference"]
    declared = ca._declared((DATASET / "tasks" / task_id / "prompt.md").read_text())
    deposit = ca._deposit_path(spec["pdb_ids"][0], DATASET / "_deposits")
    bundle = (pathlib.Path(BUNDLE_ROOT)
              / f"{spec['node']}_{spec['accession']}" / "reference.pdb")

    observed = [r for r in ca._selected_deposit(ca._structure_records(deposit),
                                                declared) if ca._is_polymer(r)]
    reference = [r for r in ca._structure_records(bundle) if ca._is_polymer(r)]
    assert len(reference) - len(observed) == RECORDED[task_id]["reference_delta"]


@needs_bundles
@pytest.mark.parametrize("task_id", sorted(RECORDED))
def test_every_site_and_class_is_recomputed(task_id):
    """The sites and their classes, not just the totals.

    Without this the fixture could move 062's C-terminal residue onto an
    internal one, or replace a site with a different number, and every other
    assertion here would still pass: the membership sets check which tasks
    build, the delta checks how many, and neither looks at which residues.

    Classification reads the deposit's own polymer scheme rather than comparing
    author numbers, because author numbering carries insertion codes and can
    restart or run backwards, so it does not order the chain.
    """
    from mddatabench import contract_audit as ca

    spec = json.loads(
        (DATASET / "tasks" / task_id / "task.json").read_text())["reference"]
    declared = ca._declared((DATASET / "tasks" / task_id / "prompt.md").read_text())
    scheme = ca.deposit_polymer_scheme(
        ca._deposit_path(spec["pdb_ids"][0], DATASET / "_deposits"))

    segments = []
    for chain, sites in sorted(declared["build_sites"].items()):
        for entry in ca.classify_build_sites(
                scheme.get(chain, []), declared["selected"].get(chain, set()),
                sorted(sites)):
            segments.append({"site": f"{chain}:{entry['site']}",
                             "class": entry["class"]})
    assert segments == RECORDED[task_id]["segments"]


@needs_bundles
def test_the_classifier_reads_position_not_residue_number():
    """1CTF's built tail is 47-52 and its observed run starts at 53.

    Numerically 47 is simply the smallest number present, so a comparison of
    numbers gets this right by accident. What makes it N-terminal is that the
    deposit's polymer scheme places those six positions before every observed
    one, which is what the classifier reads.
    """
    from mddatabench import contract_audit as ca

    scheme = ca.deposit_polymer_scheme(DATASET / "_deposits" / "1CTF.cif")["A"]
    assert [number for number, _, observed in scheme if not observed] == [
        47, 48, 49, 50, 51, 52]
    classified = ca.classify_build_sites(
        scheme, set(range(47, 121)), [(n, "") for n in range(47, 53)])
    assert {entry["class"] for entry in classified} == {"n_terminal"}
