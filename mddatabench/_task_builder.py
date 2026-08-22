"""Build a task contract and its prompt from the reference, not from a curator.

Everything a task states about its reference is derived here from three things
already on disk: MDDB's metadata, the deposit from RCSB, and the reference's own
structure file.  Nothing is typed in by hand, because the three PLpro tasks that
were show what hand-typing costs -- D01 was unsolvable until someone noticed the
reference simulates residues 4-315, and D02 until someone noticed the deposit
carries C111S.

**Residue numbers are the deposit's own, not SEQRES positions.**  The two are
not the same and the difference is not visible unless you look: 6WRH's reference
covers SEQRES 7-318, which is auth 4-315, and its substitution sits at SEQRES
114, which is auth 111.  Both numbers appear in the prompts because they are what
an agent reads off the PDB entry; a contract stating SEQRES indices would be
quietly wrong for every deposit whose numbering does not start at one.
"""

from __future__ import annotations

import collections
import re

AMINO = {"ALA": "A", "ARG": "R", "ASN": "N", "ASP": "D", "CYS": "C", "GLN": "Q",
         "GLU": "E", "GLY": "G", "HIS": "H", "ILE": "I", "LEU": "L", "LYS": "K",
         "MET": "M", "PHE": "F", "PRO": "P", "SER": "S", "THR": "T", "TRP": "W",
         "TYR": "Y", "VAL": "V", "MSE": "M"}
NUCLEIC = {"DA": "a", "DT": "t", "DG": "g", "DC": "c", "DU": "u",
           "A": "A", "U": "U", "G": "G", "C": "C",
           # Amber and CHARMM name the terminal nucleotides differently from the
           # internal ones. Leaving them out dropped both ends of every strand:
           # 1A66's 12-mer duplex came back as a 10-mer, and the prompt then
           # named the inner residues only.
           "DA5": "a", "DA3": "a", "DT5": "t", "DT3": "t", "DG5": "g", "DG3": "g",
           "DC5": "c", "DC3": "c", "DU5": "u", "DU3": "u",
           "A5": "A", "A3": "A", "U5": "U", "U3": "U", "G5": "G", "G3": "G",
           "C5": "C", "C3": "C", "RA": "A", "RU": "U", "RG": "G", "RC": "C",
           "RA5": "A", "RA3": "A", "RU5": "U", "RU3": "U", "RG5": "G", "RG3": "G",
           "RC5": "C", "RC3": "C"}
ONE_LETTER = {v: k for k, v in reversed(list(AMINO.items()))}

# Ionisation variants a prompt has to state, and tautomers it must not.  The
# scorer counts atoms per residue: HID and HIE have the same formula and are
# invisible to it, while every variant below costs or adds exactly one hydrogen.
# Stating a tautomer would hand over a free answer; not stating an ionisation
# would make the check unanswerable.
# An author-numbering step larger than this is a renumbering rather than an
# unresolved stretch.  Deposits number a fusion partner in the 1000s, so the
# jump is hundreds; the longest unresolved stretch in the cast is 46 residues.
RENUMBERING_JUMP = 100

# Internal residues the reference left out, above which they are a
# crystallisation partner rather than a gap.  Measured across the cast: the
# removals are either 1 or 2 residues, or 60 and above.
FUSION_RESIDUES = 30

IONISATION = {"HIP": "protonated histidine", "CYM": "deprotonated cysteine",
              "ASH": "protonated aspartate", "GLH": "protonated glutamate",
              "LYN": "neutral lysine"}


def _code(name):
    return AMINO.get(name) or NUCLEIC.get(name) or "X"


def seqres(path):
    """Chain -> the deposit's full construct sequence."""
    out = collections.OrderedDict()
    for line in open(path, errors="replace"):
        if line.startswith("SEQRES"):
            for name in line[19:].split():
                out.setdefault(line[11], []).append(_code(name))
    return {k: "".join(v) for k, v in out.items()}


def observed(path):
    """Chain -> [(auth residue number, one-letter code)] in file order."""
    out, seen = collections.OrderedDict(), set()
    for line in open(path, errors="replace"):
        if line.startswith("ENDMDL"):
            break
        if not line.startswith(("ATOM", "HETATM")):
            continue
        name, chain, number = line[17:20].strip(), line[21], line[22:27].strip()
        code = AMINO.get(name) or NUCLEIC.get(name)
        if not code or (chain, number) in seen:
            continue
        seen.add((chain, number))
        out.setdefault(chain, []).append((number, code))
    return out


def seqres_to_auth(deposit, chain):
    """SEQRES position (1-based) -> the deposit's own residue number.

    The observed residues are a subsequence of SEQRES in order, so walking the
    two together fixes the correspondence without an alignment.  Unobserved
    positions are absent from the result; ``auth_number`` extrapolates for them.
    """
    full = seqres(deposit).get(chain, "")
    out, index = {}, 0
    for number, code in observed(deposit).get(chain, []):
        while index < len(full) and full[index] != code:
            index += 1
        if index >= len(full):
            break
        out[index + 1] = number
        index += 1
    return out


def auth_number(mapping, position):
    """The deposit's number for a SEQRES position, extrapolated when unobserved.

    A reference that builds a missing terminal residue -- D01's 315 -- has no
    observed anchor at that position, and the prompt still has to name it.
    Numbering is contiguous within a chain often enough that stepping from the
    nearest anchor is right; when it is not, the value is marked uncertain by
    the caller rather than silently trusted.
    """
    if position in mapping:
        return mapping[position], True
    if not mapping:
        return None, False
    nearest = min(mapping, key=lambda p: abs(p - position))
    try:
        return str(int(mapping[nearest]) + (position - nearest)), False
    except ValueError:                        # insertion codes
        return None, False


def auth_ranges(mapping, lo, hi):
    """A SEQRES span as ranges in the deposit's own numbering.

    Only observed residues anchor a range.  Extrapolating every unobserved
    position independently made the extrapolations collide around a gap --
    1AHW's chain C came back as "5-5 and 5-83 and 91-95 and 89-211" for what is
    one span with eight unresolved residues in it.  Unobserved residues inside a
    span are not a boundary; they are the thing the prompt tells the agent to
    build.

    A span does break where the *observed* numbering jumps further than the
    SEQRES distance explains, which is what a fusion partner does: 6ME3 runs
    receptor 14-211, then the partner in the 1000s, then the receptor again.
    """
    anchors = [(position, mapping[position]) for position in range(lo, hi + 1)
               if position in mapping]
    if not anchors:
        (a, _), (b, _) = auth_number(mapping, lo), auth_number(mapping, hi)
        return [[a, b]], False
    spans, start = [], anchors[0]
    for previous, current in zip(anchors, anchors[1:]):
        try:
            step = int(current[1]) - int(previous[1])
        except ValueError:
            step = 1                           # insertion codes stay in their run
        # A residue the deposit did not resolve leaves a small gap in the
        # numbering and is not a boundary -- it is what "build them" refers to.
        # A renumbering is: a fusion partner numbered in the 1000s jumps by
        # hundreds and comes back.
        jumped = step <= 0 or step > RENUMBERING_JUMP
        if jumped:
            spans.append([start[1], previous[1]])
            start = current
    spans.append([start[1], anchors[-1][1]])
    # The ends themselves may be unobserved -- a reference that builds a missing
    # terminal residue still has to name it.
    certain = lo in mapping and hi in mapping
    if lo not in mapping:
        first, exact = auth_number(mapping, lo)
        if first and len(spans) == 1 or (first and spans):
            spans[0][0] = first
    if hi not in mapping:
        last, exact = auth_number(mapping, hi)
        if last:
            spans[-1][1] = last
    return spans, certain


def _span(text):
    lo, hi = text.split("-")
    return int(lo), int(hi)


def selection(record, deposit):
    """What the reference simulated, in the deposit's own chains and numbering.

    Returns one entry per reference chain: the deposit chain it corresponds to,
    the residue range or ranges, whether anything had to be built, and any
    residue where the reference and the deposit disagree.
    """
    out = []
    # A chain that only the approximate pass could place appears in both lists;
    # the exact list carries no range for it, so the approximate entry is the
    # one with anything to say.
    approximate = {d.get("参照鎖") for d in (record.get("詳細") or []) if d.get("差分")}
    for chain in (record.get("鎖") or []):
        if chain.get("種別") == "説明不能" or chain.get("参照鎖") in approximate:
            continue
        deposit_chain = chain.get("寄託鎖")
        mapping = seqres_to_auth(deposit, deposit_chain) if deposit_chain else {}
        entry = {"reference_chain": chain.get("参照鎖"), "deposit_chain": deposit_chain,
                 "residues": chain.get("長さ")}
        if chain.get("種別") == "SEQRES に連続一致":
            lo, hi = _span(chain["SEQRES位置"])
            entry["ranges"], entry["numbering_certain"] = auth_ranges(mapping, lo, hi)
            entry["build_missing"] = sum(1 for p in range(lo, hi + 1) if p not in mapping)
        elif chain.get("種別", "").startswith("SEQRES に 2 区間"):
            spans = []
            for key in ("区間1", "区間2"):
                lo, hi = _span(chain[key])
                segment, _ = auth_ranges(mapping, lo, hi)
                spans.append(segment)
            entry["ranges"] = [span for segment in spans for span in segment]
            entry["removed_residues"] = chain.get("除去長")
            entry["internal_deletion"] = True
            entry["numbering_certain"] = all(x for span in spans for x in span)
        out.append(entry)
    for detail in (record.get("詳細") or []):
        if not detail.get("差分"):
            continue
        deposit_chain = detail.get("寄託鎖")
        mapping = seqres_to_auth(deposit, deposit_chain) if deposit_chain else {}
        lo, hi = _span(detail["SEQRES位置"])
        (a, _), (b, _) = auth_number(mapping, lo), auth_number(mapping, hi)
        differences = []
        for item in detail["差分"]:
            position, change = item.split(":")
            deposited, reference = change.split("->")
            number, _ = auth_number(mapping, int(position))
            differences.append({"residue": number, "deposited": deposited,
                                "reference": reference})
        out.append({"reference_chain": detail.get("参照鎖"),
                    "deposit_chain": deposit_chain, "residues": detail.get("長さ"),
                    "ranges": [[a, b]], "differences": differences,
                    "numbering_certain": bool(a and b)})
    return merge_by_deposit_chain(assign_distinct_chains(out, deposit))


def assign_distinct_chains(entries, deposit):
    """One deposit chain per reference chain, when the deposit has enough of them.

    The sequence match places each reference chain independently, so identical
    chains all land on the first one that matches: a self-complementary DNA
    duplex put both strands on deposit chain C, and merging then read the two
    identical ranges as a chain with a fusion in the middle.  A deposit with two
    identical chains has two, and saying so is both true and what an agent needs.
    """
    full = seqres(deposit)
    taken, out = set(), []
    for entry in entries:
        chain = entry.get("deposit_chain")
        if chain is None or chain not in taken:
            taken.add(chain)
            out.append(entry)
            continue
        twin = next((other for other, sequence in full.items()
                     if other not in taken and sequence == full.get(chain)), None)
        if twin:
            entry = dict(entry, deposit_chain=twin)
            taken.add(twin)
        out.append(entry)
    return out


def merge_by_deposit_chain(entries):
    """One entry per deposit chain, however many reference chains map onto it.

    A GPCR crystallised with a fusion partner comes back as two reference chains
    on one deposit chain -- 5YC8's receptor is deposit A residues 16-214 and
    380-458, with the cytochrome in between. Left unmerged the prompt names the
    same chain twice and never says why there is a gap.
    """
    merged = {}
    for entry in entries:
        chain = entry["deposit_chain"]
        if chain not in merged:
            merged[chain] = dict(entry)
            continue
        target = merged[chain]
        target["ranges"] = sorted(target["ranges"] + entry["ranges"],
                                  key=lambda span: _sort_key(span[0]))
        target["residues"] = (target.get("residues") or 0) + (entry.get("residues") or 0)
        for key in ("build_missing", "removed_residues"):
            if entry.get(key):
                target[key] = (target.get(key) or 0) + entry[key]
        if entry.get("differences"):
            target.setdefault("differences", []).extend(entry["differences"])
        # Two reference chains on one deposit chain means the reference left a
        # piece of it out, which is the same statement as an internal deletion.
        target["internal_deletion"] = True
        target["numbering_certain"] = bool(target.get("numbering_certain")
                                           and entry.get("numbering_certain"))
    for entry in merged.values():
        entry["ranges"], entry["omitted"] = coalesce(entry["ranges"])
        if entry.get("internal_deletion") and not entry.get("removed_residues"):
            gaps = []
            for (_, end), (start, _) in zip(entry["ranges"], entry["ranges"][1:]):
                try:
                    gaps.append(int(start) - int(end) - 1)
                except (TypeError, ValueError):
                    gaps.append(None)
            total = sum(g for g in gaps if g and g > 0)
            entry["removed_residues"] = total or None
    return list(merged.values())


def coalesce(ranges):
    """Join ranges separated by less than a crystallisation partner.

    6ME3's reference omits one residue in the middle of its fusion partner, so
    the exact answer is four ranges. Reporting "1001-1002 and 1004-1196" is
    faithful and unreadable; "1001-1196, without 1003" is both.
    """
    out, omitted = [], []
    for span in ranges:
        if not out:
            out.append(list(span))
            continue
        try:
            gap = int(span[0]) - int(out[-1][1]) - 1
        except (TypeError, ValueError):
            gap = None
        if gap is not None and 0 <= gap < FUSION_RESIDUES:
            if gap:
                omitted.append([str(int(out[-1][1]) + 1), str(int(span[0]) - 1)])
            out[-1][1] = span[1]
        else:
            out.append(list(span))
    return out, omitted


def _sort_key(value):
    try:
        return (0, int(value))
    except (TypeError, ValueError):
        return (1, str(value))


def modified_residues(deposit, chains):
    """MODRES records: what the deposit calls a residue and what it really is.

    A reference that reverts one -- 4OW0's OCS, the catalytic cysteine oxidised
    to the sulfonic acid -- is making a preparation decision the agent cannot
    infer, and one the scorer will charge for: OCS carries three oxygens CYS does
    not, so keeping it fails the element comparison.
    """
    out = []
    for line in open(deposit, errors="replace"):
        if not line.startswith("MODRES"):
            continue
        name, chain, number = line[12:15].strip(), line[16], line[18:22].strip()
        parent, note = line[24:27].strip(), line[29:].strip()
        if chains and chain not in chains:
            continue
        if not any(entry["name"] == name for entry in out):
            out.append({"name": name, "parent": parent, "chain": chain,
                        "residue": number, "note": note})
    return out


def stated_protonation(reference_pdb):
    """Ionisation variants a prompt has to state, with the carve-outs removed.

    ``RSNAME`` lists every variant the reference used, but two kinds are exempt
    from scoring and so must not be stated: the residues that ligate a metal and
    the catalytic cysteine-histidine pair.  There is no settled answer for
    either -- the literature disagrees with itself about whether such a pair is
    a thiolate-imidazolium or neutral -- which is why the scorer exempts them,
    and stating an exempt residue would hand over an answer nobody is being
    asked for.  The exemption is found by geometry here exactly as the scorer
    finds it, so the two agree by construction.

    Tautomers are never returned.  The scorer counts atoms per residue and HID
    and HIE have the same formula, so it cannot see them either way.
    """
    from mddatabench import composition as cp

    monomers = cp.split_monomers(cp.read_residues(reference_pdb))
    metals = cp.read_metals(reference_pdb)
    exempt = set()
    for source in (cp.metal_ligand_positions(monomers, metals),
                   cp.catalytic_dyad_positions(monomers, metals)):
        for monomer_id, positions in source.items():
            exempt.update((monomer_id, position) for position in positions)
    out = []
    for monomer in monomers:
        for position, residue in enumerate(monomer, start=1):
            name = residue.name.strip().upper()
            if name in IONISATION and (id(monomer), position) not in exempt:
                out.append({"chain": residue.chain, "residue": residue.resseq,
                            "name": name, "meaning": IONISATION[name]})
    return out


def chain_from_name(text):
    """The chain a depositor named in prose, when they named one.

    MDDB titles say things like "from PDB 6W9C C-chain", and ATLAS and the
    nanobody set encode it as ``1ab1_A`` and ``1kxv_C2-120``.  A homomeric
    deposit's chains are interchangeable chemically, so the sequence match alone
    cannot recover which one the depositor meant.
    """
    for pattern in (r"\b(\w{4})_([A-Za-z])\d*[-\d]*", r"\b([A-Za-z])[- ]chain\b",
                    r"\bchain\s+([A-Za-z])\b"):
        found = re.search(pattern, str(text or ""))
        if found:
            return found.group(2) if found.lastindex and found.lastindex > 1 else found.group(1)
    return None


# --- the prompt ---------------------------------------------------------------
# A prompt states only what cannot be inferred from the deposit, and says
# nothing about analysis.  Everything below is derived; nothing is a choice made
# here.  What is deliberately absent is as load-bearing as what is present: the
# force field is named only when the reference's is one the submission can
# actually build, ambiguous protonation is never named because it is not scored,
# and the accession is never named because the agent must not fetch the answer.

FORCE_FIELDS = {"Amber ff14SB": "Amber ff14SB", "Amber ff19SB": "Amber ff19SB",
                "Amber ff99SB-ILDN": "Amber ff99SB-ILDN", "CHARMM36m": "CHARMM36m",
                "CHARMM36": "CHARMM36"}
WATERS = {"TIP3P": "TIP3P", "OPC": "OPC", "OPC3": "OPC3", "TIP4PEW": "TIP4P-Ew",
          "SPCE": "SPC/E", "SPC/E": "SPC/E"}


def buildable_force_field(fields):
    """The reference's protein force field, when a submission can build it.

    MoDEL is Amber Parm99, which the builder refuses as obsolete, and the
    nucleic references are ParmBSC1 where the builder has OL15.  Naming a field
    that cannot be built would make the prompt unfollowable, and the md checks
    are force-field independent by design, so the prompt simply says nothing in
    that case.
    """
    for field in (fields or []):
        if field in FORCE_FIELDS:
            return FORCE_FIELDS[field]
    return None


def _range_text(entry):
    spans = " and ".join(f"**{a}–{b}**" for a, b in entry["ranges"])
    return f"chain **{entry['deposit_chain']}** residues {spans}"


def build_prompt(task_id, title, pdb, metadata, chosen_chains, modres, protonation,
                 window_ns, replicas=1):
    """The text an agent is given.  Derived, not written."""
    field = buildable_force_field(metadata.get("FF"))
    water = WATERS.get(str(metadata.get("WAT") or "").upper())
    lines = [f"# Task {task_id}", ""]
    what = ", ".join(_range_text(entry) for entry in chosen_chains)
    lines += [f"Simulate {title}, PDB entry **{pdb}**, {what}, in explicit solvent.", ""]
    conditions = []
    if field:
        conditions.append(f"**{field}** protein force field")
    if water:
        conditions.append(f"**{water}** water")
    conditions.append("neutralised")
    lines.append("- " + ", ".join(conditions))
    ensemble = metadata.get("ENSEMBLE") or "NPT"
    lines.append(f"- **{metadata.get('TEMP')} K**, **{ensemble}**")
    lines.append(f"- at least **{window_ns:g} ns** of production MD")
    lines.append("")

    for entry in chosen_chains:
        removed = entry.get("removed_residues") or 0
        if entry.get("internal_deletion") and removed >= FUSION_RESIDUES:
            lines += [f"Chain {entry['deposit_chain']} is deposited as a fusion: "
                      f"{removed} residues between those ranges belong to the "
                      "crystallisation partner. Simulate the protein without them.", ""]
        if entry.get("build_missing"):
            lines += [f"{entry['build_missing']} residue(s) of that range are not "
                      "resolved in the deposit. Build them.", ""]
        for span in (entry.get("omitted") or []):
            where = span[0] if span[0] == span[1] else f"{span[0]}–{span[1]}"
            lines += [f"Residue {where} of chain {entry['deposit_chain']} is not part of "
                      "the reference. Leave it out.", ""]
        for difference in (entry.get("differences") or []):
            lines += [f"Residue {difference['residue']} is deposited as "
                      f"**{ONE_LETTER.get(difference['deposited'], difference['deposited'])}**; "
                      f"simulate the "
                      f"**{ONE_LETTER.get(difference['reference'], difference['reference'])}**.", ""]
    for entry in modres:
        lines += [f"Residue {entry['residue']} is deposited as **{entry['name']}**, a "
                  f"modified {entry['parent']}. Simulate the unmodified residue.", ""]
    if metadata.get("_structural_metals"):
        names = ", ".join(sorted(metadata["_structural_metals"]))
        lines += [f"The entry carries a structural {names}. Keep it.", ""]
    for entry in protonation:
        lines += [f"Residue {entry['residue']} is a {entry['meaning']}.", ""]
    if replicas > 1:
        lines += ["", ]
    lines += ["Leave the prepared structure, the topology, the minimised state and the "
              "production", "trajectory as artifacts. The evaluator recomputes everything "
              "it needs from them.", ""]
    return "\n".join(lines)


def molecule_name(entry, chains):
    """What to call the system, preferring the polymer's name over the title.

    A deposit's title is written for a paper -- "X-Ray Structural and Biological
    Evaluation of a Series of Potent..." -- while the polymer entity carries the
    molecule: "papain-like protease".  Falling back to the title is better than
    naming nothing, and both are the deposit's own words either way.
    """
    names = []
    for polymer in (entry.get("polymer_entities") or []):
        identifiers = polymer.get("rcsb_polymer_entity_container_identifiers") or {}
        if chains and not (set(identifiers.get("auth_asym_ids") or []) & set(chains)):
            continue
        description = (polymer.get("rcsb_polymer_entity") or {}).get("pdbx_description")
        if description and description not in names:
            names.append(description)
    if names:
        # A fusion construct lists the partner as its own entity. The prompt
        # already says to leave the partner out, so naming it here would only
        # contradict that.
        first = _short(names[0])
        return first if len(names) == 1 else f"{first} in complex with {_short(names[1])}"
    title = ((entry.get("struct") or {}).get("title") or "").strip()
    return _short(title) or ((entry.get("struct_keywords") or {}).get("pdbx_keywords")
                             or "the deposited system").lower()


def _short(text, limit=70):
    """A name, not a paper title. Cut at a comma or a clause, never mid-word."""
    text = str(text or "").split(",")[0].strip()
    if len(text) <= limit:
        return text
    cut = text[:limit].rsplit(" ", 1)[0]
    return cut.rstrip(" -")


def deposit_chains(deposit):
    """Chain identifiers the deposit actually has."""
    return set(observed(deposit))


def resolve_chain(named, matched, deposit):
    """Which chain to name in the prompt.

    A homomeric deposit's chains are chemically interchangeable, so the sequence
    match cannot recover which one a depositor meant and the depositor's own
    words are better.  But those words can also be wrong about the deposit:
    MDDB calls 6WRH's reference "from PDB 6WRH C-chain" and 6WRH has only chain
    A.  So the named chain is used only when the deposit has it.
    """
    if named and named in deposit_chains(deposit):
        return named
    return matched
