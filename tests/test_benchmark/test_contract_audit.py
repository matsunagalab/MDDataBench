"""Contract audit fixtures for the defects found before the 300-run rerun."""

from __future__ import annotations

import json
import re
from pathlib import Path
import tomllib

from mddatabench import contract_audit as ca


def test_gemmi_runtime_dependency_is_declared_and_importable():
    """The audit must not work only inside the campaign's scientific SIF."""
    project = tomllib.loads(
        (Path(__file__).parents[2] / "pyproject.toml").read_text()
    )
    dependencies = project["project"]["dependencies"]
    assert any(re.match(r"^gemmi(?:\W|$)", dependency, re.I)
               for dependency in dependencies)

    # This deliberately fails rather than skips. A supported installation is
    # incomplete if the dependency declaration did not produce an importable
    # audit runtime.
    import gemmi

    assert gemmi.cif is not None


def _task(tmp_path, prompt, pdb_ids=("ONE",)):
    task = tmp_path / "dataset" / "tasks" / "case"
    task.mkdir(parents=True)
    (task / "task.json").write_text(json.dumps({
        "task_id": "case", "reference": {"pdb_ids": list(pdb_ids)}}))
    (task / "prompt.md").write_text(prompt)
    bundle = tmp_path / "bundle"
    bundle.mkdir()
    (bundle / "reference.pdb").write_text("END\n")
    return task, bundle


def _record(chain, number, name, icode=""):
    return ca.Residue(chain, number, icode, name)


def _stub_records(monkeypatch, reference, deposits):
    def records(path):
        if path.name == "reference.pdb":
            return reference
        return deposits[path.stem]

    monkeypatch.setattr(ca, "_structure_records", records)
    monkeypatch.setattr(ca, "_deposit_path",
                        lambda pdb_id, cache: Path(f"{pdb_id}.cif"))
    monkeypatch.setattr(ca, "_reference_disulfide_positions", lambda bundle: set())
    monkeypatch.setattr(ca, "_deposit_disulfide_positions",
                        lambda path, declared, selected: set())
    monkeypatch.setattr(ca, "_connected_metals",
                        lambda path, declared, records:
                        [r for r in records if ca._classify(r.name) == "metal"])


def test_quoted_mmcif_and_nmr_use_first_model(tmp_path):
    cif = tmp_path / "nmr.cif"
    cif.write_text("""data_nmr
loop_
_atom_site.group_PDB
_atom_site.id
_atom_site.type_symbol
_atom_site.label_atom_id
_atom_site.label_comp_id
_atom_site.label_asym_id
_atom_site.label_entity_id
_atom_site.label_seq_id
_atom_site.pdbx_PDB_ins_code
_atom_site.Cartn_x
_atom_site.Cartn_y
_atom_site.Cartn_z
_atom_site.occupancy
_atom_site.B_iso_or_equiv
_atom_site.pdbx_formal_charge
_atom_site.auth_seq_id
_atom_site.auth_comp_id
_atom_site.auth_asym_id
_atom_site.auth_atom_id
_atom_site.pdbx_PDB_model_num
ATOM 1 C 'CA' 'ALA' A 1 1 ? 0 0 0 1 0 ? 7 ALA X CA 1
ATOM 2 C 'CA' 'GLY' A 1 1 ? 1 0 0 1 0 ? 7 GLY X CA 2
#
""")

    records = ca._structure_records(cif)

    assert [(r.chain, r.number, r.name) for r in records] == [("X", 7, "ALA")]


def test_modified_polymer_residues_use_the_wwpdb_dictionary():
    assert ca._classify("SEP") == "protein"
    assert ca._classify("TPO") == "protein"
    assert ca._classify("PTR") == "protein"
    assert ca._classify("PSU") == "nucleic"
    # Crystallisation additives must not become polymer merely because Gemmi
    # has a dictionary entry for them.
    assert ca._classify("SO4") == "other"


def test_ligand_occurrences_keep_count_and_site(tmp_path, monkeypatch):
    task, bundle = _task(
        tmp_path,
        "Simulate PDB **ONE**, chain **A** residues **1–2**.")
    reference = [_record("A", 1, "ALA"), _record("A", 2, "GLY"),
                 _record("M", 8, "LIG"), _record("N", 9, "LIG")]
    _stub_records(monkeypatch, reference, {"ONE": reference})

    report = ca.audit_task_contract(str(task), str(bundle), str(tmp_path / "cache"))

    unnamed = [f for f in report["findings"]
               if f["kind"] == "reference_other_unnamed"]
    assert [(f["component"], f["site"]) for f in unnamed] == [
        ("LIG", "M:8"), ("LIG", "N:9")]


def test_ligand_charge_statement_does_not_request_its_presence(tmp_path, monkeypatch):
    task, bundle = _task(
        tmp_path,
        "Simulate chain **A** residues **1–1**. Treat the LIG ligand as "
        "having expected formal net charge 0.")
    reference = [_record("A", 1, "ALA"), _record("M", 2, "LIG")]
    _stub_records(monkeypatch, reference, {"ONE": reference})

    report = ca.audit_task_contract(str(task), str(bundle), str(tmp_path / "cache"))

    finding = next(f for f in report["findings"]
                   if f["kind"] == "reference_other_not_requested")
    assert finding["site"] == "M:2"


def test_structural_zinc_is_not_hidden_as_bulk_counterion(tmp_path, monkeypatch):
    task, bundle = _task(
        tmp_path,
        "Simulate PDB **ONE**, chain **A** residues **1–1**. Keep its structural zinc.")
    records = [_record("A", 1, "CYS"), _record("Z", 401, "ZN")]
    _stub_records(monkeypatch, records, {"ONE": records})

    report = ca.audit_task_contract(str(task), str(bundle), str(tmp_path / "cache"))

    assert ca._classify("ZN") == "metal"
    assert not [f for f in report["findings"] if "metal" in f["kind"]]


def test_unnamed_reference_zinc_is_a_contract_finding(tmp_path, monkeypatch):
    task, bundle = _task(
        tmp_path,
        "Simulate PDB **ONE**, chain **A** residues **1–1**.")
    records = [_record("A", 1, "CYS"), _record("Z", 401, "ZN")]
    _stub_records(monkeypatch, records, {"ONE": records})

    report = ca.audit_task_contract(str(task), str(bundle), str(tmp_path / "cache"))

    finding = next(f for f in report["findings"]
                   if f["kind"] == "reference_metal_unnamed")
    assert finding["component"] == "ZN"
    assert finding["site"] == "Z:401"


def test_multiple_caps_are_compared_by_count_and_sites(tmp_path, monkeypatch):
    task, bundle = _task(
        tmp_path,
        "Simulate PDB **ONE**, chain **A** residues **1–1**. Keep the ACE caps.")
    reference = [_record("A", 1, "ALA"), _record("A", 0, "ACE")]
    deposit = reference + [_record("B", 0, "ACE")]
    _stub_records(monkeypatch, reference, {"ONE": deposit})

    report = ca.audit_task_contract(str(task), str(bundle), str(tmp_path / "cache"))

    mismatch = next(f for f in report["findings"]
                    if f["kind"] == "deposit_reference_cap_mismatch")
    assert mismatch["deposit_sites"] == ["ACE@A:0", "ACE@B:0"]
    assert mismatch["reference_sites"] == ["ACE@A:0"]


def test_disulfide_pair_set_difference_not_only_zero_vs_nonzero(
    tmp_path, monkeypatch,
):
    task, bundle = _task(
        tmp_path,
        "Simulate PDB **ONE**, chain **A** residues **1–4**.")
    records = [_record("A", i, "CYS") for i in range(1, 5)]
    _stub_records(monkeypatch, records, {"ONE": records})
    monkeypatch.setattr(ca, "_reference_disulfide_positions",
                        lambda bundle: {(1, 4)})
    monkeypatch.setattr(ca, "_deposit_disulfide_positions",
                        lambda path, declared, selected: {(2, 3)})

    report = ca.audit_task_contract(str(task), str(bundle), str(tmp_path / "cache"))

    finding = next(f for f in report["findings"]
                   if f["kind"] == "deposit_reference_disulfide_mismatch")
    assert "[(2, 3)]" in finding["detail"]
    assert "[(1, 4)]" in finding["detail"]


def test_every_pdb_id_is_audited(tmp_path, monkeypatch):
    task, bundle = _task(
        tmp_path,
        "Simulate chain **A** residues **1–1**.", pdb_ids=("ONE", "TWO"))
    reference = [_record("A", 1, "ALA")]
    _stub_records(monkeypatch, reference,
                  {"ONE": reference, "TWO": reference + [_record("A", 0, "ACE")]})

    report = ca.audit_task_contract(str(task), str(bundle), str(tmp_path / "cache"))

    assert any(f.get("pdb_id") == "TWO" for f in report["findings"])


def test_cap_word_does_not_match_capacity():
    assert ca._mentions("retain binding capacity", "ACE", cap=True) is False
    assert ca._mentions("simulate the chain uncapped", "ACE", cap=True) is True


def test_prompt_ranges_are_counted_and_exclusions_removed():
    declared = ca._declared(
        "chain **A** residues **1–10** and **20–25**, and chain **B** residues "
        "**30–35**. Residue 4–6 of chain A is not part of the reference. "
        "Leave it out.")
    assert set(declared["selected"]) == {"A", "B"}
    assert len(declared["selected"]["A"]) == 13
    assert len(declared["selected"]["B"]) == 6
    assert ca._declared_polymer_lengths(declared) == [3, 4, 6, 6]


def test_single_chain_modified_residue_omission_needs_no_repeated_chain():
    declared = ca._declared(
        "Simulate chain **A** residues **1001–1196**. "
        "Residue 1004 (YCM) is not part of the reference. Leave it out.")

    assert 1003 in declared["selected"]["A"]
    assert 1004 not in declared["selected"]["A"]


def test_polymer_comparison_uses_observed_selection_not_range_arithmetic(
    tmp_path, monkeypatch,
):
    task, bundle = _task(
        tmp_path,
        "Simulate chain **A** residues **1–4**. Chain A does not resolve "
        "residue 3; the range runs through it, so build them.")
    reference = [_record("A", number, "ALA") for number in range(1, 5)]
    deposit = [_record("A", number, "ALA") for number in (1, 2, 4)]
    _stub_records(monkeypatch, reference, {"ONE": deposit})

    report = ca.audit_task_contract(str(task), str(bundle), str(tmp_path / "cache"))

    assert not [f for f in report["findings"]
                if f["kind"] == "reference_polymer_selection_mismatch"]


def test_disulfide_position_frame_preserves_range_and_insertion_order():
    declared = ca._declared(
        "chain **A** residues **0–1** and **1106–1106** and **219–220**.")
    selected = [
        _record("A", 0, "ALA"), _record("A", 1, "CYS", "A"),
        _record("A", 1, "CYS"), _record("A", 219, "CYS"),
        _record("A", 220, "ALA"), _record("A", 1106, "ALA"),
    ]

    positions = ca._deposit_positions(selected, declared)

    assert positions[("A", 1, "A")] == 2
    assert positions[("A", 1, "")] == 3
    assert positions[("A", 1106, "")] == 4
    assert positions[("A", 219, "")] == 5


def _write_two_chain_pdb(path, separation):
    path.write_text(
        "ATOM      1  CA  ALA A   1       0.000   0.000   0.000  1.00 20.00"
        "           C\n"
        f"ATOM      2  CA  GLY B   1      {separation:6.3f}   0.000   0.000"
        "  1.00 20.00           C\n"
        "TER\nEND\n"
    )


def _multi_chain_contact_report(tmp_path, monkeypatch, separation):
    task, bundle = _task(
        tmp_path,
        "Simulate PDB **ONE**, chain **A** residues **1–1**, chain **B** "
        "residues **1–1**.")
    deposit = tmp_path / "ONE.pdb"
    _write_two_chain_pdb(deposit, separation)
    _write_two_chain_pdb(bundle / "reference.pdb", 3.0)
    monkeypatch.setattr(ca, "_deposit_path", lambda pdb_id, cache: deposit)
    monkeypatch.setattr(ca, "_reference_disulfide_positions", lambda bundle: set())
    monkeypatch.setattr(ca, "_deposit_disulfide_positions",
                        lambda path, declared, selected: set())
    return ca.audit_task_contract(str(task), str(bundle), str(tmp_path / "cache"))


def test_multi_chain_selection_with_heavy_atom_contact_passes(tmp_path, monkeypatch):
    report = _multi_chain_contact_report(tmp_path, monkeypatch, 3.0)

    assert not [finding for finding in report["findings"]
                if finding["kind"] == "deposit_polymer_chains_do_not_contact"]
    geometry = report["multi_chain_geometry"][0]
    assert geometry["deposit"]["closest_inter_chain_contact_angstrom"] == 3.0
    assert geometry["contact_cutoff_angstrom"] == 4.0


def test_widely_separated_multi_chain_selection_fails_with_rg_diagnostic(
    tmp_path, monkeypatch,
):
    report = _multi_chain_contact_report(tmp_path, monkeypatch, 20.0)

    finding = next(finding for finding in report["findings"]
                   if finding["kind"] == "deposit_polymer_chains_do_not_contact")
    assert "contact cutoff of 4.0 A" in finding["detail"]
    assert "geometric Rg" in finding["detail"]
    geometry = report["multi_chain_geometry"][0]
    assert geometry["deposit"]["closest_inter_chain_contact_angstrom"] is None
    assert geometry["deposit"][
        "heavy_atom_geometric_radius_of_gyration_angstrom"] == 10.0
    assert geometry["reference"][
        "heavy_atom_geometric_radius_of_gyration_angstrom"] == 1.5
