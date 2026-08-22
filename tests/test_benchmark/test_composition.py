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


def test_element_swap_that_preserves_the_total_is_detected(tmp_path):
    reference = glycine(1, 1, (0.0, 0.0, 0.0))
    submitted = [row.replace("           N\n", "           O\n") if " N  " in row else row
                 for row in glycine(1, 1, (0.0, 0.0, 0.0))]
    ref = cp.split_monomers(cp.read_residues(write(tmp_path, "re.pdb", reference)))
    sub = cp.split_monomers(cp.read_residues(write(tmp_path, "se.pdb", submitted)))
    assert cp.atom_totals(ref) == cp.atom_totals(sub)
    assert cp.element_totals(ref) != cp.element_totals(sub)


def test_disulfides_come_from_conect_and_zero_is_an_expectation(tmp_path):
    # Two cysteines linked head-to-tail, with their SG atoms placed 2.04 A apart
    # -- the distance measured in both of D03's artifacts.
    rows = (glycine(1, 1, (0.0, 0.0, 0.0), "CYX")
            + [atom(5, "SG", "CYX", 1, (1.4, 2.0, 0.0), "S")]
            + glycine(6, 2, (3.8, 0.0, 0.0), "CYX")
            + [atom(10, "SG", "CYX", 2, (1.4, 4.04, 0.0), "S")])
    reference = write(tmp_path, "ss_ref.pdb", rows)
    monomers = cp.split_monomers(cp.read_residues(reference))
    expected, cyx = cp.reference_disulfides(monomers)
    assert cyx == 2 and len(expected) == 1

    without = write(tmp_path, "ss_none.pdb", rows)
    observed, unusable = cp.submitted_disulfides(without, monomers)
    assert unusable is None and observed == set(), "no CONECT means no bond"

    with_conect = tmp_path / "ss_bonded.pdb"
    with_conect.write_text("".join(rows) + "CONECT    5   10\nEND\n")
    observed, unusable = cp.submitted_disulfides(str(with_conect), monomers)
    assert unusable is None and len(observed) == 1


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


def test_disulfides_survive_a_hybrid36_conect_record(tmp_path):
    """A CONECT line whose partners are past 99999 must not void the whole read."""
    rows = (glycine(1, 1, (0.0, 0.0, 0.0), "CYX", extra=[("SG", "S")])
            + glycine(6, 2, (3.8, 0.0, 0.0), "CYX", extra=[("SG", "S")]))
    # SG of residue 1 is serial 5, SG of residue 2 is serial 10; place them
    # within the 2.5 A disulfide cutoff of each other.
    rows[4] = atom(5, "SG", "CYX", 1, (1.4, 1.0, 0.0), "S")
    rows[9] = atom(10, "SG", "CYX", 2, (1.4, 3.0, 0.0), "S")
    path = tmp_path / "ss.pdb"
    # The bonding a solvated topology actually carries: 64544 of D02's CONECT
    # records hold no decimal field at all.
    path.write_text("".join(rows)
                    + "CONECT    5   10\n"
                    + "CONECTA0000A0001A0002\n"
                    + "CONECTA0001A0000\nEND\n")
    monomers = cp.split_monomers(cp.read_residues(path))
    pairs, unusable = cp.submitted_disulfides(path, monomers)
    assert unusable is None
    assert cp.describe_pairs(pairs) == ["1-2"]
