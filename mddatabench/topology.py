"""Read what a topology actually says, on both sides, instead of inferring it.

Until 2026-08-22 the prep checks read chemistry out of text: disulfides from
CONECT columns of the submitted PDB, protonation from residue names, the
expected bonding from the reference's CYX labels plus an SG-SG distance.  Two
better sources were available the whole time.

The submission ships ``system.xml``, which is the thing that exerts force.  A
CONECT record is metadata and can disagree with it; the bond that moved D01's
two zinc-ligating sulfurs from 3.00 to 2.04 A was a HarmonicBondForce term.

The reference ships a topology, but not always the same one.  MDDB is eight
federated nodes and they deposit different formats: Amber ``topology.prmtop``
on mmb, cin and rpbs, GROMACS ``topology.tpr`` on bsc, oxf and inr, CHARMM
``topology.psf`` on part of inr.  Whichever arrives states the bond list, the
residue names and the atom types outright, so nothing has to be guessed:

    MCV1900208  4862 atoms, 313 residues, net charge -2.0
                CYM 3, HIP 1, HIE 10, CYS 5, no S-S bond
                ZN  type Zn2+, charge +2.0, rmin 1.271 A, zero bonds

That last line is the one worth keeping in view.  The reference holds its
structural zinc with a bare 12-6 ion carrying the same parameters our own
submissions build, so the difference between 2 of 4 ligands retained and 1 of 4
is protonation, not force field.
"""

from __future__ import annotations

from mddatabench import _threads  # noqa: F401  must precede numpy

import collections

import numpy as np

# Metals whose sulfur or nitrogen coordination shapes the protonation a
# preparation has to choose.  Same set MDClaw guards its disulfide detection
# with, for the same reason.
METAL_ELEMENTS = frozenset({
    "ZN", "FE", "CU", "NI", "CO", "MN", "CD", "HG", "PT", "AU", "AG", "MO", "W",
    "MG", "CA",
})

# Longest metal-ligand separation that still counts as coordination.  Zn-S is
# 2.3 A; measured across 6W9C's three copies the same Cys4 site runs 2.19 to
# 3.21 A, so a tighter limit splits one site into coordinated and not.
METAL_LIGAND_ANGSTROM = 3.5

# Which side-chain atoms can donate to a metal, by residue.  Selecting on
# "any S, N or O that is not a backbone atom" instead lets a water, a hydroxide
# or a ligand atom into the coordination shell, and the carve-out then exempts
# residues whose protonation had nothing to do with the metal.
SIDECHAIN_DONORS = {
    "CYS": ("SG",), "CYM": ("SG",), "CYX": ("SG",),
    "HIS": ("ND1", "NE2"), "HID": ("ND1", "NE2"), "HIE": ("ND1", "NE2"),
    "HIP": ("ND1", "NE2"), "HSD": ("ND1", "NE2"), "HSE": ("ND1", "NE2"),
    "HSP": ("ND1", "NE2"),
    "ASP": ("OD1", "OD2"), "ASH": ("OD1", "OD2"),
    "GLU": ("OE1", "OE2"), "GLH": ("OE1", "OE2"),
    "MET": ("SD",), "SER": ("OG",), "THR": ("OG1",), "TYR": ("OH",),
    "ASN": ("OD1",), "GLN": ("OE1",), "LYS": ("NZ",), "LYN": ("NZ",),
}


def _donor_atoms(residue):
    """The side-chain atoms of this residue that can ligate a metal."""
    names = SIDECHAIN_DONORS.get(residue.name.strip().upper())
    if not names:
        return ()
    return tuple(atom for atom in residue.atoms if atom.name in names)


# Topology formats MDDB nodes deposit, in the order a bundle is searched.
# ``.prmtop`` first only because it is the most common; nothing else depends on
# the order.
REFERENCE_TOPOLOGIES = (".prmtop", ".parm7", ".tpr", ".psf", ".top")


def find_reference_topology(bundle):
    """The reference topology in this bundle, whatever format the node served.

    Returns the path.  Raises if the bundle has none, because every prep
    comparison -- residue composition, elements, disulfide bonds -- is read from
    it, and silently scoring without one would report agreement that was never
    checked.
    """
    for suffix in REFERENCE_TOPOLOGIES:
        candidate = bundle / f"reference{suffix}"
        if candidate.exists():
            return candidate
    raise SystemExit(
        f"{bundle} carries no reference topology; expected one of "
        + ", ".join(f"reference{s}" for s in REFERENCE_TOPOLOGIES))


def read_topology(path):
    """One topology file, as a ParmEd structure with bonds, charges and elements.

    ParmEd reads Amber prmtop, CHARMM psf and GROMACS top.  It cannot read a
    ``.tpr``: that is GROMACS's binary run input, not a text topology.
    MDAnalysis can, and converting its universe gives the same ParmEd structure
    the rest of this module already consumes -- verified on ATLAS 16pk_A, where
    the tpr yields 6378 atoms, 6429 bonds, per-atom charges and elements, and
    agrees with the bundle's own reference.pdb on every atom and residue name.
    """
    import parmed
    suffix = path.suffix.lower()
    if suffix == ".tpr":
        import MDAnalysis
        return MDAnalysis.Universe(str(path)).atoms.convert_to("PARMED")
    if suffix in REFERENCE_TOPOLOGIES:
        return parmed.load_file(str(path))
    raise SystemExit(f"{path.name}: unsupported topology format")


def _reference_atom_names_match(topology_atom, coordinate_atom):
    """Whether two names identify the same atom at this residue position.

    Amber writes methyl hydrogens as ``HG21`` while the older PDB convention
    writes the same atom as ``1HG2``.  Accept only that exact leading-to-trailing
    digit move, for a topology atom known to be hydrogen and at the same residue;
    broader name normalisation would weaken the atom-order guard this serves.
    """
    if topology_atom.name == coordinate_atom.name:
        return True
    pdb_name = coordinate_atom.name
    return (
        topology_atom.atomic_number == 1
        and pdb_name[:1] in "123"
        and pdb_name[1:] + pdb_name[0] == topology_atom.name
        and topology_atom.residue.idx == coordinate_atom.residue.idx
        and topology_atom.residue.name == coordinate_atom.residue.name
    )


def load_reference(topology_path, pdb_path):
    """The reference's own topology, carrying its structure's coordinates.

    The two files are separate downloads and nothing in the format ties them
    together, so the correspondence is checked rather than assumed: transplanting
    coordinates onto a topology whose atoms are in a different order would put a
    metal on the wrong residue and be visible nowhere in the report.  Verified
    2026-08-22 across all three PLpro references -- 4897/4897/4862 atoms, no
    atom-name and no residue-name mismatch -- and 2026-08-23 on an ATLAS tpr.
    """
    import parmed
    structure = read_topology(topology_path)
    coordinates = parmed.load_file(str(pdb_path))
    if len(coordinates.atoms) != len(structure.atoms):
        raise SystemExit(
            f"{topology_path.name} has {len(structure.atoms)} atoms and "
            f"{pdb_path.name} has {len(coordinates.atoms)}; the bundle is inconsistent")
    mismatched = [
        i
        for i, (a, b) in enumerate(zip(structure.atoms, coordinates.atoms))
        if not _reference_atom_names_match(a, b)
    ]
    if mismatched:
        raise SystemExit(
            f"{topology_path.name} and {pdb_path.name} disagree on atom order at "
            f"{len(mismatched)} position(s), first at index {mismatched[0]}")
    # The atom check above says nothing about bonds, and every prep expectation
    # that is a bond -- the disulfide set, the valence limits, the metal-bridge
    # test -- is read from this list.  A conversion that dropped it would shrink
    # the reference's expected set silently, so a submission missing a disulfide
    # would score as agreement with nothing in the report to show it.  Refuse a
    # polymer topology that declares no bonds at all.  Measured 2026-08-23 on
    # crambin 1AB1 from a GROMACS tpr: 639 atoms, 648 bonds, and the three
    # disulfides Cys3-Cys40, Cys4-Cys32, Cys16-Cys26 all present.
    polymer = sum(1 for residue in structure.residues
                  if residue.name.strip().upper() in POLYMER_RESIDUES)
    if polymer and not structure.bonds:
        raise SystemExit(
            f"{topology_path.name} declares {polymer} polymer residue(s) and no "
            "bonds; the bond list was lost in reading it")
    structure.coordinates = coordinates.coordinates
    return structure


def load_submission(system_xml_path, topology_pdb_path):
    """The submitted System, as a structure with bonds, charges and coordinates.

    Bonds come from the OpenMM topology; the System supplies the parameters.
    Reading it here rather than parsing CONECT also removes the PDB serial
    problem entirely -- past 99999 the column is hybrid-36 and 64544 of a 141k
    atom topology's CONECT records hold no decimal field at all.

    Returns (structure, force-bearing bonds, error_message, system).  The System
    is handed back because the scorer's force-field checks want it and it is
    already deserialised here; it is returned even when the topology PDB is
    unreadable, so those checks stay independent of this one.  It must not raise:
    this runs before the
    check that reports an unloadable System, so a truncated or empty file used to
    crash the scorer here instead of being scored as a failed submission.
    """
    import openmm as mm
    import parmed
    from openmm.app import PDBFile
    system = None
    try:
        system = mm.XmlSerializer.deserialize(open(system_xml_path).read())
        pdb = PDBFile(str(topology_pdb_path))
        structure = parmed.openmm.load_topology(pdb.topology, system,
                                                xyz=pdb.positions)
    except Exception as exc:                                        # noqa: BLE001
        return None, None, (f"the submitted topology could not be read: "
                            f"{type(exc).__name__}: {exc}"), system
    return structure, force_bearing_bonds(system, structure), None, system



# Polymer residues, named positively.  Positions used to be "everything that is
# not a metal and not solvent", which counts a bound ligand as a residue of the
# chain: one GOL in the submission and not in the reference shifts every later
# position by one and makes two identical bond sets compare unequal.  The
# variants are here because a topology names them: CYM, CYX, HID/HIE/HIP, ASH,
# GLH, LYN, and the 5' / 3' nucleic forms.
PROTEIN_RESIDUES = frozenset({
    "ALA", "ARG", "ASN", "ASP", "CYS", "GLN", "GLU", "GLY", "HIS", "ILE", "LEU",
    "LYS", "MET", "PHE", "PRO", "SER", "THR", "TRP", "TYR", "VAL",
    "CYM", "CYX", "HID", "HIE", "HIP", "HSD", "HSE", "HSP", "ASH", "GLH", "LYN",
    "ARN", "TYM", "ACE", "NME", "NHE", "NMA",
})
NUCLEIC_RESIDUES = frozenset(
    [base + suffix for base in ("DA", "DC", "DG", "DT", "DU", "A", "C", "G", "U")
     for suffix in ("", "5", "3", "N")]
)
POLYMER_RESIDUES = PROTEIN_RESIDUES | NUCLEIC_RESIDUES

# Between the longest bond constrained over a hydrogen and a heavy atom (H-S,
# 1.34 A) and the shortest angle constrained over the same (C...H, 1.94 A).
# Hydrogen-hydrogen pairs are settled by element, not by this: OPC water's H-H
# is 1.37 A and would fall on the bonded side of any threshold that keeps H-S.
CONSTRAINED_ANGLE_ANGSTROM = 1.45


def force_bearing_bonds(system, structure):
    """Atom-index pairs the System actually constrains or bonds.

    ``parmed.openmm.load_topology`` takes its bond list from the OpenMM topology,
    which is CONECT plus template inference -- so a structure's ``bonds`` are the
    PDB's connectivity, not the force field's.  The two can disagree in both
    directions: a bond only in ``system.xml`` is invisible to a CONECT-derived
    list, and a CONECT record with no force term behind it looks like a bond.
    The claim these checks rest on is about what exerts force, so read it from
    the System: HarmonicBondForce for the bonds that keep a potential, and the
    constraint list for the ones that were turned rigid (with HBonds and rigid
    water, that is most of them -- 21451 constraints against 177 bond terms in
    one measured task).
    """
    import openmm as mm
    from openmm import unit
    pairs, constrained = set(), []
    for force in system.getForces():
        if isinstance(force, mm.HarmonicBondForce):
            for index in range(force.getNumBonds()):
                one, two, _, _ = force.getBondParameters(index)
                pairs.add(frozenset((one, two)))
    for index in range(system.getNumConstraints()):
        one, two, length = system.getConstraintParameters(index)
        constrained.append((one, two, length.value_in_unit(unit.angstrom)))
    # A constraint is not always a bond.  A rigid water fixes all three sides of
    # its triangle -- O-H, O-H and H-H -- so the angle arrives as a distance,
    # and `constraints=HAngles` does the same for every H-X-H and H-X-Y angle in
    # the solute.  Counting those as bonds gives hydrogens a second partner and
    # heavy atoms a fifth: measured, 47478 atoms of the 5ZK8 membrane system
    # read as over their valence, and 119 of a 3263-atom protein under HAngles.
    #
    # Only angles involving hydrogen are ever constrained, so a pair with no
    # hydrogen in it is always a bond -- C-C, C-S and S-S reach 2.04 A and no
    # scheme constrains a heavy-atom angle.  Two tests cover the rest:
    #
    #  * Both ends hydrogen -> an angle.  No biomolecular force field bonds two
    #    hydrogens, and this is how every rigid water spells its H-O-H.  It has
    #    to be the element test rather than a length: OPC's H-H is 1.37 A and a
    #    real H-S bond is 1.34, so no threshold separates them.  Measured across
    #    tip3p, spce, tip4pew, tip5p, opc, opc3, tip3p-fb and tip4p-fb.
    #  * One end hydrogen -> a bond if short.  `constraints=HAngles` fixes the
    #    H-X-Y angle as an X...Y distance, which for a hydrogen and a heavy atom
    #    is far longer than their bond.  Measured on a 3263-atom protein under
    #    HAngles: bonded H-O 0.96, H-N 1.01, C-H 1.08-1.09, H-S 1.34 (longest);
    #    angle C...H 1.94-1.95 (shortest).  119 atoms read as over their valence
    #    without this and none with it.
    hydrogen = {atom.idx for atom in structure.atoms
                if atom.element_name in ("H", "D")}
    for one, two, length in constrained:
        ends = (one in hydrogen, two in hydrogen)
        if all(ends):
            continue
        if any(ends) and length >= CONSTRAINED_ANGLE_ANGSTROM:
            continue
        pairs.add(frozenset((one, two)))
    return pairs


def backbone_links(structure, bonds=None):
    """Declared inter-residue peptide and phosphodiester links.

    ``bonds`` follows the same rule as the chemistry checks below: a submission
    passes the force-bearing pairs extracted from its System, while a reference
    passes ``None`` and therefore uses the bonds in its deposited topology.  A
    short C--N contact is deliberately not evidence here; the five membrane
    submissions measured on 2026-08-28 contain real, unwanted peptide terms,
    while other close fragment ends do not.

    The returned dictionaries are small and JSON-serialisable so the evaluator
    can retain the scientific evidence after the much larger System XML is
    reclaimed.
    """
    atoms = structure.atoms
    if bonds is None:
        bonds = {frozenset((bond.atom1.idx, bond.atom2.idx))
                 for bond in structure.bonds}
    links = []
    for pair in bonds:
        if len(pair) != 2:
            continue
        one, two = (atoms[index] for index in sorted(pair))
        if one.residue.idx == two.residue.idx:
            continue
        one_name = one.residue.name.strip().upper()
        two_name = two.residue.name.strip().upper()
        oriented = None
        if one_name in PROTEIN_RESIDUES and two_name in PROTEIN_RESIDUES:
            if one.name == "C" and two.name == "N":
                oriented = (one, two, "peptide")
            elif two.name == "C" and one.name == "N":
                oriented = (two, one, "peptide")
        elif one_name in NUCLEIC_RESIDUES and two_name in NUCLEIC_RESIDUES:
            if one.name in ("O3'", "O3*") and two.name == "P":
                oriented = (one, two, "phosphodiester")
            elif two.name in ("O3'", "O3*") and one.name == "P":
                oriented = (two, one, "phosphodiester")
        if oriented is None:
            continue
        tail, head, kind = oriented
        links.append({
            "kind": kind,
            "atom_indices": [int(tail.idx), int(head.idx)],
            "atom_names": [tail.name, head.name],
            "residue_indices": [int(tail.residue.idx), int(head.residue.idx)],
            "residue_names": [tail.residue.name, head.residue.name],
            "residue_numbers": [int(tail.residue.number), int(head.residue.number)],
            "chains": [tail.residue.chain or "", head.residue.chain or ""],
        })
    return sorted(links, key=lambda link: (
        link["residue_indices"], link["atom_indices"]))


def sulfur_bonds(structure, bonds=None):
    """Every S-S bond, as a set of residue-index pairs.  Zero is a real answer.

    ``bonds`` is a set of atom-index pairs; when given it replaces the
    structure's own connectivity, which is how a submission is read from the
    force field rather than from CONECT.  A reference prmtop has no separate
    force list -- its bonds are the force field -- so it passes None.
    """
    atoms = structure.atoms
    if bonds is None:
        bonds = {frozenset((bond.atom1.idx, bond.atom2.idx))
                 for bond in structure.bonds}
    pairs = set()
    for bond in bonds:
        one, two = sorted(bond)
        if atoms[one].element_name == "S" and atoms[two].element_name == "S":
            pairs.add(frozenset((atoms[one].residue.idx, atoms[two].residue.idx)))
    return pairs


def metal_atoms(structure):
    """(atom index, residue index, label, position) for every metal ion."""
    out = []
    for residue in structure.residues:
        if residue.name.strip().upper() not in METAL_ELEMENTS:
            continue
        for atom in residue.atoms:
            out.append((atom.idx, residue.idx,
                        f"{residue.name}{residue.number}"
                        f"{(residue.insertion_code or '').strip()}"
                        f"{('/' + residue.chain) if residue.chain else ''}",
                        np.array([atom.xx, atom.xy, atom.xz])))
    return out


def duplicate_atom_names(structure):
    """Residues carrying the same atom name twice, as (label, [names]).

    An atom name never repeats inside a residue, so a repeat means a rebuild
    added hydrogens on top of hydrogens that were already there.
    """
    out = []
    for residue in structure.residues:
        names = [atom.name for atom in residue.atoms]
        repeated = sorted({n for n in names if names.count(n) > 1})
        if repeated:
            out.append((f"{residue.name}{residue.number}", repeated))
    return out


def valence_problems(structure, bonds=None):
    """Atoms carrying more bonds than the element can hold.

    ``bonds`` is a set of atom-index pairs and follows the same contract as
    :func:`sulfur_bonds`: a submission passes what the System exerts, and a
    reference prmtop passes None because its own bonds are the force field.
    Reading a submission's ``structure.bonds`` instead measures CONECT, which
    a PDB cannot address past 493215 serials -- a 381954-atom topology with a
    TER after every water consumes 506032, and OpenMM's writer then wraps them
    onto the low decimal range.  Measured on 1AHW: 2245 serials named two atoms
    each, and the CONECT records that resolved through them put 84 atoms over
    their valence, joining protein to water up to 135 A away.  The System
    indexes atoms by position and cannot alias.
    """
    # Only limits nothing legitimate exceeds.  Sulfur is not among them: a
    # sulfonamide, a sulfate and DMSO all carry four bonds on S, so the earlier
    # limit of 2 would have failed a correct system for being correct.
    limits = {"H": 1, "O": 2, "N": 4, "C": 4}
    if bonds is None:
        bonds = {frozenset((bond.atom1.idx, bond.atom2.idx))
                 for bond in structure.bonds}
    degree = collections.Counter()
    for bond in bonds:
        one, two = tuple(bond)
        degree[one] += 1
        degree[two] += 1
    out = []
    for atom in structure.atoms:
        limit = limits.get(atom.element_name)
        if limit is not None and degree[atom.idx] > limit:
            out.append((f"{atom.residue.name}{atom.residue.number}:{atom.name}",
                        atom.element_name, degree[atom.idx], limit))
    return out


def protein_residue_positions(structure):
    """{residue index: 1-based position among polymer residues}."""
    positions, count = {}, 0
    for residue in structure.residues:
        if residue.name.strip().upper() not in POLYMER_RESIDUES:
            continue
        count += 1
        positions[residue.idx] = count
    return positions


def sulfur_bond_positions(structure, bonds=None):
    """S-S bonds as pairs of 1-based polymer positions, plus what was dropped.

    Residue numbering is not comparable -- a reference numbers from 1 and a
    submission carries author numbering -- but position within the polymer is.
    That frame is re-derived on each side independently, so it only lines up
    while the two sides contain the same polymer residues: a terminal cap on one
    side shifts every later position by one and makes two identical bond sets
    compare unequal.  The caller is handed the residue count so it can say that
    rather than blaming the bonds.

    Returns (pairs, polymer_residue_count, dropped), where ``dropped`` names S-S
    bonds touching a residue outside the polymer -- a modified residue or a
    ligand sulfur -- which are excluded from the comparison and would otherwise
    vanish silently.
    """
    positions = protein_residue_positions(structure)
    pairs, dropped = set(), []
    for pair in sulfur_bonds(structure, bonds):
        mapped = tuple(sorted((positions.get(index) for index in pair),
                              key=lambda value: (value is None, value)))
        if all(value is not None for value in mapped):
            pairs.add(frozenset(mapped))
        else:
            dropped.append("-".join(
                f"{structure.residues[index].name}{structure.residues[index].number}"
                for index in sorted(pair)))
    return pairs, len(positions), sorted(dropped)


def sulfur_bond_monomer_positions(structure, bonds=None):
    """S-S edges as pairs of ``(monomer, position)`` polymer endpoints.

    Monomers are the connected components made by declared peptide and
    phosphodiester bonds, in file order.  Both the monomer index and the
    residue position are zero/one based respectively.  This keeps inter-chain
    disulfides while giving the scorer a frame it can translate through its
    sequence-based monomer correspondence.

    Returns ``(pairs, component_sizes, dropped)``.  ``dropped`` has the same
    meaning as in :func:`sulfur_bond_positions`.
    """
    polymer = [residue for residue in structure.residues
               if residue.name.strip().upper() in POLYMER_RESIDUES]
    parent = {residue.idx: residue.idx for residue in polymer}

    def root(index):
        while parent[index] != index:
            parent[index] = parent[parent[index]]
            index = parent[index]
        return index

    for link in backbone_links(structure, bonds):
        first, second = link["residue_indices"]
        if first not in parent or second not in parent:
            continue
        first_root, second_root = root(first), root(second)
        if first_root != second_root:
            parent[second_root] = first_root

    groups = collections.defaultdict(list)
    for residue in polymer:
        groups[root(residue.idx)].append(residue.idx)
    components = sorted(groups.values(), key=lambda group: group[0])
    endpoint = {
        residue_index: (monomer_index, position)
        for monomer_index, component in enumerate(components)
        for position, residue_index in enumerate(component, start=1)
    }

    pairs, dropped = set(), []
    for pair in sulfur_bonds(structure, bonds):
        mapped = [endpoint.get(index) for index in pair]
        if all(value is not None for value in mapped):
            pairs.add(frozenset(mapped))
        else:
            dropped.append("-".join(
                f"{structure.residues[index].name}{structure.residues[index].number}"
                for index in sorted(pair)))
    return pairs, [len(component) for component in components], sorted(dropped)


def describe_position_pairs(pairs):
    return sorted("-".join(str(x) for x in sorted(pair)) for pair in pairs)


def describe_monomer_position_pairs(pairs):
    """Compact labels for pairs returned by ``sulfur_bond_monomer_positions``."""
    return sorted("--".join(f"M{monomer + 1}:{position}"
                            for monomer, position in sorted(pair))
                  for pair in pairs)


def metal_bridging_bonds(structure, cutoff=METAL_LIGAND_ANGSTROM, bonds=None):
    """Covalent bonds joining two ligands of one metal, as printable labels.

    Two side chains that both reach the same metal are ligands of it, not
    partners of each other, however close their donor atoms happen to be.

    ``bonds`` follows the same contract as :func:`sulfur_bonds` and
    :func:`valence_problems`: what the System exerts, or None for a reference
    whose own bonds are its force field.
    """
    metals = metal_atoms(structure)
    if not metals:
        return []
    atoms = structure.atoms
    if bonds is None:
        bonds = {frozenset((bond.atom1.idx, bond.atom2.idx))
                 for bond in structure.bonds}
    out = []
    for bond in bonds:
        first_index, second_index = tuple(bond)
        one, two = atoms[first_index], atoms[second_index]
        if one.residue.idx == two.residue.idx:
            continue
        if not (_donor_atoms(one.residue) and _donor_atoms(two.residue)):
            continue
        if one not in _donor_atoms(one.residue) or two not in _donor_atoms(two.residue):
            continue
        first = np.array([one.xx, one.xy, one.xz])
        second = np.array([two.xx, two.xy, two.xz])
        for _, _, label, position in metals:
            if (np.linalg.norm(first - position) <= cutoff
                    and np.linalg.norm(second - position) <= cutoff):
                out.append(f"{one.residue.name}{one.residue.number}:{one.name}-"
                           f"{two.residue.name}{two.residue.number}:{two.name} "
                           f"bridging {label}")
                break
    return out


def coordination_shell(structure, cutoff=METAL_LIGAND_ANGSTROM):
    """{metal label: [(atom index, residue label, distance)]} for side-chain donors."""
    shells = {}
    for metal_atom, metal_index, label, position in metal_atoms(structure):
        donors = []
        for residue in structure.residues:
            if residue.idx == metal_index:
                continue
            for atom in _donor_atoms(residue):
                distance = float(np.linalg.norm(
                    np.array([atom.xx, atom.xy, atom.xz]) - position))
                if distance <= cutoff:
                    donors.append((atom.idx,
                                   f"{residue.name}{residue.number}:{atom.name}",
                                   round(distance, 2)))
        # Keyed by the metal's own atom index, never by its printed label: two
        # copies of a homo-oligomer carry the same residue number, and a
        # label-keyed dict silently drops one whole site.  Reproduced on a
        # two-chain synthetic with ZN301 in each: one of the two shells vanished.
        shells[metal_atom] = (label, sorted(donors, key=lambda d: d[2]))
    return shells
