"""Unit tests for the per-monomer composition checks.

These run on synthetic PDBs, so they need neither a fetched bundle nor OpenMM
and are not marked slow.  They exist because the properties being relied on are
not obvious: that a histidine tautomer is invisible to atom counts while every
ionisation variant is not, and that monomers are found from backbone geometry
rather than from chain IDs.
"""

from __future__ import annotations

import pytest

from mddatabench import composition as cp


def atom(serial, name, resname, resseq, xyz, element, chain="A"):
    x, y, z = xyz
    return (f"ATOM  {serial:5d} {name:^4}{' '}{resname:>3} {chain}{resseq:4d}    "
            f"{x:8.3f}{y:8.3f}{z:8.3f}{1.0:6.2f}{0.0:6.2f}          {element:>2}\n")


def glycine(serial, resseq, origin, resname="GLY", extra=()):
    """N, CA, C, O plus whatever extra atoms the caller wants."""
    ox, oy, oz = origin
    rows = [atom(serial, "N", resname, resseq, (ox, oy, oz), "N"),
            atom(serial + 1, "CA", resname, resseq, (ox + 1.4, oy, oz), "C"),
            atom(serial + 2, "C", resname, resseq, (ox + 2.5, oy, oz), "C"),
            atom(serial + 3, "O", resname, resseq, (ox + 3.1, oy, oz), "O")]
    for offset, (name, element) in enumerate(extra, start=4):
        rows.append(atom(serial + offset, name, resname, resseq,
                         (ox + 1.4, oy + 1.0 + offset * 0.1, oz), element))
    return rows


def write(tmp_path, name, rows):
    path = tmp_path / name
    path.write_text("".join(rows) + "END\n")
    return str(path)


def test_monomers_come_from_backbone_geometry_not_chain_ids(tmp_path):
    """Two residues 1.3 A apart are one monomer; move them apart and they are two."""
    linked = glycine(1, 1, (0.0, 0.0, 0.0)) + glycine(5, 2, (3.8, 0.0, 0.0))
    broken = glycine(1, 1, (0.0, 0.0, 0.0)) + glycine(5, 2, (30.0, 0.0, 0.0))
    assert len(cp.split_monomers(cp.read_residues(write(tmp_path, "a.pdb", linked)))) == 1
    assert len(cp.split_monomers(cp.read_residues(write(tmp_path, "b.pdb", broken)))) == 2


def test_repeated_chain_ids_do_not_merge_separate_monomers(tmp_path):
    """MDClaw warns that PDB chain IDs may be reused, so two components can both
    be labelled A:1 GLY. A repeated atom name is what separates them."""
    rows = glycine(1, 1, (0.0, 0.0, 0.0)) + glycine(5, 1, (30.0, 0.0, 0.0))
    residues = cp.read_residues(write(tmp_path, "c.pdb", rows))
    assert len(residues) == 2, "identical labels must not collapse into one residue"
    assert len(cp.split_monomers(residues)) == 2


@pytest.mark.parametrize("name", ["HID", "HIE"])
def test_histidine_tautomer_is_invisible_to_atom_counts(tmp_path, name):
    reference = glycine(1, 1, (0.0, 0.0, 0.0), "HID", extra=[("HD1", "H")])
    submitted = glycine(1, 1, (0.0, 0.0, 0.0), name, extra=[("HE2", "H")])
    ref = cp.split_monomers(cp.read_residues(write(tmp_path, f"r{name}.pdb", reference)))
    sub = cp.split_monomers(cp.read_residues(write(tmp_path, f"s{name}.pdb", submitted)))
    pairs, problems = cp.match_monomers(ref, sub)
    assert not problems
    assert cp.compare_monomer(*pairs[0]) == {"sequence": [], "atom_counts": [], "elements": []}


def test_one_extra_hydrogen_is_detected(tmp_path):
    """HIP costs exactly one hydrogen -- the error the old +/-2 tolerance admitted."""
    reference = glycine(1, 1, (0.0, 0.0, 0.0), "HID", extra=[("HD1", "H")])
    submitted = glycine(1, 1, (0.0, 0.0, 0.0), "HIP", extra=[("HD1", "H"), ("HE2", "H")])
    ref = cp.split_monomers(cp.read_residues(write(tmp_path, "rh.pdb", reference)))
    sub = cp.split_monomers(cp.read_residues(write(tmp_path, "sh.pdb", submitted)))
    pairs, _ = cp.match_monomers(ref, sub)
    findings = cp.compare_monomer(*pairs[0])
    assert findings["atom_counts"] and not findings["sequence"]


def test_element_swap_that_preserves_the_count_is_detected(tmp_path):
    """Counting atoms cannot see a substitution; counting elements can."""
    reference = glycine(1, 1, (0.0, 0.0, 0.0))
    submitted = [row.replace("           N\n", "           O\n") if " N  " in row else row
                 for row in glycine(1, 1, (0.0, 0.0, 0.0))]
    ref = cp.split_monomers(cp.read_residues(write(tmp_path, "re.pdb", reference)))
    sub = cp.split_monomers(cp.read_residues(write(tmp_path, "se.pdb", submitted)))
    assert ref[0][0].n_atoms == sub[0][0].n_atoms
    assert cp.element_totals(ref) != cp.element_totals(sub)

def test_solvent_and_ions_are_not_part_of_the_solute(tmp_path):
    rows = glycine(1, 1, (0.0, 0.0, 0.0)) + [
        atom(9, "O", "HOH", 2, (10.0, 0.0, 0.0), "O", chain="B"),
        atom(10, "NA", "NA", 3, (12.0, 0.0, 0.0), "NA", chain="C")]
    residues = cp.read_residues(write(tmp_path, "solv.pdb", rows))
    assert len(residues) == 1 and residues[0].name == "GLY"


# --- hybrid-36 serials -------------------------------------------------------
# OpenMM writes hybrid-36 past 99999 and the CONECT reader used to call those
# records malformed, which made every disulfide check on a solvated system give
# up.  The boundaries below are the ones the format specification fixes.

@pytest.mark.parametrize("field, value", [
    ("    1", 1),
    ("99999", 99999),
    ("A0000", 100000),          # first hybrid-36 value
    ("A0001", 100001),
    ("ZZZZZ", 43770015),        # last uppercase value
    ("a0000", 43770016),        # first lowercase value
    ("zzzzz", 87440031),        # last representable value
])
def test_hybrid36_serials_decode(field, value):
    assert cp.hy36decode(field) == value


@pytest.mark.parametrize("field", ["     ", "xx", "A00 0", "!!!!!"])
def test_unreadable_serials_are_none_not_an_exception(field):
    assert cp.hy36decode(field) is None


# --- what is exempt from the protonation comparison, and why -----------------
# Two kinds of residue have no defensible target to compare against, and both
# are found by geometry so the answer is the same on a reference that wrote
# CYM/HIP and a submission that wrote CYS/HIE.

def metal(serial, resname, resnum, xyz, element="ZN", chain="A"):
    x, y, z = xyz
    return (f"HETATM{serial:5d} {element:<4}{resname:>4} {chain}{resnum:4d}    "
            f"{x:8.3f}{y:8.3f}{z:8.3f}{1.0:6.2f}{0.0:6.2f}          {element:>2}\n")


def test_a_catalytic_pair_is_found_by_geometry_not_by_residue_name(tmp_path):
    """CYS/HIE and CYM/HIP give the same answer: heavy atoms do not move."""
    def build(cys_name, his_name):
        # One monomer: backbones 3.8 A apart so the peptide link is found, and
        # the two side-chain donors 3.0 A from each other.
        rows = glycine(1, 10, (0.0, 0.0, 0.0), cys_name, extra=[("SG", "S")])
        rows += glycine(6, 20, (3.8, 0.0, 0.0), his_name,
                        extra=[("ND1", "N"), ("NE2", "N")])
        rows[4] = atom(5, "SG", cys_name, 10, (0.0, 5.0, 0.0), "S")
        rows[9] = atom(10, "ND1", his_name, 20, (0.0, 8.0, 0.0), "N")
        return rows

    for cys_name, his_name in (("CYS", "HIE"), ("CYM", "HIP")):
        path = write(tmp_path, f"{cys_name}{his_name}.pdb", build(cys_name, his_name))
        monomers = cp.split_monomers(cp.read_residues(path))
        found = cp.catalytic_dyad_positions(monomers, cp.read_metals(path))
        assert [sorted(v) for v in found.values()] == [[1, 2]], \
            f"{cys_name}/{his_name} must give the same pair"


def test_a_cysteine_and_histidine_on_one_metal_are_not_a_catalytic_pair(tmp_path):
    """They are close through the metal, not to each other."""
    rows = glycine(1, 10, (0.0, 0.0, 0.0), "CYS", extra=[("SG", "S")])
    rows += glycine(6, 20, (3.8, 0.0, 0.0), "HIS", extra=[("ND1", "N"), ("NE2", "N")])
    rows[4] = atom(5, "SG", "CYS", 10, (0.0, 2.3, 0.0), "S")
    rows[9] = atom(10, "ND1", "HIS", 20, (0.0, -2.1, 0.0), "N")
    rows.append(metal(11, "ZN", 900, (0.0, 0.0, 0.0)))
    path = write(tmp_path, "znsite.pdb", rows)
    monomers = cp.split_monomers(cp.read_residues(path))
    metals = cp.read_metals(path)
    assert cp.catalytic_dyad_positions(monomers, metals) == {}, \
        "both ligate the zinc, so neither is exempt as a catalytic pair"
    assert [sorted(v) for v in cp.metal_ligand_positions(monomers, metals).values()] == [[1, 2]]


def test_a_distant_cysteine_histidine_pair_is_not_exempt(tmp_path):
    """The nearest non-catalytic pair measured in a real reference is 4.08 A."""
    rows = glycine(1, 10, (0.0, 0.0, 0.0), "CYS", extra=[("SG", "S")])
    rows += glycine(6, 20, (3.8, 0.0, 0.0), "HIS", extra=[("ND1", "N"), ("NE2", "N")])
    rows[4] = atom(5, "SG", "CYS", 10, (0.0, 5.0, 0.0), "S")
    rows[9] = atom(10, "ND1", "HIS", 20, (0.0, 9.1, 0.0), "N")
    path = write(tmp_path, "far.pdb", rows)
    monomers = cp.split_monomers(cp.read_residues(path))
    assert cp.catalytic_dyad_positions(monomers, cp.read_metals(path)) == {}


# --- a bilayer is environment, not solute ------------------------------------
# The membrane references carry 360 DPPC around a receptor whose crystal has a
# handful of ordered lipids at most.  Counting them turned every membrane task
# into a guess at the reference's box: 360 lipids contribute 360 monomers and
# 360 phosphorus atoms to comparisons that demand exact equality, so a
# submission with a perfectly good bilayer of 320 failed on both.

def lipid(serial, resseq, origin, name="DPP"):
    ox, oy, oz = origin
    return [atom(serial, "P", name, resseq, (ox, oy, oz), "P"),
            atom(serial + 1, "C1", name, resseq, (ox + 1.5, oy, oz), "C")]


def test_lipids_do_not_enter_the_residue_or_element_comparison(tmp_path):
    rows = glycine(1, 1, (0.0, 0.0, 0.0)) + lipid(5, 2, (20.0, 0.0, 0.0))
    residues = cp.read_residues(write(tmp_path, "bilayer.pdb", rows))
    assert [r.name for r in residues] == ["GLY"]
    assert "P" not in cp.element_totals(cp.split_monomers(residues))


def test_the_species_is_reported_separately_because_it_is_a_decision(tmp_path):
    rows = glycine(1, 1, (0.0, 0.0, 0.0))
    for i in range(3):
        rows += lipid(5 + 2 * i, 2 + i, (20.0 + 5 * i, 0.0, 0.0))
    path = write(tmp_path, "species.pdb", rows)
    assert cp.lipid_species(path) == {"DPP": 3}


def test_a_structure_with_no_lipid_reports_none(tmp_path):
    path = write(tmp_path, "none.pdb", glycine(1, 1, (0.0, 0.0, 0.0)))
    assert cp.lipid_species(path) == {}


def test_the_four_letter_and_three_letter_spellings_are_one_lipid(tmp_path):
    """A PDB truncates DPPC to three columns; both are the same decision."""
    rows = glycine(1, 1, (0.0, 0.0, 0.0)) + lipid(5, 2, (20.0, 0.0, 0.0), "DPP")
    assert set(cp.lipid_species(write(tmp_path, "trunc.pdb", rows))) == {"DPP"}
    assert "DPPC" in cp.LIPID_RESIDUES and "DPP" in cp.LIPID_RESIDUES


# --- one lipid, two spellings ------------------------------------------------
# CHARMM writes DPPC as one residue and a PDB truncates it to DPP; Amber's
# Lipid21 splits the same lipid into a PC head and two PA tails.  Comparing the
# residue names directly rejects a correct Amber submission against a CHARMM
# reference -- the same failure as naming CHARMM36 in a prompt MDClaw can only
# build with Amber.

def test_the_charmm_and_lipid21_spellings_decompose_to_one_chemistry():
    reference, _ = cp.lipid_chemistry({"DPP": 360}, "DPPC")
    submitted, _ = cp.lipid_chemistry({"PC": 300, "PA": 600}, "DPPC")
    assert reference == submitted == frozenset({"PC", "PA"})


def test_a_different_lipid_is_still_a_different_lipid():
    """DPPC is two palmitoyls; POPC swaps one for an oleoyl."""
    wanted, _ = cp.lipid_chemistry({"DPP": 360}, "DPPC")
    popc, _ = cp.lipid_chemistry({"PC": 300, "PA": 300, "OL": 300}, "DPPC")
    assert wanted != popc


def test_lipids_are_counted_by_head_group_not_by_residue():
    """Under Lipid21 one DPPC is three residues; counting residues triples it."""
    _, count = cp.lipid_chemistry({"PC": 300, "PA": 600}, "DPPC")
    assert count == 300
    _, charmm = cp.lipid_chemistry({"DPP": 360}, "DPPC")
    assert charmm == 360


def test_a_truncation_is_read_as_the_lipid_the_contract_states():
    """DPP is DPPC, DPPE or DPPG; three columns cannot say which."""
    assert cp.lipid_components("DPP", "DPPC") == frozenset({"PC", "PA"})
    assert cp.lipid_components("DPP", "DPPE") == frozenset({"PE", "PA"})
    assert cp.lipid_components("DPP") == frozenset()


def test_no_bilayer_decomposes_to_nothing():
    assert cp.lipid_chemistry({}, "DPPC") == (frozenset(), 0)
