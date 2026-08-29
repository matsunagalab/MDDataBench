"""Reading chemistry out of two topologies, on assumptions that were not tested.

Every case here was a real defect found on 2026-08-22, not a hypothetical.  The
three tasks in the dataset are single-chain with one metal each, so none of them
exercised what breaks below.

Marked slow because it needs parmed and openmm, which the fast CI job does not
install.
"""

from __future__ import annotations

import pytest

pytestmark = pytest.mark.slow
parmed = pytest.importorskip("parmed")
mm = pytest.importorskip("openmm")

from mddatabench import composition as cp  # noqa: E402
from mddatabench import scoring as sc  # noqa: E402
from mddatabench import topology as tp  # noqa: E402


def build(atoms):
    """A structure from (element, atom name, residue name, resnum, chain, xyz)."""
    structure = parmed.Structure()
    for element, name, resname, resnum, chain, (x, y, z) in atoms:
        atom = parmed.Atom(name=name, atomic_number=parmed.periodic_table.AtomicNum[element])
        atom.xx, atom.xy, atom.xz = x, y, z
        structure.add_atom(atom, resname, resnum, chain=chain)
    return structure


def test_two_metals_with_the_same_number_are_two_sites():
    """A homo-oligomer numbers its copies alike; a label-keyed dict loses one."""
    structure = build([
        ("S", "SG", "CYS", 10, "A", (0.0, 0.0, 0.0)),
        ("S", "SG", "CYS", 20, "A", (4.6, 0.0, 0.0)),
        ("Zn", "ZN", "ZN", 301, "A", (2.3, 0.0, 0.0)),
        ("S", "SG", "CYS", 10, "B", (0.0, 50.0, 0.0)),
        ("S", "SG", "CYS", 20, "B", (4.6, 50.0, 0.0)),
        ("Zn", "ZN", "ZN", 301, "B", (2.3, 50.0, 0.0)),
    ])
    shells = tp.coordination_shell(structure)
    assert len(shells) == 2, f"one site was overwritten: {list(shells)}"
    assert all(len(donors) == 2 for _, donors in shells.values())


def test_bonds_are_read_from_the_system_not_from_conect():
    """A CONECT record with no force term behind it is not a bond.

    `parmed.openmm.load_topology` takes its bonds from the OpenMM topology, so
    the structure's own list is the PDB's connectivity.  What the checks claim
    to measure is what exerts force, and the two can disagree.
    """
    system = mm.System()
    for _ in range(4):
        system.addParticle(32.06)
    force = mm.HarmonicBondForce()
    force.addBond(0, 1, 0.204, 138908.8)
    system.addForce(force)
    system.addConstraint(2, 3, 0.204)

    structure = build([
        ("S", "SG", "CYS", 10, "A", (0.0, 0.0, 0.0)),
        ("S", "SG", "CYS", 20, "A", (2.04, 0.0, 0.0)),
        ("S", "SG", "CYS", 30, "A", (0.0, 9.0, 0.0)),
        ("S", "SG", "CYS", 40, "A", (2.04, 9.0, 0.0)),
    ])
    bonds = tp.force_bearing_bonds(system, structure)
    assert bonds == {frozenset((0, 1)), frozenset((2, 3))}, \
        "a constrained bond still exerts force and must be counted"
    assert tp.sulfur_bonds(structure, bonds) == {frozenset((0, 1)), frozenset((2, 3))}
    assert tp.sulfur_bonds(structure) == set(), \
        "the structure carries no CONECT-derived bonds of its own"


def test_only_declared_inter_residue_backbone_bonds_are_retained():
    structure = build([
        ("C", "C", "ALA", 1, "A", (0.0, 0.0, 0.0)),
        ("S", "SG", "ALA", 1, "A", (0.0, 2.0, 0.0)),
        ("N", "N", "GLY", 2, "A", (1.33, 0.0, 0.0)),
        ("S", "SG", "GLY", 2, "A", (0.0, 4.0, 0.0)),
    ])
    links = tp.backbone_links(
        structure, {frozenset((0, 2)), frozenset((1, 3))})
    assert len(links) == 1, "a disulfide must not merge polymer backbone components"
    assert links[0]["kind"] == "peptide"
    assert links[0]["atom_indices"] == [0, 2]
    assert links[0]["residue_indices"] == [0, 1]


def test_disulfide_endpoints_keep_both_monomers():
    structure = build([
        ("N", "N", "CYS", 1, "A", (0.0, 0.0, 0.0)),
        ("C", "C", "CYS", 1, "A", (1.3, 0.0, 0.0)),
        ("S", "SG", "CYS", 1, "A", (0.0, 2.0, 0.0)),
        ("N", "N", "CYS", 2, "A", (2.6, 0.0, 0.0)),
        ("C", "C", "CYS", 2, "A", (3.9, 0.0, 0.0)),
        ("S", "SG", "CYS", 2, "A", (2.0, 2.0, 0.0)),
        ("N", "N", "CYS", 1, "B", (0.0, 10.0, 0.0)),
        ("C", "C", "CYS", 1, "B", (1.3, 10.0, 0.0)),
        ("S", "SG", "CYS", 1, "B", (2.0, 4.0, 0.0)),
        ("N", "N", "CYS", 2, "B", (2.6, 10.0, 0.0)),
        ("C", "C", "CYS", 2, "B", (3.9, 10.0, 0.0)),
        ("S", "SG", "CYS", 2, "B", (4.0, 4.0, 0.0)),
    ])
    bonds = {
        frozenset((1, 3)),       # A1:C--A2:N
        frozenset((7, 9)),       # B1:C--B2:N
        frozenset((5, 8)),       # A2:SG--B1:SG
    }
    edges, sizes, dropped = tp.sulfur_bond_monomer_positions(structure, bonds)
    assert sizes == [2, 2]
    assert edges == {frozenset(((0, 2), (1, 1)))}
    assert dropped == []


def _monomer(names):
    return [cp.Residue(name, "A", str(position))
            for position, name in enumerate(names, start=1)]


def _edge(first, second):
    return frozenset((first, second))


def test_whole_disulfide_set_selects_the_identical_copy_permutation():
    """Swapping only L copies defeats independent H/L zip pairing."""
    heavy = ["CYS", "CYS", "CYS"]
    light = ["CYS", "CYS", "GLY", "CYS"]
    reference = [_monomer(heavy), _monomer(light),
                 _monomer(heavy), _monomer(light)]
    submitted = [_monomer(heavy), _monomer(light),
                 _monomer(heavy), _monomer(light)]
    expected = {
        _edge((0, 1), (0, 2)), _edge((1, 1), (1, 2)),
        _edge((2, 1), (2, 2)), _edge((3, 1), (3, 2)),
        _edge((0, 3), (1, 4)), _edge((2, 3), (3, 4)),
    }
    observed = {
        _edge((0, 1), (0, 2)), _edge((1, 1), (1, 2)),
        _edge((2, 1), (2, 2)), _edge((3, 1), (3, 2)),
        _edge((0, 3), (3, 4)), _edge((2, 3), (1, 4)),
    }

    best = sc._best_disulfide_correspondence(
        expected, observed, reference, submitted)
    assert best[0] == 0
    assert best[1] == (0, 3, 2, 1)
    assert not best[3] and not best[4]

    changed = set(observed)
    changed.remove(_edge((2, 3), (1, 4)))
    changed.add(_edge((2, 3), (1, 3)))
    mismatch = sc._best_disulfide_correspondence(
        expected, changed, reference, submitted)
    assert mismatch[0] == 2
    assert len(mismatch[3]) == len(mismatch[4]) == 1


def test_phosphodiester_link_is_retained_in_its_declared_direction():
    structure = build([
        ("O", "O3'", "DA", 1, "A", (0.0, 0.0, 0.0)),
        ("P", "P", "DT", 2, "A", (1.6, 0.0, 0.0)),
    ])
    links = tp.backbone_links(structure, {frozenset((0, 1))})
    assert [(link["kind"], link["atom_names"]) for link in links] == [
        ("phosphodiester", ["O3'", "P"]),
    ]


def test_four_bonds_on_sulfur_is_not_a_valence_violation():
    """A sulfonamide, a sulfate and DMSO all carry four bonds on S."""
    structure = build([
        ("S", "S", "SO4", 1, "A", (0.0, 0.0, 0.0)),
        ("O", "O1", "SO4", 1, "A", (1.5, 0.0, 0.0)),
        ("O", "O2", "SO4", 1, "A", (-1.5, 0.0, 0.0)),
        ("O", "O3", "SO4", 1, "A", (0.0, 1.5, 0.0)),
        ("O", "O4", "SO4", 1, "A", (0.0, -1.5, 0.0)),
    ])
    for index in range(1, 5):
        structure.bonds.append(parmed.Bond(structure.atoms[0], structure.atoms[index]))
    assert tp.valence_problems(structure) == []


def test_only_side_chain_donors_enter_a_coordination_shell():
    """Water beside a metal is not a ligand of the protein's making."""
    structure = build([
        ("S", "SG", "CYS", 10, "A", (0.0, 0.0, 0.0)),
        ("S", "SG", "CYS", 20, "A", (4.6, 0.0, 0.0)),
        ("O", "O", "HOH", 900, "A", (2.3, 2.0, 0.0)),
        ("N", "N", "ALA", 30, "A", (2.3, -2.0, 0.0)),
        ("Zn", "ZN", "ZN", 301, "A", (2.3, 0.0, 0.0)),
    ])
    donors = next(iter(tp.coordination_shell(structure).values()))[1]
    assert [name for _, name, _ in donors] == ["CYS10:SG", "CYS20:SG"]


def test_a_ligand_does_not_shift_the_polymer_positions():
    """Positions count polymer residues; a bound ligand is not one of them."""
    structure = build([
        ("N", "N", "ALA", 1, "A", (0.0, 0.0, 0.0)),
        ("C", "C1", "GOL", 900, "A", (10.0, 0.0, 0.0)),
        ("N", "N", "GLY", 2, "A", (3.8, 0.0, 0.0)),
    ])
    positions = tp.protein_residue_positions(structure)
    assert sorted(positions.values()) == [1, 2]
    assert positions[2] == 2, "the glycine is the second polymer residue, not the third"
