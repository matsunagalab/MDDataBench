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

# Terminal nucleotides, collapsed onto the same parent for the same reason.
# Amber marks a strand's ends by name -- DA5, DT3, G5, C3 -- and every nucleic
# reference in the cast is written that way, while a submission may write the
# plain residue and leave the terminus to the atoms. Measured by stripping the
# suffixes from each reference and re-matching: without this, 12 of the 14
# nucleic tasks pair no monomer at all and 1KX5 pairs 8 of 10, so three md gates
# fail on a correct submission. What the terminus actually is stays graded,
# because a 5' end carries no phosphate and the atom count inside the matched
# monomer says so.
CANONICAL_RESIDUE.update({
    f"{base}{end}": base
    for base in ("DA", "DC", "DG", "DT", "DU", "A", "C", "G", "U", "T")
    for end in ("5", "3")
})

SOLVENT_RESIDUES = {
    "HOH", "WAT", "TIP", "TIP3", "TIP4", "SOL", "T3P", "T4P", "OPC",
    "NA", "NA+", "SOD", "CL", "CL-", "CLA", "K", "K+", "POT", "MG", "CA",
    "ZN", "IOD", "BR", "LI", "CS", "RB", "F",
}

# Lipids of a bilayer, which are environment rather than solute.  How many of
# them there are follows from the box the agent chose, not from any chemistry
# decision: the membrane references carry 360 and a submission that builds a
# perfectly good bilayer of 320 is not wrong.  Counting them turned every
# membrane task into a guess at the reference's box, because a reference with
# 360 DPPC contributes 360 monomers and 360 phosphorus atoms to comparisons that
# demand exact equality.  Which lipid it is, is a chemistry decision, and
# ``lipid_species`` checks that separately.
# A lipid has two spellings and they are not interchangeable text.  CHARMM and
# the PDB write one residue per lipid -- DPPC, truncated to DPP in three PDB
# columns -- while Amber's Lipid21 splits it into a head-group residue and one
# residue per acyl chain, so the same DPPC bilayer reads as PC + PA + PA.  A
# reference simulated under CHARMM therefore never shares a residue name with a
# correct submission built under Lipid21, and comparing the names directly
# rejects it.  Both are decomposed into Lipid21 components before comparison.
LIPID21_HEADS = {"PC", "PE", "PS", "PGR", "PH-", "PI", "PGS"}
LIPID21_TAILS = {"PA", "ST", "OL", "MY", "LAL", "AR", "DHA", "SA", "PO"}
LIPID21_WHOLE = {"CHL", "CHL1"}          # cholesterol is not split

# Monolithic names, decomposed.  The first two letters of a CHARMM lipid name
# its chains (DP = di-palmitoyl, PO = palmitoyl+oleoyl) and the last its head.
LIPID_COMPONENTS = {
    "DPPC": {"PC", "PA"},          "DPPE": {"PE", "PA"},   "DPPG": {"PGR", "PA"},
    "DPPS": {"PS", "PA"},
    "POPC": {"PC", "PA", "OL"},    "POPE": {"PE", "PA", "OL"},
    "POPG": {"PGR", "PA", "OL"},   "POPS": {"PS", "PA", "OL"},
    "POPI": {"PI", "PA", "OL"},    "POPA": {"PH-", "PA", "OL"},
    "DOPC": {"PC", "OL"},          "DOPE": {"PE", "OL"},   "DOPS": {"PS", "OL"},
    "DMPC": {"PC", "MY"},          "DLPC": {"PC", "LAL"},  "DSPC": {"PC", "ST"},
    "PLPC": {"PC", "PA", "LAL"},   "SDPC": {"PC", "ST", "DHA"},
    "SAPI": {"PI", "ST", "AR"},
    "CHL1": {"CHL"},               "CHOL": {"CHL"},
    "PSM": {"PSM"},                "SSM": {"SSM"},
}

LIPID_RESIDUES = (set(LIPID_COMPONENTS)
                  | LIPID21_HEADS | LIPID21_TAILS | LIPID21_WHOLE
                  # PDB truncates a four-letter lipid name to three columns.
                  | {name[:3] for name in LIPID_COMPONENTS})


def lipid_components(name, stated=None):
    """The Lipid21 components of one lipid residue name.

    ``stated`` resolves a three-column truncation: DPP is DPPC, DPPE or DPPG and
    the file cannot say which, but the task contract records the lipid the
    reference was built from, and that is what the truncation abbreviates.
    """
    name = name.strip().upper()
    if name in LIPID_COMPONENTS:
        return frozenset(LIPID_COMPONENTS[name])
    if name in LIPID21_HEADS or name in LIPID21_TAILS or name in LIPID21_WHOLE:
        return frozenset({name})
    if stated and name == stated.strip().upper()[:len(name)]:
        return frozenset(LIPID_COMPONENTS.get(stated.strip().upper(), {stated}))
    return frozenset()


def lipid_chemistry(counts, stated=None):
    """Decompose a species tally into (Lipid21 components, number of lipids).

    Counting lipids means counting head groups, not residues: under Lipid21 one
    DPPC is three residues and under CHARMM it is one.
    """
    components, lipids = set(), 0
    for name, count in counts.items():
        parts = lipid_components(name, stated)
        components |= parts
        key = name.strip().upper()
        if key in LIPID21_TAILS:
            continue                              # a tail is half a lipid, not one
        lipids += count
    return frozenset(components), lipids

# Longest bond that still counts as the polymer link.  A peptide C-N is 1.33 A
# and a phosphodiester O3'-P is 1.60 A; 2.0 A separates them from the 3-4 A gap
# left by a chain break without admitting a non-bonded contact.
POLYMER_LINK_ANGSTROM = 2.0

class Residue:
    __slots__ = ("name", "chain", "resseq", "atoms")

    def __init__(self, name, chain, resseq):
        self.name = name
        self.chain = chain
        self.resseq = resseq
        self.atoms = []          # (atom_name, element, xyz)

    @property
    def canonical(self):
        return CANONICAL_RESIDUE.get(self.name, self.name)

    @property
    def n_atoms(self):
        return len(self.atoms)

    def element_counts(self):
        return collections.Counter(a[1] for a in self.atoms if a[1] != "H")

    def atom(self, name):
        for a in self.atoms:
            if a[0] == name:
                return a
        return None

    def label(self):
        return f"{self.name}{self.resseq}"


def lipid_species(path):
    """Which lipids a structure carries, and how many of each.

    Kept separate from the residue list because the species is a decision and
    the count is a consequence of the box.
    """
    counts = collections.Counter()
    seen = set()
    for line in open(path):
        if not line.startswith(("ATOM", "HETATM")):
            continue
        name = line[17:20].strip().upper()
        if name not in LIPID_RESIDUES:
            continue
        key = (line[21], line[22:27].strip(), name)
        if key in seen:
            continue
        seen.add(key)
        counts[name] += 1
    return dict(counts)


def read_residues(path, drop_solvent=True):
    """Ordered residues of a PDB, solvent, free ions and bilayer lipids removed."""
    residues = []
    current = None
    for line in open(path):
        if not line.startswith(("ATOM", "HETATM")):
            continue
        name = line[17:20].strip()
        if drop_solvent and name.upper() in (SOLVENT_RESIDUES | LIPID_RESIDUES):
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
        current.atoms.append((atom_name, element,
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
            if float(np.linalg.norm(a[2] - b[2])) <= POLYMER_LINK_ANGSTROM:
                return True
    return False


def canonical_sequence(monomer):
    return tuple(r.canonical for r in monomer)


def residue_formula(residue):
    """Element counts including hydrogen, used to resolve a generic ``LIG``."""
    return tuple(sorted(collections.Counter(atom[1] for atom in residue.atoms).items()))


def match_monomers(reference, submission):
    """Pair reference monomers with submission monomers by canonical sequence.

    Homo-oligomers have no unique pairing and need none: every copy faces the
    same per-residue checks, so sequences are grouped and the group sizes are
    compared.  Returns (pairs, problems).
    """
    # Some MDDB topology exports replace a deposited ligand name with the
    # generic residue name LIG.  In that one narrow case the name cannot carry
    # identity, so pair a singleton submission component only when its complete
    # formula (including hydrogens) is identical.  Named ligands are never
    # aliased to one another.
    generic_ligand_formulas = {
        residue_formula(monomer[0])
        for monomer in reference
        if len(monomer) == 1 and monomer[0].canonical == "LIG"
    }

    def matching_key(monomer):
        if len(monomer) == 1:
            formula = residue_formula(monomer[0])
            if formula in generic_ligand_formulas:
                return (("__GENERIC_LIGAND__", formula),)
        return canonical_sequence(monomer)

    ref_groups = collections.defaultdict(list)
    sub_groups = collections.defaultdict(list)
    for m in reference:
        ref_groups[matching_key(m)].append(m)
    for m in submission:
        sub_groups[matching_key(m)].append(m)

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
                f"({''.join(str(s)[0] for s in sequence[:12])}...) absent from the reference")
    return pairs, problems


def contract_correspondence(indices, reference_rows, submitted_rows, pairs):
    """Where each reference contract atom is in the submission.

    The contract names backbone atoms by their index into ``reference.pdb``, and
    the fluctuation gates need the submission's own index for each of them.
    Resolving that by ``(residue number, atom name)`` -- what this replaced --
    compares two files that share no numbering: an antibody numbers each of its
    three chains from 1, so 624 of 1AHW's 642 keys name three different residues
    up to 88.8 A apart and every one of them resolved to the first, reporting
    1908 of 1908 "matched" while 1266 were wrong.  It is not only multimers: a
    submission keeps the deposit's numbering, and 5ZK8 runs 18-214 and 383-458
    against a reference renumbered 1..273.

    Anchored on the monomer pairing instead, which ``match_monomers`` makes from
    canonical sequence and ``split_monomers`` makes from backbone geometry, so
    neither residue numbers nor chain labels are read across the two sides.
    Within one file ``(chain, residue number, atom name)`` does address one atom,
    and that is all it is used for here.

    Built straight off ``pairs``: a paired monomer and its partner are the same
    canonical sequence and therefore the same length, so zipping them addresses
    the submitted residue directly and no monomer identity, offset or
    short-partner guard is needed.  Verified elementwise 2026-08-24 against the
    offset form on all five solved jobs -- same indices, 0 differing slots, the
    atoms 0.0 A apart.

    Returns ``(own_indices, missing)``; ``missing`` describes each atom that
    could not be placed, so a failure names its cause instead of a count.  One
    message covers both ways a contract atom escapes the pairing -- its monomer
    went unpaired, or ``read_residues`` dropped it from the polymer entirely;
    the second never fired on any of the 101 bundles.
    """
    resolve = {}
    for reference_monomer, submitted_monomer in pairs:
        for reference_residue, submitted_residue in zip(reference_monomer,
                                                        submitted_monomer):
            resolve[(reference_residue.chain, reference_residue.resseq)] = submitted_residue
    submitted_index = {}
    for n, row in enumerate(submitted_rows):
        submitted_index.setdefault(row, n)

    own, missing = [], []
    for i in indices:
        chain, resseq, atom_name = reference_rows[i]
        residue = resolve.get((chain, resseq))
        if residue is None:
            missing.append(f"{chain}:{resseq}:{atom_name} is in a monomer the "
                           "submission does not pair with")
            continue
        n = submitted_index.get((residue.chain, residue.resseq, atom_name))
        if n is None:
            missing.append(f"{chain}:{resseq}:{atom_name} has no {atom_name} in the "
                           f"submission's {residue.name}{residue.resseq}")
            continue
        own.append(n)
    return own, missing


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
            for atom_name, element, xyz in residue.atoms:
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
            sulfur = cys.atom("SG")[2]
            for his_index, his in histidines:
                if his_index in bound:
                    continue
                distances = [float(np.linalg.norm(sulfur - his.atom(name)[2]))
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
        generic_ligand_match = (
            (r.canonical == "LIG" or s.canonical == "LIG")
            and residue_formula(r) == residue_formula(s)
        )
        if r.canonical != s.canonical and not generic_ligand_match:
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
