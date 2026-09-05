"""Slow release checks for topology-derived task contracts."""

from __future__ import annotations

import json
import os
import pathlib

import pytest

from mddatabench import contract_audit as ca


DATASET = pathlib.Path(__file__).resolve().parents[2] / "benchmarks" / "mddatabench"
BUNDLE_ROOT = os.environ.get("MDDATABENCH_BUNDLE_ROOT")

pytestmark = [
    pytest.mark.slow,
    pytest.mark.skipif(
        not BUNDLE_ROOT or not pathlib.Path(BUNDLE_ROOT).is_dir(),
        reason="set MDDATABENCH_BUNDLE_ROOT to a fetched bundle tree",
    ),
]


def test_all_98_task_boundaries_match_their_reference_topologies():
    tasks = sorted(DATASET.glob("tasks/*/task.json"))
    assert len(tasks) == 98
    failures = []
    for task_json in tasks:
        task_dir = task_json.parent
        spec = json.loads(task_json.read_text())
        reference_spec = spec["reference"]
        selection = reference_spec["selection"]
        prompt = (task_dir / "prompt.md").read_text()
        reference, _ = ca._reference_backbone_contract(
            pathlib.Path(BUNDLE_ROOT)
            / f"{reference_spec['node']}_{reference_spec['accession']}")
        for pdb_id in reference_spec["pdb_ids"]:
            deposit = DATASET / "_deposits" / f"{pdb_id.upper()}.cif"
            findings = ca._boundary_contract_findings(
                prompt, selection, ca._declared(prompt),
                ca.deposit_polymer_scheme(deposit), reference)
            if findings:
                failures.append((task_dir.name, pdb_id, findings))
    assert failures == []


def test_all_98_tasks_disclose_nonstandard_reference_protonation():
    tasks = sorted(DATASET.glob("tasks/*/task.json"))
    assert len(tasks) == 98
    failures = []
    for task_json in tasks:
        task_dir = task_json.parent
        spec = json.loads(task_json.read_text())
        reference_spec = spec["reference"]
        selection = reference_spec["selection"]
        prompt = (task_dir / "prompt.md").read_text()
        reference_pdb = (
            pathlib.Path(BUNDLE_ROOT)
            / f"{reference_spec['node']}_{reference_spec['accession']}"
            / "reference.pdb"
        )
        for pdb_id in reference_spec["pdb_ids"]:
            deposit = DATASET / "_deposits" / f"{pdb_id.upper()}.cif"
            findings = ca._protonation_contract_findings(
                prompt, selection, ca._declared(prompt),
                ca.deposit_polymer_scheme(deposit), reference_pdb)
            if findings:
                failures.append((task_dir.name, pdb_id, findings))
    assert failures == []


def test_088_author_endpoints_and_sequence_match_reference():
    """Author 126 is absent; PHE260 must not be confused with renumbered PHE259."""
    from mddatabench.composition import CANONICAL_RESIDUE

    task = DATASET / "tasks/088_soluble_12ca"
    spec = json.loads((task / "task.json").read_text())
    selection = spec["reference"]["selection"]
    prompt = (task / "prompt.md").read_text()
    deposit_file = DATASET / "_deposits/12CA.cif"
    bundle = pathlib.Path(BUNDLE_ROOT) / "mmb_A0001"
    scheme = ca.deposit_polymer_scheme(deposit_file)
    declared = ca._declared(prompt)
    selected = ca._selected_deposit(ca._structure_records(deposit_file), declared)
    reference = [r for r in ca._structure_records(bundle / "reference.pdb") if ca._is_polymer(r)]

    assert ca.stored_range_tokens(selection) == {"A": [("5", "260")]}
    assert ca.declared_range_tokens(prompt) == {"A": [("5", "260")]}
    assert all(number != 126 for number, _, _ in scheme["A"])
    assert len(selected) == len(reference) == 255
    assert [(selected[i].site, selected[i].name) for i in (0, -1)] == [
        ("A:5", "TRP"), ("A:260", "PHE")]
    assert [(reference[i].site, reference[i].name) for i in (0, -1)] == [
        ("A:1", "TRP"), ("A:255", "PHE")]
    assert [CANONICAL_RESIDUE.get(r.name, r.name) for r in selected] == [
        CANONICAL_RESIDUE.get(r.name, r.name) for r in reference]

    backbone, _ = ca._reference_backbone_contract(bundle)
    assert ca._boundary_contract_findings(prompt, selection, declared, scheme, backbone) == []
    # The proposed 5--259 correction would remove the real terminal PHE.
    selection["ranges"]["A"] = [["5", "259"]]
    shortened = prompt.replace("5–260", "5–259")
    findings = ca._boundary_contract_findings(
        shortened, selection, ca._declared(shortened), scheme, backbone)
    assert findings[0]["kind"] == "selection_components_differ_from_reference"
    assert "254 polymer sites" in findings[0]["detail"]
