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
import itertools

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
# SG-SG is 2.04 A in both D03 artifacts; 2.5 A is the same limit the earlier
# per-task check used.
DISULFIDE_ANGSTROM = 2.5

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


def compare_monomer(reference, submission):
    """Per-residue comparison inside one matched monomer."""
    findings = {"sequence": [], "atom_counts": [], "elements": []}
    for index, (r, s) in enumerate(zip(reference, submission), start=1):
        if r.canonical != s.canonical:
            findings["sequence"].append(f"#{index} {r.label()} vs {s.label()}")
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


def atom_totals(monomers):
    return sum(r.n_atoms for m in monomers for r in m)


def reference_disulfides(monomers, cutoff=DISULFIDE_ANGSTROM):
    """Expected S-S pairs, taken from the reference's own CYX residues.

    The reference names disulfide-bonded cysteines CYX and carries coordinates,
    so the pairing is data, not a curator's list.  Zero CYX means zero pairs,
    which is a real expectation and is checked like any other.
    """
    sulfurs = []
    for chain_index, monomer in enumerate(monomers):
        for residue in monomer:
            if residue.canonical == "CYS" and residue.name.upper() == "CYX":
                atom = residue.atom("SG")
                if atom is not None:
                    sulfurs.append(((chain_index, residue.resseq), atom[3]))
    pairs = set()
    for (left, x), (right, y) in itertools.combinations(sulfurs, 2):
        if float(np.linalg.norm(x - y)) <= cutoff:
            pairs.add(frozenset((left, right)))
    return pairs, len(sulfurs)


def submitted_disulfides(path, monomers):
    """Observed S-S pairs, from the CONECT records of the submitted topology.

    CONECT is where the bond actually lives: ``system.system.xml`` is a compiled
    force-field object with no atom names and, once HBonds and rigid water turn
    most bonds into constraints, no bond list either -- D03's System keeps 177
    HarmonicBondForce terms against 21451 constraints.  Returns
    (pairs, unusable_reason).
    """
    located = {}
    for chain_index, monomer in enumerate(monomers):
        for residue in monomer:
            if residue.canonical != "CYS":
                continue
            atom = residue.atom("SG")
            if atom is not None:
                located[atom[0]] = (chain_index, residue.resseq)
    if any(serial < 0 for serial in located):
        return set(), ("an SG atom carries an unreadable serial number; "
                       "disulfide bonding cannot be read from this topology")

    pairs = set()
    for line in open(path):
        if not line.startswith("CONECT"):
            continue
        fields = []
        for i in range(5):
            chunk = line[6 + 5 * i:11 + 5 * i]
            if chunk.strip():
                serial = hy36decode(chunk)
                if serial is None:
                    return set(), "malformed CONECT record in the submitted topology"
                fields.append(serial)
        for partner in fields[1:]:
            if fields[0] in located and partner in located and fields[0] != partner:
                pairs.add(frozenset((located[fields[0]], located[partner])))
    return pairs, None


def _residue_order(item):
    """Sort key for (chain_index, resseq): numeric, so 3 precedes 11."""
    chain, resseq = item
    digits = "".join(itertools.takewhile(str.isdigit, resseq))
    return chain, int(digits) if digits else 0, resseq


def describe_pairs(pairs):
    out = []
    for pair in sorted(pairs, key=lambda p: sorted(p, key=_residue_order)[0]):
        (c1, r1), (c2, r2) = sorted(pair, key=_residue_order)
        out.append(f"{r1}-{r2}" if c1 == c2 else f"{c1}:{r1}-{c2}:{r2}")
    return out
