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
# Lipids a reference can carry.  A single one is a bound ligand; a bilayer is
# hundreds, and the scorer compares composition against the reference, so a
# submission that leaves the membrane out fails on every count.
LIPIDS = frozenset({"POPC", "POPE", "POPS", "POPG", "POPI", "POPA", "DPPC", "DOPC",
                    "DOPE", "DMPC", "DPPE", "DPPG", "DLPC", "PLPC", "SDPC", "SAPI",
                    "CHL1", "CHOL", "PSM", "SSM"})
BILAYER_RESIDUES = 20

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
              "LYN": "neutral lysine", "ARN": "neutral arginine",
              "TYM": "deprotonated tyrosine"}


def _code(name):
    return AMINO.get(name) or NUCLEIC.get(name) or "X"


def seqres(path):
    """Chain -> the deposit's full construct sequence, modified residues included."""
    parents = modres_parents(path)
    out = collections.OrderedDict()
    for line in open(path, errors="replace"):
        if line.startswith("SEQRES"):
            for name in line[19:].split():
                out.setdefault(line[11], []).append(_code(parents.get(name, name)))
    return {k: "".join(v) for k, v in out.items()}


def modres_parents(path):
    """Residue name -> the standard residue its MODRES record stands for.

    A modified residue is present in the deposit; it is just not spelled with a
    standard name. Skipping it makes the walk call it unresolved, and the prompt
    then tells the agent to build a residue that is already there -- 4OW0 asked
    for residue 112 to be built while also saying it is deposited as OCS.

    Keyed by name rather than by position because both sides of the alignment
    have to agree: reading OCS as C in the ATOM records while SEQRES still gives
    X puts the walk one residue out and every later anchor with it.
    """
    out = {}
    for line in open(path, errors="replace"):
        if line.startswith("MODRES"):
            out[line[12:15].strip()] = line[24:27].strip()
    return out


def observed(path):
    """Chain -> [(auth residue number, one-letter code)] in file order.

    Modified residues count as observed, under the residue they stand for.
    """
    parents = modres_parents(path)
    out, seen = collections.OrderedDict(), set()
    for line in open(path, errors="replace"):
        if line.startswith("ENDMDL"):
            break
        if not line.startswith(("ATOM", "HETATM")):
            continue
        name, chain, number = line[17:20].strip(), line[21], line[22:27].strip()
        code = AMINO.get(name) or NUCLEIC.get(name)
        if code is None:
            parent = parents.get(name)
            code = (AMINO.get(parent) or NUCLEIC.get(parent)) if parent else None
        if not code or (chain, number) in seen:
            continue
        seen.add((chain, number))
        out.setdefault(chain, []).append((number, code))
    return out


def observed_runs(pairs):
    """Observed residues split into runs of consecutive residue numbers.

    A run is the unit that can be placed in SEQRES with confidence: inside one
    the numbering is contiguous by construction, so its residue codes are a
    contiguous stretch of SEQRES and matching them is unambiguous almost always.
    Between runs anything may have happened -- unresolved residues, a
    renumbered fusion partner -- and nothing about the gap has to be guessed.
    """
    runs = []
    for number, code in pairs:
        try:
            value = int(str(number).strip())
        except (TypeError, ValueError):
            value = None
        previous = runs[-1][-1][0] if runs else None
        if runs and value is not None and previous is not None and value == previous + 1:
            runs[-1].append((value, number, code))
        else:
            runs.append([(value, number, code)])
    return runs


def seqres_to_auth(deposit, chain):
    """SEQRES position (1-based) -> the deposit's own residue number.

    Placed a run at a time rather than residue by residue.  Walking the two
    sequences together and advancing past every mismatch is what the docstring
    here used to describe as "without an alignment", and a repeated residue
    breaks it: 1AHW chain C is SEQRES ``S G T T N T`` against an observed
    ``T N T`` starting at author 4, so the walk spent SEQRES position 3 on
    author 4 and shifted every later anchor by one.  The reference covers SEQRES
    4-211 there, and the prompt came out asking for author 5-211 -- 207 residues
    where the reference has 208 -- while the residues it named as unresolved
    were a different set from the ones that are.

    Matching a whole run instead makes the repeat harmless: it is the run's
    codes that have to sit somewhere in SEQRES, and a run of any length lands in
    one place.  Runs are placed left to right and may not overlap, which is what
    being a subsequence means.  Measured across the cast, this takes the chains
    whose converted length disagrees with the reference from 12 to 5 and the
    ones resting on an extrapolated endpoint from 16 to 6; the rest are chains
    whose numbering skips, where the range is right and only its width is not.

    Unobserved positions are absent from the result; ``auth_number``
    extrapolates for them.
    """
    full = seqres(deposit).get(chain, "")
    pairs = observed(deposit).get(chain, [])
    if not full or not pairs:
        return {}
    out, cursor = {}, 0
    for run in observed_runs(pairs):
        codes = "".join(code for _, _, code in run)
        start = full.find(codes, cursor)
        if start < 0:
            # A run that matches nowhere left is a sequence its own SEQRES does
            # not contain. Placing it anywhere would be a guess, so it is left
            # unplaced -- but the runs after it are not, because breaking out
            # here made one stray record cost the whole rest of the chain, and a
            # free amino acid deposited as a HETATM beside its ion is exactly
            # that: 1DTD ends with a GLU 300 that is a ligand, not residue 300.
            # An incomplete mapping is refused by `mapping_is_trustworthy`.
            continue
        for offset, (_, number, _) in enumerate(run):
            out[start + offset + 1] = number
        cursor = start + len(codes)
    return out


def mapping_is_trustworthy(deposit, chain, mapping, tolerated_singletons=1):
    """Whether the whole chain was placed, so a number taken from it means something.

    Every residue, not a share of them.  A share was the wrong test: a chain
    whose middle disagrees with its own SEQRES placed 60 of 99 residues, passed
    a half threshold, and produced a prompt saying 40 residues of the range are
    unresolved when the deposit resolves 39 of them.  Nothing about a partly
    placed chain is safe to state, because which part failed is exactly what is
    not known.

    Costs nothing: measured across the 100 shipped tasks all 159 chains place
    completely, and across the 769 chains of every deposit on disk, 767 do.

    A single unplaced run of one residue is tolerated, because that is what a
    free amino acid deposited as a HETATM looks like -- 1DTD's GLU 300 beside
    its zinc -- and it is not part of the polymer whose numbering is in
    question.  A run of two or more that cannot be placed is a real
    disagreement and is refused.
    """
    seen = observed(deposit).get(chain, [])
    if not seen:
        return False
    unplaced = len(seen) - len(mapping)
    if unplaced == 0:
        return True
    if unplaced > tolerated_singletons:
        return False
    # Tolerated only when what went missing really was a lone residue.
    return all(len(run) > 1 or unplaced == 1
               for run in observed_runs(seen) if len(run) == 1)


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
        # Refused here rather than left to the caller: every number this module
        # states comes out of this mapping, and a chain that did not place is a
        # chain whose numbers are guesses. The guard lived beside the mapping
        # and nothing in the library called it, so a partly placed chain reached
        # the prompt with no refusal anywhere on the documented path.
        if deposit_chain and not mapping_is_trustworthy(deposit, deposit_chain, mapping):
            raise SystemExit(
                f"chain {deposit_chain} of the deposit does not place against its "
                "own SEQRES, so no residue number taken from it means anything")
        entry = {"reference_chain": chain.get("参照鎖"), "deposit_chain": deposit_chain,
                 "residues": chain.get("長さ")}
        if chain.get("種別") == "SEQRES に連続一致":
            lo, hi = _span(chain["SEQRES位置"])
            entry["ranges"], entry["numbering_certain"] = auth_ranges(mapping, lo, hi)
            entry["seqres_start"] = lo
            # Kept because a chain may have to be re-measured on a different
            # deposit chain later: the SEQRES interval is what the match found,
            # and it is the only form that survives being moved. Reconstructing
            # it from the auth range does not work -- 6I53's deposit chain E maps
            # auth 10 to SEQRES 3, and the arithmetic returns -18.
            entry["seqres_spans"] = [(lo, hi)]
            unresolved = [p for p in range(lo, hi + 1) if p not in mapping]
            entry["build_missing"] = len(unresolved)
            # Name them rather than count them: "build residue 315" is followed,
            # "three residues are not resolved" has to be worked out first.
            named = [auth_number(mapping, p)[0] for p in unresolved]
            entry["build_residues"] = [n for n in named if n]
        elif chain.get("種別", "").startswith("SEQRES に 2 区間"):
            spans, seqres_spans = [], []
            for key in ("区間1", "区間2"):
                lo, hi = _span(chain[key])
                seqres_spans.append((lo, hi))
                segment, _ = auth_ranges(mapping, lo, hi)
                spans.append(segment)
            entry["ranges"] = [span for segment in spans for span in segment]
            entry["removed_residues"] = chain.get("除去長")
            entry["internal_deletion"] = True
            entry["seqres_start"] = _span(chain["区間1"])[0]
            entry["seqres_spans"] = seqres_spans
            entry["numbering_certain"] = all(x for span in spans for x in span)
        out.append(entry)
    for detail in (record.get("詳細") or []):
        if not detail.get("差分"):
            continue
        deposit_chain = detail.get("寄託鎖")
        mapping = seqres_to_auth(deposit, deposit_chain) if deposit_chain else {}
        if deposit_chain and not mapping_is_trustworthy(deposit, deposit_chain, mapping):
            raise SystemExit(
                f"chain {deposit_chain} of the deposit does not place against its "
                "own SEQRES, so no residue number taken from it means anything")
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
                    "seqres_spans": [(lo, hi)], "seqres_start": lo,
                    "numbering_certain": bool(a and b)})
    return merge_by_deposit_chain(assign_distinct_chains(out, deposit))


def spans_overlap(one, other):
    """Whether two lists of author ranges cover a residue in common.

    The test that separates the two ways a deposit chain comes to carry several
    reference chains.  Pieces of one construct are disjoint by construction --
    the crystallisation partner was cut out from between them -- while two copies
    of a subunit cover the same residues twice.
    """
    def number(value):
        try:
            return int(value)
        except (TypeError, ValueError):
            return None

    for lo, hi in one:
        for other_lo, other_hi in other:
            bounds = [number(v) for v in (lo, hi, other_lo, other_hi)]
            if None in bounds:
                # An endpoint that is not a plain number has no arithmetic to
                # do, so only an identical pair counts as covering the same
                # residues rather than a guess about which way it sorts.
                if (lo, hi) == (other_lo, other_hi):
                    return True
                continue
            if bounds[0] <= bounds[3] and bounds[2] <= bounds[1]:
                return True
    return False


def remeasure_on(entry, deposit, chain):
    """The entry as it reads on a different deposit chain.

    Measured again from the SEQRES intervals the match found, not from the author
    range, and one range per interval.  Collapsing a two-interval match into one
    span is how 6I53 came to ask for deposit chain D residues 10-401: the correct
    answer is 10-322 and 384-417, the deposit holds nothing between them, and the
    single span both invents 45 residues and loses the statement that the two
    pieces are joined.
    """
    mapping = seqres_to_auth(deposit, chain)
    ranges, certain, unresolved = [], True, []
    for lo, hi in entry["seqres_spans"]:
        segment, segment_certain = auth_ranges(mapping, lo, hi)
        ranges.extend(segment)
        certain = certain and segment_certain
        unresolved += [p for p in range(lo, hi + 1) if p not in mapping]
    moved = dict(entry, deposit_chain=chain, ranges=ranges, numbering_certain=certain)
    if entry.get("build_missing") is not None:
        named = [auth_number(mapping, p)[0] for p in unresolved]
        moved["build_missing"] = len(unresolved)
        moved["build_residues"] = [n for n in named if n]
    return moved


def assign_distinct_chains(entries, deposit):
    """One deposit chain per construct, when the deposit has enough of them.

    The sequence match places each reference chain independently, so identical
    chains all land on the first one that matches: a self-complementary DNA
    duplex put both strands on deposit chain C, and merging then read the two
    identical ranges as a chain with a fusion in the middle.  A deposit with two
    identical chains has two, and saying so is both true and what an agent needs.

    Grouped before claiming, because a deposit chain can collect reference chains
    for both reasons at once and they need opposite treatment.  6I53 is a GABA-A
    pentamer whose subunits are each fusion constructs: deposit chain E collects
    four reference chains, which are two copies of two pieces.  Moving one
    duplicate per twin, in the order they arrive, left both full-length copies on
    E -- the only overlapping range pair in the cast -- and stranded a 33-residue
    piece away from the copy it belongs to.  Pieces of one construct are disjoint
    and copies overlap, so grouping on that answers both at once.
    """
    full = seqres(deposit)
    constructs, order = {}, []
    for entry in entries:
        order.append(entry)
        chain = entry.get("deposit_chain")
        if chain is None:
            continue
        groups = constructs.setdefault(chain, [])
        for group in groups:
            if not spans_overlap(entry.get("ranges") or [],
                                 [span for member in group
                                  for span in (member.get("ranges") or [])]):
                group.append(entry)
                break
        else:
            groups.append([entry])

    taken, moved = set(constructs), {}
    for chain, groups in constructs.items():
        for group in groups[1:]:
            twin = next((other for other, sequence in full.items()
                         if other not in taken and sequence == full.get(chain)), None)
            if not twin:
                continue
            taken.add(twin)
            for entry in group:
                # Identical SEQRES does not mean identical numbering or identical
                # observed extent, so the ranges have to be measured again on the
                # chain they are now claimed to describe.
                moved[id(entry)] = (remeasure_on(entry, deposit, twin)
                                    if entry.get("seqres_spans")
                                    else dict(entry, deposit_chain=twin))
    return [moved.get(id(entry), entry) for entry in order]


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
            merged[chain] = dict(entry, reference_polymers=1)
            continue
        target = merged[chain]
        target["ranges"] = sorted(target["ranges"] + entry["ranges"],
                                  key=lambda span: _sort_key(span[0]))
        target["residues"] = (target.get("residues") or 0) + (entry.get("residues") or 0)
        if entry.get("build_missing"):
            target["build_missing"] = (target.get("build_missing") or 0) + entry["build_missing"]
        if entry.get("build_residues"):
            # The count was being merged and the sites were not, so a chain that
            # gained a second reference polymer kept one list and lost the other.
            # The sites are what the prompt is written from; the count is only
            # upstream provenance.
            merged_sites = list(target.get("build_residues") or [])
            for site in entry["build_residues"]:
                if site not in merged_sites:
                    merged_sites.append(site)
            target["build_residues"] = merged_sites
        # Never add author numbers together: a renumbered fusion partner makes
        # the arithmetic report 790 residues for a 160-residue insert. The
        # classifier's own count is used where it exists.
        if entry.get("removed_residues"):
            target["removed_residues"] = entry["removed_residues"]
        if entry.get("differences"):
            target.setdefault("differences", []).extend(entry["differences"])
        # Two reference chains on one deposit chain means the reference left a
        # piece of it out, which is the same statement as an internal deletion.
        target["internal_deletion"] = True
        # How many polymers the reference holds this deposit chain as, which is
        # what says whether it ligated the pieces or left them apart.  Counted
        # here because it is provenance and cannot be recovered afterwards: one
        # reference chain carrying an internal deletion and two reference chains
        # merged onto one deposit chain produce the same ranges.
        target["reference_polymers"] = target.get("reference_polymers", 1) + 1
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
        if not any(e["name"] == name and e["residue"] == number for e in out):
            out.append({"name": name, "parent": parent, "chain": chain,
                        "residue": number, "note": note})
    return out


def stated_protonation(reference_pdb, deposit=None, chains=None):
    """Ionisation variants a prompt has to state, in the deposit's numbering.

    Two kinds are exempt from scoring and so must not be stated: the residues
    that ligate a metal and the catalytic cysteine-histidine pair.  There is no
    settled answer for either -- the literature disagrees with itself about
    whether such a pair is a thiolate-imidazolium or neutral -- which is why the
    scorer exempts them, and stating an exempt residue would hand over an answer
    nobody is being asked for.  The exemption is found by geometry here exactly
    as the scorer finds it, so the two agree by construction.

    Tautomers are never returned.  The scorer counts atoms per residue and HID
    and HIE have the same formula, so it cannot see them either way.

    **The number is the deposit's, not the reference's.**  References renumber:
    ATLAS 16pk_A runs 1-415 in its own file.  Returning that number would name a
    residue an agent cannot find in the entry it is given, which is the mistake
    this module exists to remove.  Without a mapping the residue is returned
    with ``residue: None`` and the caller drops it rather than stating a number
    that does not mean anything.
    """
    from mddatabench import composition as cp

    monomers = cp.split_monomers(cp.read_residues(reference_pdb))
    metals = cp.read_metals(reference_pdb)
    exempt = set()
    for source in (cp.metal_ligand_positions(monomers, metals),
                   cp.catalytic_dyad_positions(monomers, metals)):
        for monomer_id, positions in source.items():
            exempt.update((monomer_id, position) for position in positions)
    mappings = {}
    if deposit and chains:
        for entry in chains:
            deposit_chain = entry.get("deposit_chain")
            if deposit_chain and deposit_chain not in mappings:
                mappings[deposit_chain] = seqres_to_auth(deposit, deposit_chain)
    out = []
    for index, monomer in enumerate(monomers):
        entry = chains[index] if chains and index < len(chains) else None
        for position, residue in enumerate(monomer, start=1):
            name = residue.name.strip().upper()
            if name not in IONISATION or (id(monomer), position) in exempt:
                continue
            number = None
            if entry and entry.get("seqres_start") is not None:
                mapping = mappings.get(entry.get("deposit_chain")) or {}
                number, _ = auth_number(mapping, entry["seqres_start"] + position - 1)
            out.append({"chain": entry.get("deposit_chain") if entry else residue.chain,
                        "residue": number, "name": name,
                        "meaning": IONISATION[name],
                        "reference_residue": residue.resseq})
    return [entry for entry in out if entry["residue"] is not None]


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

# Protein force fields a submission can actually be built with, checked against
# MDClaw's catalogue on 2026-08-23: it is Amber-only, and ff94, ff96 and ff99 are
# refused outright as obsolete.  CHARMM36 and CHARMM36m are deliberately absent
# even though 54 of the hundred references use one of them -- naming a field the
# reference implementation cannot build makes the prompt unfollowable, and the
# md checks are force-field independent by design precisely so this can be left
# to the agent.
FORCE_FIELDS = {"Amber ff14SB": "Amber ff14SB", "Amber ff19SB": "Amber ff19SB",
                "Amber ff99SB-ILDN": "Amber ff99SB-ILDN",
                "Amber ff99SB": "Amber ff99SB", "Amber ff15ipq": "Amber ff15ipq",
                "Amber fb15": "Amber fb15", "Amber ff03.r1": "Amber ff03.r1"}
WATERS = {"TIP3P": "TIP3P", "OPC": "OPC", "OPC3": "OPC3", "TIP4PEW": "TIP4P-Ew",
          "TIP4P-EW": "TIP4P-Ew", "TIP4PEW ": "TIP4P-Ew", "SPCE": "SPC/E",
          "SPC/E": "SPC/E", "SPC-E": "SPC/E"}


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
    """A chain and its ranges, or a refusal.

    An entry whose numbering could not be recovered used to print "chain
    **None** residues **None–None**", which is worse than not shipping the task.
    """
    chain = entry.get("deposit_chain")
    spans = [(a, b) for a, b in entry.get("ranges") or [] if a is not None and b is not None]
    if not chain or not spans:
        raise SystemExit(
            f"the reference chain {entry.get('reference_chain')!r} could not be placed "
            "on the deposit; the task cannot state what to simulate")
    return (f"chain **{chain}** residues "
            + " and ".join(f"**{a}–{b}**" for a, b in spans))


def bilayer(metadata):
    """The lipid a reference is embedded in, and how many of it.

    A deposit does not say either: the crystallised receptor carries a handful of
    ordered lipids at most, while the reference simulated 360. Leaving it to the
    agent means building the receptor in water, which is not the system.
    """
    count = metadata.get("LIPIRES") or 0
    try:
        count = int(count)
    except (TypeError, ValueError):
        return None
    if count < BILAYER_RESIDUES:
        return None
    names = sorted(set(metadata.get("RSNAME") or []) & LIPIDS)
    return {"lipid": names[0] if len(names) == 1 else names, "residues": count}


def joins_its_pieces(chosen_chains):
    """The deposit chains whose pieces the reference holds as one polymer.

    A fusion construct is written as two ranges, and simulating it is not one
    decision but two: the crystallisation partner comes out, and then the two
    receptor halves are either left as separate chains or ligated into one.
    Measured across the fusion references in the cast, 5ZK8 bonds residue 214 to
    383 at 1.35 A where the deposit leaves them 9.6 A apart, while 5YC8 keeps
    199 and 79 residues apart.  The deposit records neither, so the prompt has
    to.

    Read from provenance rather than inferred from counts.  The two ways a chain
    comes to carry several ranges are exactly the two answers: one reference
    chain with an internal deletion is one polymer and was ligated, while
    several reference chains merged onto one deposit chain are several polymers
    and were not.  Counting instead -- fewer reference polymers than requested
    pieces -- reads a bound ligand or a chain break inside a piece as a join,
    and cannot say which of three pieces were joined to which.
    """
    return frozenset(entry["deposit_chain"] for entry in chosen_chains
                     if len(entry.get("ranges") or []) > 1
                     and entry.get("reference_polymers", 1) == 1)


def _validated_build_sites(entry: dict) -> list:
    """The residues this chain must build, or nothing, never a bare count.

    Gated on ``build_residues`` and never on ``build_missing``. The two have
    different provenance: ``build_missing`` is a length that survives being
    merged and moved between deposit chains, and in the finished contracts it
    reports a non-zero value for seven tasks whose reference built nothing at
    all. Emitting prose from the count produced instructions that added
    residues the reference does not have, failing the very composition check
    they were meant to satisfy.

    A named site that the surrounding prompt contradicts is a defect in the
    task, not a residue to drop quietly: 011_membrane_6kuy asked an agent both
    to leave residues out and to build them because a silent filter swallowed
    the collision. Generation fails instead.

    Identifiers keep their insertion codes and are compared as identifiers, not
    as integers. Author numbering is not an ordering: 036 declares ``1A-79``,
    and reading ``1A``, ``1`` and ``1B`` all as ``1`` would let a site match a
    range endpoint or an omission it has nothing to do with. Without the
    deposit's polymer scheme this function cannot order an insertion-coded
    site, so it accepts one only where the range endpoint spells it exactly,
    and refuses anything it cannot read at all.
    """
    named = list(entry.get("build_residues") or [])
    if not named:
        return []
    chain = entry.get("deposit_chain")
    spans = [(_site_key(low), _site_key(high))
             for low, high in (entry.get("ranges") or [])]
    omitted = set()
    for span in (entry.get("omitted") or []):
        low, high = _as_int(span[0]), _as_int(span[1])
        if low is None or high is None:
            raise ValueError(
                f"chain {chain}: omitted span {span!r} is not a residue range")
        omitted.update(range(min(low, high), max(low, high) + 1))

    seen: list = []
    for site in named:
        if site in seen or str(site) in {str(other) for other in seen}:
            raise ValueError(
                f"chain {chain}: residue {site} is listed twice for building")
        number, icode = _site_key(site)
        if number is None:
            raise ValueError(
                f"chain {chain}: residue {site!r} is not an author residue id")
        if not icode and number in omitted:
            raise ValueError(
                f"chain {chain}: residue {site} is both built and omitted")
        if spans and not _site_within(number, icode, spans):
            raise ValueError(
                f"chain {chain}: residue {site} is built but lies outside "
                f"every stated range {entry.get('ranges')}")
        seen.append(site)
    return seen


def _site_key(value) -> tuple:
    """``"1A"`` as ``(1, "A")``; a bare number as ``(n, "")``."""
    match = re.match(r"\s*(-?\d+)([A-Za-z]?)\s*$", str(value))
    return (int(match.group(1)), match.group(2).upper()) if match else (None, "")


def _site_within(number: int, icode: str, spans: list) -> bool:
    """Is this site inside one of the spans, without ordering by number alone?

    An insertion-coded site is accepted only where an endpoint spells it
    exactly. ``1A`` may precede or follow ``1`` depending on the deposit's own
    scheme, which this module cannot see, so anything else is refused rather
    than guessed.
    """
    for (low, low_icode), (high, high_icode) in spans:
        if low is None or high is None:
            continue
        if icode:
            if ((number, icode) == (low, low_icode)
                    or (number, icode) == (high, high_icode)):
                return True
            continue
        first, last = min(low, high), max(low, high)
        if first < number < last:
            return True
        # An endpoint carrying its own insertion code names one residue, not
        # every residue sharing that number.
        if number == low and not low_icode:
            return True
        if number == high and not high_icode:
            return True
    return False


def _as_int(value):
    """The numeric part of an author residue id, or None for a bare code."""
    text = str(value).strip()
    match = re.match(r"(-?\d+)", text)
    return int(match.group(1)) if match else None


def build_prompt(task_id, title, pdb, metadata, chosen_chains, modres, protonation,
                 window_ns, replicas=1, joined_chains=()):
    """The text an agent is given.  Derived, not written.

    ``joined_chains`` names the deposit chains whose pieces the reference holds
    as one continuous polymer.  See ``joins_its_pieces``: a construct written as
    two ranges can be simulated as two chains or as one, the deposit records
    neither, and the two differ by a peptide bond and two pairs of termini.
    """
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
    temperature = metadata.get("TEMP")
    if temperature is None:
        raise SystemExit("the reference records no temperature, so the prompt cannot "
                         "state one and the measured-temperature check cannot be scored")
    # 38 of the hundred references record no ensemble. NPT is what the prompt
    # asks for and what the density and box checks assume, and the contract
    # records both that and the fact the reference did not say.
    # The ensemble decides whether there is a pressure at all. NVT has no
    # barostat, so naming one would be wrong; NPT without a setpoint leaves the
    # agent to guess a number the density check then grades.
    ensemble = metadata.get("ENSEMBLE") or "NPT"
    if ensemble.upper() == "NVT":
        lines.append(f"- **{temperature} K**, **NVT** (no barostat)")
    else:
        pressure = metadata.get("_pressure_bar") or 1
        lines.append(f"- **{temperature} K**, **{ensemble}** at **{pressure:g} bar**")
    lines.append(f"- at least **{window_ns:g} ns** of production MD")
    lines.append("")

    for entry in chosen_chains:
        removed = entry.get("removed_residues") or 0
        if entry.get("internal_deletion") and removed >= FUSION_RESIDUES:
            lines += [f"Chain {entry['deposit_chain']} is deposited as a fusion: "
                      f"{removed} residues between those ranges belong to the "
                      "crystallisation partner. Simulate the protein without them.", ""]
        if entry["deposit_chain"] in joined_chains:
            lines += [f"Join the pieces of chain {entry['deposit_chain']} into a "
                      "single continuous chain, bonded where the removed part "
                      "was.", ""]
        named = _validated_build_sites(entry)
        if named:
            which = ", ".join(str(site) for site in named)
            lines += [f"Chain {entry['deposit_chain']} does not resolve "
                      f"residue{'s' if len(named) > 1 else ''} {which}; the range "
                      "runs through them, so build them.", ""]
        for span in (entry.get("omitted") or []):
            where = span[0] if span[0] == span[1] else f"{span[0]}–{span[1]}"
            lines += [f"Residue {where} of chain {entry['deposit_chain']} is not part of "
                      "the reference. Leave it out.", ""]
        for difference in (entry.get("differences") or []):
            if difference.get("residue") is None:
                continue
            lines += [f"Residue {difference['residue']} is deposited as "
                      f"**{ONE_LETTER.get(difference['deposited'], difference['deposited'])}**; "
                      f"simulate the "
                      f"**{ONE_LETTER.get(difference['reference'], difference['reference'])}**.", ""]
    for entry in modres:
        if not entry.get("residue"):
            continue
        lines += [f"Residue {entry['residue']} is deposited as **{entry['name']}**, a "
                  f"modified {entry['parent']}. Simulate the unmodified residue.", ""]
    membrane = bilayer(metadata)
    if membrane:
        lipid = membrane["lipid"]
        what = lipid if isinstance(lipid, str) else " and ".join(lipid)
        lines += [f"Embed it in a **{what}** bilayer.", ""]
    if metadata.get("_structural_metals"):
        names = ", ".join(sorted(metadata["_structural_metals"]))
        lines += [f"The entry carries a structural {names}. Keep it.", ""]
    for entry in protonation:
        where = (f"Residue {entry['residue']} of chain {entry['chain']}"
                 if entry.get("chain") else f"Residue {entry['residue']}")
        lines += [f"{where} is a {entry['meaning']}.", ""]
    # Everything the previous line did not name is standard, and saying so is
    # the point: a pKa predictor will disagree with the reference somewhere.
    # MDClaw runs pdb2pqr+propka at pH 7.4 and it neutralised two aspartates of
    # 5ZK8 that the reference kept charged, which the atom-count check sees as a
    # composition difference the prompt never asked for. Every reference in the
    # cast carries hydrogens, so "standard except where stated" is measured
    # rather than assumed.
    lines += [("Simulate every other ionisable side chain" if protonation
               else "Simulate every ionisable side chain")
              + " in its standard state at pH 7: charged aspartate, glutamate, "
                "lysine and arginine, and neutral histidine and cysteine.", ""]
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


def recompute_on_chain(entry, deposit, chain):
    """Move an entry to another copy of the same chain, and re-measure it.

    Identical SEQRES does not mean identical observed extent: a homotrimer
    resolves different residues in each copy, so 6W9C chain A is missing 225-227
    where chain C is missing 315. Naming one chain and listing the other's gaps
    tells the agent to build residues that are already there.
    """
    if chain == entry.get("deposit_chain") or entry.get("seqres_start") is None:
        return dict(entry, deposit_chain=chain)
    mapping = seqres_to_auth(deposit, chain)
    lo = entry["seqres_start"]
    hi = lo + (entry.get("residues") or 1) - 1
    ranges, certain = auth_ranges(mapping, lo, hi)
    unresolved = [p for p in range(lo, hi + 1) if p not in mapping]
    named = [auth_number(mapping, p)[0] for p in unresolved]
    return dict(entry, deposit_chain=chain, ranges=ranges, numbering_certain=certain,
                build_missing=len(unresolved),
                build_residues=[n for n in named if n])


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
