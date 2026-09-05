"""Evaluator-owned chemical correspondence for non-polymer contract atoms.

Force-field bonds do not encode chemical bond orders. A declared isomeric
SMILES supplies those; topology connectivity, attached H, net charge and 3D
stereochemistry must independently satisfy it. Names never select a mapping.
"""

from itertools import islice

import numpy as np


MAX_MAPPINGS = 4096


def template_maps(structure, bonds, component_atoms, smiles):
    """All chemically admissible template-heavy-index -> topology-index maps.

    Reject incomplete/externally bonded components and bounded-search overflow;
    never take an arbitrary first symmetry match. No distance-based bond guessing.
    """
    import networkx as nx
    from rdkit import Chem

    template = Chem.MolFromSmiles(smiles)
    if template is None or len(Chem.GetMolFrags(template)) != 1:
        raise ValueError("one connected, valid declared SMILES is required")
    template = Chem.RemoveHs(template)
    if any(tag == "?" for _, tag in Chem.FindMolChiralCenters(
            template, includeUnassigned=True, useLegacyImplementation=False)):
        raise ValueError("declared ligand stereochemistry is incomplete")
    atoms = list(component_atoms)
    if len(atoms) != Chem.AddHs(template).GetNumAtoms():
        raise ValueError("component atom inventory differs from declared SMILES")
    ids = {a.idx for a in atoms}
    adjacent = {i: set() for i in ids}
    for edge in bonds:
        a, b = tuple(edge)
        if (a in ids) != (b in ids):
            raise ValueError("ligand has a covalent bond outside its component")
        if a in ids:
            adjacent[a].add(b)
            adjacent[b].add(a)
    charge = sum(a.charge for a in atoms)
    if not np.isfinite(charge) or abs(charge - Chem.GetFormalCharge(template)) > 0.01:
        raise ValueError("component net charge differs from declared SMILES")
    graph = nx.Graph()
    for atom in atoms:
        if atom.atomic_number <= 0:
            raise ValueError("component has an unknown element")
        if atom.atomic_number == 1:
            if (len(adjacent[atom.idx]) != 1 or
                    structure.atoms[next(iter(adjacent[atom.idx]))].atomic_number == 1):
                raise ValueError("component hydrogen is missing a unique bond")
        else:
            graph.add_node(atom.idx, element=atom.atomic_number,
                           h=sum(structure.atoms[i].atomic_number == 1
                                 for i in adjacent[atom.idx]))
    for a in graph:
        for b in adjacent[a]:
            if b in graph:
                graph.add_edge(a, b)
    wanted = nx.Graph()
    for atom in template.GetAtoms():
        wanted.add_node(atom.GetIdx(), element=atom.GetAtomicNum(), h=atom.GetTotalNumHs())
    wanted.add_edges_from((b.GetBeginAtomIdx(), b.GetEndAtomIdx()) for b in template.GetBonds())
    if len(graph) != len(wanted) or graph.number_of_edges() != wanted.number_of_edges():
        raise ValueError("component atom/bond inventory differs from declared SMILES")
    candidates = nx.isomorphism.GraphMatcher(
        wanted, graph, node_match=lambda a, b: a == b).isomorphisms_iter()
    expected = Chem.MolToSmiles(template, isomericSmiles=True)
    coordinates = np.asarray(structure.coordinates, dtype=float)
    valid = []
    for count, mapping in enumerate(islice(candidates, MAX_MAPPINGS + 1)):
        if count == MAX_MAPPINGS:
            raise ValueError("chemical correspondence search limit exceeded")
        mol = Chem.Mol(template)
        conformer = Chem.Conformer(mol.GetNumAtoms())
        for i, j in mapping.items():
            xyz = coordinates[j]
            if not np.isfinite(xyz).all():
                raise ValueError("component coordinates are not finite")
            conformer.SetAtomPosition(i, xyz)
        mol.RemoveAllConformers()
        mol.AddConformer(conformer)
        Chem.RemoveStereochemistry(mol)
        Chem.AssignStereochemistryFrom3D(mol)
        if Chem.MolToSmiles(mol, isomericSmiles=True) == expected:
            valid.append(mapping)
    if not valid:
        raise ValueError("component connectivity, hydrogenation or stereochemistry differs from SMILES")
    return valid


def ligand_correspondence(indices, reference_rows, submitted_rows, pairs, reference, submitted,
                          submitted_bonds, declarations):
    """Return (index overrides, blocked indices), including same-name ligands."""
    from .topology import POLYMER_RESIDUES

    overrides, blocked = {}, {}
    reference_bonds = [frozenset((b.atom1.idx, b.atom2.idx)) for b in reference.bonds]
    for left, right in pairs:
        for ref_residue, sub_residue in zip(left, right):
            if ref_residue.canonical in POLYMER_RESIDUES:
                continue
            targets = [i for i in indices if reference_rows[i][:2]
                       == (ref_residue.chain, ref_residue.resseq)]
            if not targets:
                continue
            try:
                if submitted is None or submitted_bonds is None:
                    raise ValueError("submitted ligand topology is unavailable")
                specs = [d for d in declarations if d.get("residue_name") == ref_residue.name]
                if len(specs) != 1 or not specs[0].get("smiles"):
                    raise ValueError("non-polymer contract atoms require one declared SMILES")
                # PDB and TPR can partition the same atoms differently (042's
                # one PDB LIG is 1+101 atoms in two TPR residues). Membership
                # comes from the paired coordinate components; bonds do not.
                rr = [reference.atoms[i] for i, row in enumerate(reference_rows)
                      if row[:2] == (ref_residue.chain, ref_residue.resseq)]
                own_indices = [i for i, row in enumerate(submitted_rows)
                               if row[:2] == (sub_residue.chain, sub_residue.resseq)]
                if not own_indices or max(own_indices) >= len(submitted.atoms):
                    raise ValueError("submitted component atom inventory is inconsistent")
                sr = [submitted.atoms[i] for i in own_indices]
                for atom in sr:
                    if submitted_rows[atom.idx][2] != atom.name:
                        raise ValueError("submitted topology and coordinate atom order/labels disagree")
                ref_maps = template_maps(reference, reference_bonds, rr, specs[0]["smiles"])
                sub_maps = template_maps(submitted, submitted_bonds, sr, specs[0]["smiles"])
                for i in targets:
                    template_indices = {k for m in ref_maps for k, v in m.items() if v == i}
                    choices = {m[k] for m in sub_maps for k in template_indices}
                    if len(choices) != 1:
                        blocked[i] = "chemical symmetry leaves this contract atom ambiguous"
                    else:
                        overrides[i] = choices.pop()
            except (ValueError, ImportError) as exc:
                blocked.update({i: str(exc) for i in targets})
    return overrides, blocked
