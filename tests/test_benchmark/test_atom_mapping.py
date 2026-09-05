"""Chemical correspondence must not depend on labels or reward altered chemistry."""

from types import SimpleNamespace as NS
import json
import os
from pathlib import Path

import numpy as np
import pytest

pytest.importorskip("rdkit")
pytest.importorskip("networkx")
from rdkit import Chem
from rdkit.Chem import AllChem

from mddatabench import atom_mapping as am, composition as cp, topology as tp


def molecule(smiles, reverse=False):
    mol = Chem.AddHs(Chem.MolFromSmiles(smiles))
    assert AllChem.EmbedMolecule(mol, randomSeed=73) == 0
    if reverse:
        mol = Chem.RenumberAtoms(mol, list(reversed(range(mol.GetNumAtoms()))))
    residue = NS(name="LIG", chain="B", number=7, insertion_code="", atoms=[])
    atoms = [NS(idx=a.GetIdx(), name=f"X{a.GetIdx()}", atomic_number=a.GetAtomicNum(),
                charge=a.GetFormalCharge(), mass=a.GetMass(), residue=residue)
             for a in mol.GetAtoms()]
    residue.atoms = atoms
    bonds = [frozenset((b.GetBeginAtomIdx(), b.GetEndAtomIdx())) for b in mol.GetBonds()]
    structure = NS(atoms=atoms, residues=[residue], coordinates=mol.GetConformer().GetPositions(),
                   bonds=[NS(atom1=atoms[min(b)], atom2=atoms[max(b)]) for b in bonds])
    return structure, bonds


def correspondence(ref, sub, bonds, indices, smiles, submitted_key=("B", "7")):
    left, right = cp.Residue("LIG", "B", "7"), cp.Residue("LIG", *submitted_key)
    def rows(st, key):
        return [(*key, a.name) for a in st.atoms]
    return cp.contract_correspondence(indices, rows(ref, ("B", "7")), rows(sub, submitted_key), [([left], [right])],
        {"reference": ref, "submitted": sub, "submitted_bonds": bonds,
         "declarations": [{"residue_name": "LIG", "smiles": smiles}]})


def test_arbitrary_names_atom_order_and_residue_labels_do_not_choose_atoms():
    ref, _ = molecule("CCO")
    sub, bonds = molecule("CCO", reverse=True)
    for a in sub.atoms:
        a.name = f"REN{a.idx}"
    own, missing = correspondence(ref, sub, bonds, [0, 1, 2], "CCO", submitted_key=("Z", "999"))
    assert not missing
    assert own == [len(sub.atoms)-1-i for i in (0, 1, 2)]
    # The same coordinate observable must be invariant under the permutation.
    np.testing.assert_allclose(ref.coordinates[[0, 1, 2]], sub.coordinates[own])
    from mddatabench import dynamics

    rng = np.random.default_rng(11)
    xyz = ref.coordinates[None, :, :] + rng.normal(0, 0.1, (30, len(ref.atoms), 3))
    reordered = xyz[:, ::-1, :]
    for observable in (dynamics.atom_fluctuations, dynamics.total_fluctuation,
                       dynamics.radius_of_gyration):
        np.testing.assert_allclose(observable(xyz[:, :3, :]), observable(reordered[:, own, :]))


def test_matching_names_are_not_trusted():
    ref, _ = molecule("CCO")
    sub, bonds = molecule("CCO", reverse=True)
    own, missing = correspondence(ref, sub, bonds, [0, 1, 2], "CCO")
    assert not missing and own != [0, 1, 2]


def test_topology_residue_partition_does_not_define_component_membership():
    ref, _ = molecule("CCO")
    sub, bonds = molecule("CCO")
    ref.atoms[0].residue = NS(name="LIG", number=999, atoms=[ref.atoms[0]])
    sub.atoms[1].residue = NS(name="LIG", number=111, atoms=[sub.atoms[1]])
    own, missing = correspondence(ref, sub, bonds, [0, 1, 2], "CCO")
    assert not missing and own == [0, 1, 2]


def test_missing_stereochemical_intent_is_not_guessed():
    ref, _ = molecule("C[C@H](N)C(=O)O")
    sub, bonds = molecule("C[C@H](N)C(=O)O")
    own, missing = correspondence(ref, sub, bonds, [1], "CC(N)C(=O)O")
    assert not own and "incomplete" in missing[0]


@pytest.mark.parametrize("expected,wrong", [("CC=O", "C=CO"), ("C/C=C/C", "C/C=C\\C")])
def test_same_connectivity_different_chemical_state_is_rejected(expected, wrong):
    ref, _ = molecule(expected)
    sub, bonds = molecule(wrong)
    own, missing = correspondence(ref, sub, bonds, [0], expected)
    assert not own and missing


@pytest.mark.parametrize("wrong", ["COC", "CCCO", "C[C@@H](N)C(=O)O"])
def test_isomer_extra_atoms_and_wrong_stereoisomer_are_rejected(wrong):
    smiles = "C[C@H](N)C(=O)O" if "@" in wrong else "CCO"
    ref, _ = molecule(smiles)
    sub, bonds = molecule(wrong)
    own, missing = correspondence(ref, sub, bonds, [0], smiles)
    assert not own and missing


@pytest.mark.parametrize("damage", ["bond_missing", "bond_extra", "charge", "element", "external"])
def test_incomplete_or_inconsistent_evidence_is_not_rescued_by_names(damage):
    ref, _ = molecule("CCO")
    sub, bonds = molecule("CCO")
    if damage == "bond_missing":
        bonds.remove(frozenset((0, 1)))
    elif damage == "bond_extra":
        bonds.append(frozenset((0, 2)))
    elif damage == "charge":
        sub.atoms[0].charge += 1
    elif damage == "element":
        sub.atoms[0].atomic_number = 0
    else:
        bonds.append(frozenset((0, 999)))
    own, missing = correspondence(ref, sub, bonds, [0], "CCO")
    assert not own and missing


def test_symmetry_is_allowed_only_when_target_atom_is_invariant():
    smiles = "Oc1ccccc1"
    ref, _ = molecule(smiles)
    sub, bonds = molecule(smiles)
    own, missing = correspondence(ref, sub, bonds, [0, 2], smiles)
    assert own == [0]
    assert len(missing) == 1 and "symmetry" in missing[0]


def test_search_limit_and_missing_smiles_fail_closed(monkeypatch):
    ref, _ = molecule("CCO")
    sub, bonds = molecule("CCO")
    monkeypatch.setattr(am, "MAX_MAPPINGS", 0)
    own, missing = correspondence(ref, sub, bonds, [0], "CCO")
    assert not own and "limit" in missing[0]
    own, missing = correspondence(ref, sub, bonds, [0], None)
    assert not own and "SMILES" in missing[0]


def test_reference_elements_require_explicit_pdb_and_mass_agreement(tmp_path):
    pdb = tmp_path / "reference.pdb"
    pdb.write_text("ATOM      1  CA  LIG B   7       0.000   0.000   0.000  1.00  0.00           C\n")
    atom = NS(idx=0, atomic_number=20, mass=12.01)
    tp.verify_reference_elements(NS(atoms=[atom]), pdb)
    assert atom.atomic_number == 6  # Not calcium inferred from CA.
    atom.atomic_number, atom.mass = 20, 40.078
    with pytest.raises(ValueError, match="conflicts"):
        tp.verify_reference_elements(NS(atoms=[atom]), pdb)


def test_blank_pdb_element_requires_topology_element_mass_agreement(tmp_path):
    pdb = tmp_path / "reference.pdb"
    pdb.write_text("ATOM      1  CA  LIG B   7       0.000   0.000   0.000  1.00  0.00\n")
    atom = NS(idx=0, atomic_number=6, mass=12.01)
    tp.verify_reference_elements(NS(atoms=[atom]), pdb)
    assert atom.atomic_number == 6
    for number in (0, 20):
        atom.atomic_number = number
        with pytest.raises(ValueError, match="corroborated"):
            tp.verify_reference_elements(NS(atoms=[atom]), pdb)


def test_cached_042_reference_has_unambiguous_scored_ligand_atoms():
    """Reference-only regression, not a rescore of any solver trajectory."""
    bundle_root = os.environ.get("MDDATABENCH_BUNDLE_ROOT")
    if not bundle_root:
        pytest.skip("requires the existing evaluator reference cache")
    bundle = Path(bundle_root) / "cin_A000J"
    if not (bundle / "reference.tpr").is_file():
        pytest.skip("042 reference is not cached")
    task_file = Path(__file__).resolve().parents[2] / "benchmarks/mddatabench/tasks/042_ligand_4mn3/task.json"
    spec = json.loads(task_file.read_text())["reference"]
    structure = tp.load_reference(bundle / "reference.tpr", bundle / "reference.pdb")
    from mddatabench.scoring import pdb_atoms

    rows = pdb_atoms(bundle / "reference.pdb")
    atoms = [a for a, row in zip(structure.atoms, rows) if row[:2] == ("B", "58")]
    bonds = [frozenset((b.atom1.idx, b.atom2.idx)) for b in structure.bonds]
    maps = am.template_maps(structure, bonds, atoms, spec["extra_components"][0]["smiles"])
    assert len(maps) > 1  # Symmetry elsewhere must not make these three ambiguous.
    indices = json.loads((bundle / "pca_atom_indices.json").read_text())["atom_indices"]
    targets = [i for i in indices if rows[i][:2] == ("B", "58")]
    assert len(targets) == 3
    for target in targets:
        assert len({k for m in maps for k, v in m.items() if v == target}) == 1
