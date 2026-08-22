"""Compare a submitted system's composition against the MDDB reference.

Everything here works per monomer, not per file.  A monomer is a covalently
connected polymer chain, found from peptide/phosphodiester geometry rather than
from PDB chain IDs: preparation tools relabel and reuse chain IDs (MDClaw's own
``chain_identity_map.json`` says "PDB chain IDs are MD compatibility labels and
may be reused"), and D03's ``system.topology.pdb`` already carries chains A, B
and C where the reference has only A.  Zipping two residue lists in file order
happens to work for a monomer and silently misaligns for anything else.

Monomers are matched by canonical sequence, not by chain ID or by order.  The
canonical sequence collapses every protonation and bonding variant of a residue
onto its parent (HID/HIE/HIP -> HIS, CYX/CYM -> CYS, ASH -> ASP, ...), so
matching never fails because of a protonation choice; the protonation is then
graded inside the matched monomer, where it belongs.

Protonation is graded by ATOM COUNT, never by residue name.  Names are a
convention: the same MDClaw submission writes CYX in ``merged.pdb`` and CYS in
``system.topology.pdb``, GROMACS writes HISD/HISE/HISH and CHARMM HSD/HSE/HSP.
Atom counts are not a convention, and they have exactly the property the task
needs -- measured 2026-08-21 on D01/D02/D03, the reference and the submission
disagree on the histidine tautomer in D01 (HIE vs HID) and D02 (HID vs HIE) and
agree on every per-residue atom count:

    HID <-> HIE          same formula   -> invisible, which is correct: the
                                           tautomer is the agent's free choice
    HIS -> HIP           +1 H           -> detected
    ASP -> ASH, GLU -> GLH  +1 H        -> detected
    LYS -> LYN, CYS -> CYM  -1 H        -> detected
    CYS -> CYX (S-S)     -1 H           -> detected
"""

from __future__ import annotations

from mddatabench import _threads  # noqa: F401  must precede numpy

import collections

import numpy as np

# Every protonation / bonding variant collapsed onto its parent residue.  Used
# only to match monomers to each other; the variants themselves are graded by
# atom count inside the matched monomer.
CANONICAL_RESIDUE = {
    "HID": "HIS", "HIE": "HIS", "HIP": "HIS", "HSD": "HIS", "HSE": "HIS",
    "HSP": "HIS", "HISD": "HIS", "HISE": "HIS", "HISH": "HIS",
    "CYX": "CYS", "CYM": "CYS", "CYS2": "CYS",
    "ASH": "ASP", "ASPP": "ASP", "GLH": "GLU", "GLUP": "GLU",
    "LYN": "LYS", "ARN": "ARG", "TYM": "TYR",
}

SOLVENT_RESIDUES = {
    "HOH", "WAT", "TIP", "TIP3", "TIP4", "SOL", "T3P", "T4P", "OPC",
    "NA", "NA+", "SOD", "CL", "CL-", "CLA", "K", "K+", "POT", "MG", "CA",
    "ZN", "IOD", "BR", "LI", "CS", "RB", "F",
}

# Longest bond that still counts as the polymer link.  A peptide C-N is 1.33 A
# and a phosphodiester O3'-P is 1.60 A; 2.0 A separates them from the 3-4 A gap
# left by a chain break without admitting a non-bonded contact.
POLYMER_LINK_ANGSTROM = 2.0

_HY36_UPPER = "0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZ"
_HY36_LOWER = _HY36_UPPER.lower()


def hy36decode(field, width=5):
    """Read a PDB serial field, decimal or hybrid-36.  None if it is neither.

    Past 99999 the PDB serial column switches to hybrid-36 -- ``A0000`` is
    100000 -- and OpenMM writes it: a 136k-atom ``system.topology.pdb`` has
    64544 CONECT records with no decimal field in them.  Reading those as
    malformed made every disulfide check on a solvated system give up and
    report the topology as unusable, which is how all three tasks failed
    ``disulfide_bonds_match_reference`` on 2026-08-21.
    """
    text = field.strip()
    if not text:
        return None
    try:
        return int(text)
    except ValueError:
        pass
    if len(text) != width:
        return None
    if text[0] in _HY36_UPPER[10:]:
        digits, offset = _HY36_UPPER, -10 * 36 ** (width - 1)
    elif text[0] in _HY36_LOWER[10:]:
        digits, offset = _HY36_LOWER, 16 * 36 ** (width - 1)
    else:
        return None
    value = 0
    for char in text:
        index = digits.find(char)
        if index < 0:
            return None
        value = value * 36 + index
    return value + offset + 10 ** width


class Residue:
    __slots__ = ("name", "chain", "resseq", "atoms")

    def __init__(self, name, chain, resseq):
        self.name = name
        self.chain = chain
        self.resseq = resseq
        self.atoms = []          # (serial, atom_name, element, xyz)

    @property
    def canonical(self):
        return CANONICAL_RESIDUE.get(self.name, self.name)

    @property
    def n_atoms(self):
        return len(self.atoms)

    @property
    def n_heavy(self):
        return sum(1 for a in self.atoms if a[2] != "H")

    def element_counts(self):
        return collections.Counter(a[2] for a in self.atoms if a[2] != "H")

    def atom(self, name):
        for a in self.atoms:
            if a[1] == name:
                return a
        return None

    def label(self):
        return f"{self.name}{self.resseq}"


def read_residues(path, drop_solvent=True):
    """Ordered residues of a PDB, solvent and free ions removed by default."""
    residues = []
    current = None
    for line in open(path):
        if not line.startswith(("ATOM", "HETATM")):
            continue
        name = line[17:20].strip()
        if drop_solvent and name.upper() in SOLVENT_RESIDUES:
            current = None
            continue
        chain, resseq = line[21], line[22:27].strip()
        atom_name = line[12:16].strip()
        # A new residue starts when the (chain, number, name) triple changes, and
        # also when an atom name repeats: two separate components can carry the
        # same label, because preparation tools reuse chain IDs, and an atom name
        # never occurs twice inside one residue.
        if (current is None
                or (current.chain, current.resseq, current.name) != (chain, resseq, name)
                or current.atom(atom_name) is not None):
            current = Residue(name, chain, resseq)
            residues.append(current)
        element = (line[76:78].strip() or atom_name.lstrip("0123456789")[:1]).upper()
        serial = hy36decode(line[6:11])
        if serial is None:                       # unreadable serial column
            serial = -1
        current.atoms.append((serial, atom_name, element,
                              np.array([float(line[30 + 8 * i:38 + 8 * i]) for i in range(3)])))
    return residues


def split_monomers(residues):
    """Split an ordered residue list into covalently connected polymer chains.

    Uses backbone geometry, not chain IDs.  Two consecutive residues belong to
    the same monomer when their peptide C-N or phosphodiester O3'-P link is
    within POLYMER_LINK_ANGSTROM.
    """
    monomers = []
    current = []
    for previous, residue in zip([None] + residues[:-1], residues):
        if previous is not None and not _linked(previous, residue):
            monomers.append(current)
            current = []
        current.append(residue)
    if current:
        monomers.append(current)
    return monomers


def _linked(first, second):
    for tail, head in (("C", "N"), ("O3'", "P")):
        a, b = first.atom(tail), second.atom(head)
        if a is not None and b is not None:
            if float(np.linalg.norm(a[3] - b[3])) <= POLYMER_LINK_ANGSTROM:
                return True
    return False


def canonical_sequence(monomer):
    return tuple(r.canonical for r in monomer)


def match_monomers(reference, submission):
    """Pair reference monomers with submission monomers by canonical sequence.

    Homo-oligomers have no unique pairing and need none: every copy faces the
    same per-residue checks, so sequences are grouped and the group sizes are
    compared.  Returns (pairs, problems).
    """
    ref_groups = collections.defaultdict(list)
    sub_groups = collections.defaultdict(list)
    for m in reference:
        ref_groups[canonical_sequence(m)].append(m)
    for m in submission:
        sub_groups[canonical_sequence(m)].append(m)

    pairs, problems = [], []
    for sequence, ref_copies in ref_groups.items():
        sub_copies = sub_groups.get(sequence, [])
        if len(sub_copies) != len(ref_copies):
            problems.append(
                f"{len(ref_copies)} copies of a {len(sequence)}-residue chain in the "
                f"reference, {len(sub_copies)} in the submission")
        pairs.extend(zip(ref_copies, sub_copies))
    for sequence, sub_copies in sub_groups.items():
        if sequence not in ref_groups:
            problems.append(
                f"submission has an extra {len(sequence)}-residue chain "
                f"({''.join(s[0] for s in sequence[:12])}...) absent from the reference")
    return pairs, problems


# Metals whose coordination decides the protonation of the side chains around
# them.  Same list MDClaw guards its disulfide detection with.
METAL_RESIDUES = frozenset({
    "ZN", "FE", "CU", "NI", "CO", "MN", "CD", "HG", "PT", "AU", "AG", "MO", "W",
    "MG", "CA",
})

# Backbone atoms are never metal ligands in a protein.  Including them turns a
# single zinc into a dozen "ligands": measured on the reference trajectories, a
# 4.5 A cutoff over all atoms picks up every amide nitrogen in the loop.
BACKBONE_ATOMS = frozenset({"N", "CA", "C", "O", "OXT", "H", "HA", "HA2", "HA3",
                            "H1", "H2", "H3", "HN"})

# Longest metal-ligand separation that still counts as coordination.  Zn-S is
# 2.3 A; across 6W9C's three copies the same site measures 2.19 to 3.21 A.
METAL_LIGAND_ANGSTROM = 3.5


def read_metals(path):
    """(label, xyz) for every metal ion in a structure file."""
    metals = []
    for line in open(path):
        if not line.startswith(("ATOM", "HETATM")):
            continue
        name = line[17:20].strip().upper()
        if name not in METAL_RESIDUES:
            continue
        metals.append((f"{name}{line[22:27].strip()}",
                       np.array([float(line[30 + 8 * i:38 + 8 * i]) for i in range(3)])))
    return metals


def metal_ligand_positions(monomers, metals, cutoff=METAL_LIGAND_ANGSTROM):
    """{id(monomer): {1-based position, ...}} for side chains ligating a metal.

    Keyed by the monomer object rather than by its index, because
    ``match_monomers`` groups monomers by canonical sequence and the pairs it
    returns are not in input order: for anything but a single chain, an
    index-keyed result would exempt positions in the wrong monomer.

    Taken from the built structure, which still carries the deposit's
    coordinates, not from the trajectory.  The reference trajectories show why:
    once two thiolates leave, the zinc is chelated by whatever oxygen is near --
    measured 1.75 A to GLN191:OE1 in 6WRH -- and a set derived from the run
    would exempt a glutamine that was never a ligand.
    """
    positions = {}
    for monomer in monomers:
        found = set()
        for position, residue in enumerate(monomer, start=1):
            for _, atom_name, element, xyz in residue.atoms:
                if atom_name in BACKBONE_ATOMS or element not in ("S", "N", "O"):
                    continue
                if any(float(np.linalg.norm(xyz - metal)) <= cutoff
                       for _, metal in metals):
                    found.add(position)
                    break
        if found:
            positions[id(monomer)] = found
    return positions


# Longest Cys-SG to His-N separation that still reads as a catalytic dyad.
# Measured on the three references: the dyad sits at 2.98, 3.08 and 3.11 A and
# the next closest Cys/His pair in the same structure is 4.08, 4.63 and 4.08 A,
# so 3.5 A isolates one pair per structure with most of an angstrom to spare.
CATALYTIC_DYAD_ANGSTROM = 3.5

# The His nitrogens that can carry the proton of the pair.
HIS_DONORS = ("ND1", "NE2")


def catalytic_dyad_positions(monomers, metals, cutoff=CATALYTIC_DYAD_ANGSTROM):
    """{id(monomer): {1-based position, ...}} for a cysteine-histidine dyad.

    Found by geometry rather than by residue name, so it reads the same on a
    reference that wrote CYM/HIP and on a submission that wrote CYS/HIE: the
    heavy atoms do not move when the proton does.

    Whether such a pair is a thiolate-imidazolium ion pair or a neutral
    thiol-imidazole is not settled.  Neutron crystallography of SARS-CoV-2 Mpro
    reports the zwitterion, room-temperature X-ray of the same enzyme reports
    the neutral form, MD of cruzain reports neutral, and for 3CL-PR the
    dominant species reportedly differs between H2O and D2O.  A benchmark
    cannot score a contested choice, so the pair is exempted from the
    protonation comparison and recorded instead -- the same treatment the metal
    sites get, for the same reason.

    Residues ligating a metal are excluded: a Cys and a His on one zinc are
    close to each other through the metal, not to each other.
    """
    ligands = metal_ligand_positions(monomers, metals, cutoff=METAL_LIGAND_ANGSTROM)
    positions = {}
    for monomer in monomers:
        bound = ligands.get(id(monomer), set())
        cysteines = [(index, residue) for index, residue in enumerate(monomer, start=1)
                     if residue.canonical == "CYS" and residue.atom("SG") is not None]
        histidines = [(index, residue) for index, residue in enumerate(monomer, start=1)
                      if residue.canonical == "HIS"]
        found = set()
        for cys_index, cys in cysteines:
            if cys_index in bound:
                continue
            sulfur = cys.atom("SG")[3]
            for his_index, his in histidines:
                if his_index in bound:
                    continue
                distances = [float(np.linalg.norm(sulfur - his.atom(name)[3]))
                             for name in HIS_DONORS if his.atom(name) is not None]
                if distances and min(distances) <= cutoff:
                    found.update((cys_index, his_index))
        if found:
            positions[id(monomer)] = found
    return positions


def compare_monomer(reference, submission, exempt=()):
    """Per-residue comparison inside one matched monomer.

    ``exempt`` holds 1-based positions whose protonation is a metal-site
    modelling decision rather than a preparation error.  Their identity is
    still compared -- a cysteine that became an alanine is a mutation and has
    nothing to do with the metal -- but their atom counts and element counts
    are not, because there is no defensible target to compare them against:
    measured 2026-08-22, all three references hold a four-cysteine structural
    zinc with a bare 12-6 ion and deprotonate two of the four ligands, so a
    submission that deprotonates all four is further from the reference and
    closer to right.
    """
    findings = {"sequence": [], "atom_counts": [], "elements": []}
    exempt = set(exempt)
    for index, (r, s) in enumerate(zip(reference, submission), start=1):
        if r.canonical != s.canonical:
            findings["sequence"].append(f"#{index} {r.label()} vs {s.label()}")
            continue
        if index in exempt:
            continue
        if r.n_atoms != s.n_atoms:
            findings["atom_counts"].append(
                f"#{index} {r.label()} {r.n_atoms} vs {s.label()} {s.n_atoms} atoms")
        if r.element_counts() != s.element_counts():
            findings["elements"].append(
                f"#{index} {r.label()} {dict(sorted(r.element_counts().items()))} vs "
                f"{dict(sorted(s.element_counts().items()))}")
    return findings


def element_totals(monomers):
    total = collections.Counter()
    for monomer in monomers:
        for residue in monomer:
            total += residue.element_counts()
    return dict(sorted(total.items()))
