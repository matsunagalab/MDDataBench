"""Fail a task build when its prompt cannot imply its reference system.

Reference preparation relabels chains and may split one declared construct at
an omitted fusion segment, so letter equality produced seven false membrane
defects in the first campaign audit. Compare composition and chemistry instead.
"""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
import json
import pathlib
import re
import urllib.request


WATER = {"HOH", "WAT", "SOL", "TIP", "T3P", "TIP3", "DOD", "H2O"}
BULK_IONS = {"NA", "CL", "K", "SOD", "CLA", "POT", "NA+", "CL-"}
METALS = {"ZN", "FE", "FE2", "MN", "CU", "NI", "CO", "MG", "CA", "CD",
          "HG", "PT", "AU", "AG", "MO", "W"}
CAPS = {"ACE", "NME", "NHE", "NH2", "FOR", "NMA"}
AMINO = set(
    "ALA ARG ASN ASP CYS GLN GLU GLY HIS ILE LEU LYS MET PHE PRO SER THR TRP "
    "TYR VAL HID HIE HIP HSD HSE HSP CYX CYM ASH GLH LYN MSE SEC PYL ARN TYM"
    .split())
NUCLEIC = {r for base in "ACGTU"
           for r in (base, f"D{base}", f"D{base}3", f"D{base}5",
                     f"{base}3", f"{base}5", f"R{base}")}
LIPID = {"DPP", "POP", "POC", "CHL", "DOP", "DPPC", "POPC"}
@dataclass(frozen=True)
class Residue:
    chain: str
    number: int
    icode: str
    name: str

    @property
    def site(self) -> str:
        return f"{self.chain}:{self.number}{self.icode}"


def _structure_records(path: pathlib.Path) -> list[Residue]:
    """First-model residues read by gemmi for both PDB and mmCIF.

    Atom-site rows are CIF tokens, not whitespace-separated text. Gemmi handles
    quoted and wrapped fields. The benchmark prepares one NMR model, so both
    deposit and reference use model zero rather than first-versus-last.
    """
    import gemmi

    if path.suffix.lower() in {".cif", ".mmcif"}:
        block = gemmi.cif.read_file(str(path)).sole_block()
        table = block.find([
            "_atom_site.auth_asym_id",
            "_atom_site.auth_seq_id",
            "_atom_site.label_comp_id",
            "_atom_site.pdbx_PDB_ins_code",
            "_atom_site.pdbx_PDB_model_num",
        ])
        records, seen, first_model = [], set(), None
        for row in table:
            chain, number, name, icode, model = (
                str(value).strip("'\"") for value in row)
            if first_model is None:
                first_model = model
            if model != first_model:
                continue
            name = name.upper()
            if name in WATER:
                continue
            key = (chain, number, "" if icode in {"?", "."} else icode)
            if key in seen:
                continue
            seen.add(key)
            records.append(Residue(key[0], int(key[1]), key[2], name))
        return records

    structure = gemmi.read_structure(str(path))
    if not structure:
        return []
    records = []
    for chain in structure[0]:
        chain_name = str(chain.name).strip() or "A"
        for residue in chain:
            name = str(residue.name).strip().upper()
            if name in WATER:
                continue
            records.append(Residue(
                chain=chain_name,
                number=int(residue.seqid.num),
                icode=str(residue.seqid.icode or "").strip(),
                name=name,
            ))
    return records


def _classify(resname: str) -> str:
    """Classify chemistry without treating a short name list as exhaustive.

    Amber-specific protonation variants still need the explicit sets, but the
    wwPDB residue dictionary supplied by Gemmi recognizes modified polymer
    residues such as SEP/TPO/PTR. Unknown chemistry deliberately remains
    ``other`` so the audit reports it instead of silently dropping it.
    """
    if resname in AMINO:
        return "protein"
    if resname in NUCLEIC:
        return "nucleic"
    if resname in CAPS:
        return "cap"
    if resname in LIPID:
        return "lipid"
    if resname in BULK_IONS:
        return "bulk_ion"
    if resname in METALS:
        return "metal"
    try:
        import gemmi

        residue_info = gemmi.find_tabulated_residue(resname)
        if residue_info.is_amino_acid():
            return "protein"
        if residue_info.is_nucleic_acid():
            return "nucleic"
    except (ImportError, RuntimeError):
        # The scorer environment provides Gemmi. Keeping a conservative
        # fallback makes the standalone report fail visibly on unknown
        # components rather than classifying them as polymer by guesswork.
        pass
    return "other"


def _is_polymer(residue: Residue) -> bool:
    return _classify(residue.name) in {"protein", "nucleic"}


_CHAIN_START = re.compile(
    r"chain\s+\*\*([A-Za-z0-9]+)\*\*\s+residues?\s+", re.I)
_RANGE = re.compile(
    r"\*\*(-?\d+)[A-Za-z]?\s*[–—-]\s*(-?\d+)[A-Za-z]?\*\*", re.I)
_EXCLUDED_RANGE = re.compile(
    r"residues?\s+(?:\*\*)?(-?\d+)(?:\s*[–—-]\s*(-?\d+))?(?:\*\*)?\s+of\s+"
    r"chain\s+(?:\*\*)?([A-Za-z0-9]+)(?:\*\*)?.*?"
    r"(?:not part|leave it out|exclude|without)",
    re.I)
_BUILD_MISSING = re.compile(
    r"chain\s+(?:\*\*)?([A-Za-z0-9]+)(?:\*\*)?\s+does\s+not\s+resolve\s+"
    r"residues?\s+([^.;]+).*?\bbuild\s+them\b", re.I)


_RANGE_TOKENS = re.compile(
    r"\*\*(-?\d+[A-Za-z]?)\s*[–—-]\s*(-?\d+[A-Za-z]?)\*\*")


def declared_range_tokens(prompt: str) -> dict[str, list[tuple[str, str]]]:
    """The prompt's residue ranges as written, insertion codes intact.

    ``_declared`` drops the insertion letter and expands each range with
    integer arithmetic, which is right for counting residues and wrong for
    comparing against ``reference.selection.ranges``: task 036 declares
    ``1A-79`` and the stored contract agrees, but the integer form reads it as
    ``1-79`` and would report a mismatch that is not there.

    Order is preserved and duplicates are kept, because the stored ranges are
    meant to mirror the prompt exactly. Comparing as sets would accept
    008_membrane_6i53's stored list, which repeats one of chain E's ranges and
    drops chain D's second one.
    """
    out: dict[str, list[tuple[str, str]]] = {}
    starts = list(_CHAIN_START.finditer(prompt))
    for index, match in enumerate(starts):
        end = starts[index + 1].start() if index + 1 < len(starts) else len(prompt)
        clause = prompt[match.end():end].split(".", 1)[0]
        pieces = _RANGE_TOKENS.findall(clause)
        if pieces:
            out.setdefault(match.group(1), []).extend(
                (str(first), str(last)) for first, last in pieces)
    return out


def stored_range_tokens(selection: dict) -> dict[str, list[tuple[str, str]]]:
    """``reference.selection.ranges`` in the same shape, for comparison."""
    stored = selection.get("ranges") or {}
    return {chain: [(str(first), str(last)) for first, last in spans]
            for chain, spans in stored.items()}


def selection_range_findings(prompt: str, selection: dict) -> list[dict]:
    """Report where the stored selection stops mirroring the prompt.

    Nothing reads ``selection.ranges`` today -- the scorer recomputes from the
    bundle and the harness hands the agent ``prompt.md`` -- so a disagreement
    mis-scores nothing now. It is recorded because the field claims to be the
    prompt's selection and six tasks show it is not, which any future consumer
    would inherit.
    """
    if "ranges" not in (selection or {}):
        # Nothing claims to mirror the prompt. Every shipped contract carries
        # the field, so this only spares synthetic fixtures that model one
        # chemistry question and omit the selection entirely.
        return []
    declared = declared_range_tokens(prompt)
    stored = stored_range_tokens(selection)
    findings: list[dict] = []
    # `chains` and the keys of `ranges` are separate claims and can disagree
    # separately, so check them separately -- the earlier version named the
    # finding after `chains` while only ever reading `ranges`. `chains` is
    # compared as a set: eight tasks store it in an order their prompt does not
    # use, so the field's order carries no meaning and reordering it would be
    # churn rather than a correction.
    listed = selection.get("chains")
    if listed is not None and set(listed) != set(declared):
        findings.append({
            "kind": "selection_chains_differ_from_prompt",
            "detail": (f"prompt declares {sorted(declared)}, "
                       f"selection.chains holds {sorted(listed)}"),
            "component": "selection",
        })
    if set(declared) != set(stored):
        findings.append({
            "kind": "selection_range_chains_differ_from_prompt",
            "detail": (f"prompt declares {sorted(declared)}, "
                       f"selection.ranges is keyed by {sorted(stored)}"),
            "component": "selection",
        })
    for chain in sorted(set(declared) & set(stored)):
        if declared[chain] != stored[chain]:
            findings.append({
                "kind": "selection_ranges_differ_from_prompt",
                "detail": (f"chain {chain}: prompt {declared[chain]}, "
                           f"selection.ranges {stored[chain]}"),
                "component": "selection",
                "chain": chain,
            })
    return findings


def deposit_polymer_scheme(path) -> dict[str, list[tuple]]:
    """Each deposit chain's residues in the order the deposit itself gives.

    ``_pdbx_poly_seq_scheme`` lists every SEQRES position, observed or not, in
    polymer order, with ``auth_seq_num`` set to ``?`` where there are no
    coordinates. That order is the only sound one: author numbering can carry
    insertion codes, restart, or run non-monotonically, so comparing residue
    numbers cannot tell you which residue comes first.

    Returns ``{chain: [(auth_number, insertion_code, observed), ...]}`` with
    ``auth_number`` None for an unobserved position.
    """
    import gemmi

    block = gemmi.cif.read(str(path)).sole_block()
    table = block.find("_pdbx_poly_seq_scheme.",
                       ["pdb_strand_id", "pdb_seq_num", "auth_seq_num",
                        "pdb_ins_code"])
    scheme: dict[str, list[tuple]] = {}
    for row in table:
        chain = str(row[0])
        # pdb_seq_num carries the author number for every SEQRES position,
        # observed or not; auth_seq_num is "?" exactly where the deposit has no
        # coordinates, which is what makes a position unobserved.
        numbered, resolved = str(row[1]), str(row[2])
        icode = str(row[3])
        icode = "" if icode in (".", "?") else icode.strip().upper()
        observed = resolved not in ("?", ".")
        number = (int(numbered)
                  if numbered.lstrip("-").isdigit() else None)
        scheme.setdefault(chain, []).append((number, icode, observed))
    return scheme


def classify_build_sites(scheme_chain: list, selected: set,
                         sites: list) -> list[dict]:
    """Terminal or internal, judged by position in the polymer, not by number.

    A run is N-terminal when nothing selected precedes it and C-terminal when
    nothing selected follows it. Sites the scheme does not place are reported
    as ``unclassified`` rather than guessed.
    """
    order = {(number, icode): index
             for index, (number, icode, _) in enumerate(scheme_chain)
             if number is not None}
    observed = [index for index, (number, icode, seen) in enumerate(scheme_chain)
                if seen and number is not None and number in selected]
    first, last = (min(observed), max(observed)) if observed else (None, None)
    out = []
    for number, icode in sites:
        index = order.get((number, icode))
        if index is None or first is None:
            out.append({"site": f"{number}{icode}", "class": "unclassified"})
        elif index < first:
            out.append({"site": f"{number}{icode}", "class": "n_terminal"})
        elif index > last:
            out.append({"site": f"{number}{icode}", "class": "c_terminal"})
        else:
            out.append({"site": f"{number}{icode}", "class": "internal"})
    return out


def _declared(prompt: str) -> dict:
    """Structured polymer selection and named chemistry in the prompt."""
    ranges: dict[str, list[tuple[int, int]]] = {}
    starts = list(_CHAIN_START.finditer(prompt))
    for index, match in enumerate(starts):
        # A chain clause may carry several ranges ("18-214 and 383-458").
        # Stop at the next chain clause so its ranges cannot be attributed to
        # the previous chain. The first campaign's membrane prompts use this
        # shape in 11 of 14 tasks.
        end = starts[index + 1].start() if index + 1 < len(starts) else len(prompt)
        clause = prompt[match.end():end]
        # The construct declaration ends before prose later in the prompt;
        # only its first sentence can contribute ranges.
        clause = clause.split(".", 1)[0]
        pieces = [(int(first), int(last))
                  for first, last in _RANGE.findall(clause)]
        if pieces:
            ranges.setdefault(match.group(1), []).extend(pieces)
    excluded: dict[str, list[tuple[int, int]]] = {}
    for start, end, chain in _EXCLUDED_RANGE.findall(prompt.replace("\n", " ")):
        excluded.setdefault(chain, []).append((int(start), int(end or start)))
    selected: dict[str, set[int]] = {}
    for chain, pieces in ranges.items():
        values = set()
        for start, end in pieces:
            values.update(range(min(start, end), max(start, end) + 1))
        for start, end in excluded.get(chain, []):
            values.difference_update(range(min(start, end), max(start, end) + 1))
        selected[chain] = values
    body = "\n".join(line for line in prompt.splitlines()
                     if not line.startswith("# Task"))
    joined = set(re.findall(
        r"join\s+the\s+pieces\s+of\s+chain\s+(?:\*\*)?([A-Za-z0-9]+)",
        prompt, re.I))
    build_missing: dict[str, set[int]] = {}
    # Two views of the same instruction. The integer set is what the polymer
    # count has always used; the exact one keeps the insertion code, because
    # "build residue 1A" and a resolved residue 1 are different residues and
    # collapsing both to 1 makes each look like the other.
    build_sites: dict[str, list[tuple[int, str]]] = {}
    for chain, numbers in _BUILD_MISSING.findall(prompt.replace("\n", " ")):
        for token in re.findall(r"-?\d+[A-Za-z]?", numbers):
            match = re.match(r"(-?\d+)([A-Za-z]?)", token)
            number, icode = int(match.group(1)), match.group(2).upper()
            build_missing.setdefault(chain, set()).add(number)
            site = (number, icode)
            if site not in build_sites.setdefault(chain, []):
                build_sites[chain].append(site)
    return {"chains": set(ranges), "chain_order": list(ranges),
            "ranges": ranges, "selected": selected, "joined": joined,
            "excluded": excluded, "build_missing": build_missing,
            "build_sites": build_sites, "body": body}


def _mentions(body: str, name: str, *, cap: bool = False) -> bool:
    terms = [rf"\b{re.escape(name)}\b"]
    if cap:
        terms.append(r"\b(?:cap|caps|capped|capping|uncapped)\b")
    return re.search("|".join(terms), body, re.I) is not None


def _deposit_path(pdb_id: str, cache_dir: pathlib.Path) -> pathlib.Path | None:
    cache_dir.mkdir(parents=True, exist_ok=True)
    target = cache_dir / f"{pdb_id.upper()}.cif"
    if target.exists() and target.stat().st_size:
        return target
    try:
        with urllib.request.urlopen(
                f"https://files.rcsb.org/download/{pdb_id.upper()}.cif",
                timeout=120) as response:
            target.write_bytes(response.read())
    except Exception:
        return None
    return target


def _selected_deposit(records: list[Residue], declared: dict) -> list[Residue]:
    selected = declared["selected"]
    output = []
    for residue in records:
        if (residue.chain not in selected
                or residue.number not in selected[residue.chain]):
            continue
        if _is_polymer(residue):
            output.append(residue)
            continue
        # A selected modified amino acid still occupies one polymer position
        # when the prompt explicitly says to simulate its unmodified parent.
        if (_classify(residue.name) == "other"
                and re.search(rf"\bresidue\s+{residue.number}\b.*?\bunmodified\b",
                              declared["body"], re.I | re.S)):
            output.append(residue)
    return output


def _contiguous_lengths(values: set[int]) -> list[int]:
    """Lengths of integer runs, independent of author chain labels."""
    lengths: list[int] = []
    previous = None
    for value in sorted(values):
        if previous is None or value != previous + 1:
            lengths.append(1)
        else:
            lengths[-1] += 1
        previous = value
    return lengths


def _declared_polymer_lengths(declared: dict) -> list[int]:
    lengths: list[int] = []
    for chain in declared["chain_order"]:
        values = declared["selected"][chain]
        if chain in declared["joined"]:
            lengths.append(len(values))
        else:
            lengths.extend(_contiguous_lengths(values))
    return sorted(lengths)


def _reference_polymer_lengths(records: list[Residue]) -> list[int]:
    counts = Counter(r.chain for r in records if _is_polymer(r))
    return sorted(counts.values())


def _occurrences(records: list[Residue], kind: str) -> list[Residue]:
    return [r for r in records if _classify(r.name) == kind]


def _occurrence_counts(records: list[Residue], kind: str) -> Counter:
    return Counter(r.name for r in _occurrences(records, kind))


def _deposit_positions(selected: list[Residue],
                       declared: dict) -> dict[tuple[str, int, str], int]:
    """Observed and explicitly rebuilt sites mapped into the prompt construct.

    Missing residues still occupy positions because the prompt asks the agent
    to build them. Mapping only observed atom-site rows shifted every later
    disulfide by the missing count (eight positions in task 015).
    """
    positions: dict[tuple[str, int, str], int] = {}
    position = 0
    for chain in declared["chain_order"]:
        chain_records = [r for r in selected if r.chain == chain]
        ordered_sites: list[tuple[int, str]] = []
        seen_sites: set[tuple[int, str]] = set()
        for start, end in declared["ranges"][chain]:
            low, high = sorted((start, end))
            # Preserve deposit row order for insertion codes. 1CEB begins 1A,
            # then 1, then 2; lexical sorting silently reversed those first two
            # and changed a real Cys1 disulfide from position 2 to position 1.
            pieces = [(r.number, r.icode) for r in chain_records
                      if low <= r.number <= high]
            missing = [(number, "")
                       for number in declared["build_missing"].get(chain, set())
                       if low <= number <= high
                       and not any(site[0] == number for site in pieces)]
            for site in sorted(missing, reverse=start > end):
                insert_at = next((i for i, present in enumerate(pieces)
                                  if ((present[0] > site[0]) if start <= end
                                      else (present[0] < site[0]))), len(pieces))
                pieces.insert(insert_at, site)
            for site in pieces:
                if site not in seen_sites:
                    ordered_sites.append(site)
                    seen_sites.add(site)
        for number, icode in ordered_sites:
            position += 1
            positions[(chain, number, icode)] = position
    return positions


def _deposit_disulfide_positions(path: pathlib.Path,
                                  declared: dict,
                                  selected: list[Residue]) -> set[tuple[int, int]]:
    """Deposited struct_conn disulfides in the prompt's construct frame."""
    import gemmi

    structure = gemmi.read_structure(str(path))
    position = _deposit_positions(selected, declared)
    pairs = set()
    for connection in structure.connections:
        if connection.type != gemmi.ConnectionType.Disulf:
            continue
        ends = []
        for partner in (connection.partner1, connection.partner2):
            ends.append((str(partner.chain_name).strip(),
                         int(partner.res_id.seqid.num),
                         str(partner.res_id.seqid.icode or "").strip()))
        if all(end in position for end in ends):
            pairs.add(tuple(sorted(position[end] for end in ends)))
    return pairs


def _reference_disulfide_positions(bundle: pathlib.Path) -> set[tuple[int, int]]:
    """Reference S-S pairs from its force-bearing topology, never geometry."""
    from mddatabench.topology import (
        find_reference_topology, read_topology, sulfur_bond_positions)

    # Bond membership does not need coordinates. Loading the topology directly
    # also avoids rejecting task 061 merely because its separately deposited
    # PDB orders 815 atoms differently from its force-bearing prmtop.
    structure = read_topology(find_reference_topology(bundle))
    pairs, _, dropped = sulfur_bond_positions(structure)
    if dropped:
        raise ValueError(
            f"reference topology has {len(dropped)} sulfur bond(s) outside its polymer")
    return {tuple(sorted(pair)) for pair in pairs}


def _difference_detail(label: str, deposit: Counter, reference: Counter) -> str:
    return (f"{label}: deposit {dict(sorted(deposit.items()))}, "
            f"reference {dict(sorted(reference.items()))}")


_METAL_WORDS = {
    "ZN": ("zinc",), "FE": ("iron",), "CU": ("copper",),
    "MN": ("manganese",), "CO": ("cobalt",), "MG": ("magnesium",),
    "CA": ("calcium",),
}


def _component_is_named(body: str, residue: Residue, kind: str) -> bool:
    if _mentions(body, residue.name, cap=kind == "cap"):
        return True
    return any(re.search(rf"\b{word}\b", body, re.I)
               for word in _METAL_WORDS.get(residue.name, ()))


def _connected_metals(path: pathlib.Path, declared: dict,
                      records: list[Residue]) -> list[Residue]:
    """Metals coordinated by struct_conn to a selected polymer residue."""
    import gemmi

    selected = declared["selected"]
    structure = gemmi.read_structure(str(path))
    site_ligands: dict[tuple[str, int, str], set[tuple[str, int, str]]] = {}
    for connection in structure.connections:
        if connection.type != gemmi.ConnectionType.MetalC:
            continue
        partners = (connection.partner1, connection.partner2)
        for metal, polymer in (partners, tuple(reversed(partners))):
            metal_name = str(metal.res_id.name).strip().upper()
            polymer_chain = str(polymer.chain_name).strip()
            polymer_number = int(polymer.res_id.seqid.num)
            if (metal_name in METALS and polymer_chain in selected
                    and polymer_number in selected[polymer_chain]):
                site = (str(metal.chain_name).strip(),
                        int(metal.res_id.seqid.num), metal_name)
                ligand = (polymer_chain, polymer_number,
                          str(polymer.res_id.seqid.icode or "").strip())
                site_ligands.setdefault(site, set()).add(ligand)
    # A single retained contact is not enough to make a crystallographic ion a
    # structural site. 6W9C's second Zn bridges three symmetry copies; after the
    # prompt selects chain C it has one remaining ligand, while the intended
    # Cys4 zinc has four. Counting both falsely accused the prompt of asking for
    # one zinc while the deposit supplied two.
    sites = {site for site, ligands in site_ligands.items() if len(ligands) >= 2}
    return [r for r in records if (r.chain, r.number, r.name) in sites]


def _deposit_components(path: pathlib.Path, records: list[Residue],
                        declared: dict, kind: str) -> list[Residue]:
    occurrences = _occurrences(records, kind)
    if kind == "cap":
        # A capped ligand may be on a non-selected chain (task 042), so caps
        # cannot be filtered to the prompt's polymer chain letters.
        return occurrences
    if kind == "metal":
        connected = _connected_metals(path, declared, records)
        # Some older deposits omit metal coordination records. Same-chain
        # named metals are the conservative fallback, never every crystallising
        # ion in the asymmetric unit.
        if connected:
            return connected
        return [r for r in occurrences
                if r.chain in declared["chains"]
                and _component_is_named(declared["body"], r, kind)]
    # Reference ligands are normalized to LIG, whereas the deposit keeps its
    # chemical component name. Only a name stated by the prompt establishes
    # which of the many crystallisation additives is the intended ligand.
    named = [r for r in occurrences
             if _component_is_named(declared["body"], r, kind)]
    in_selected_chain = [r for r in named if r.chain in declared["chains"]]
    return in_selected_chain or named


def _difference_is_declared(body: str, kind: str) -> bool:
    if kind == "cap":
        return re.search(
            r"\b(?:uncapped|free termin(?:us|i)|remove|drop|without)\b.*\bcap",
            body, re.I) is not None
    if kind == "metal":
        return re.search(
            r"\b(?:remove|drop|without|exclude)\b.*\b(?:metal|zinc|iron|"
            r"copper|manganese|cobalt|magnesium|calcium)\b", body, re.I) is not None
    return re.search(
        r"\b(?:remove|drop|without|exclude|simulate the unmodified)\b",
        body, re.I) is not None


def _kind_is_named(body: str, kind: str) -> bool:
    if kind == "cap":
        return re.search(r"\b(?:ACE|NME|NHE|NH2|NMA|cap|capped|uncapped)\b",
                         body, re.I) is not None
    if kind == "metal":
        words = [name for aliases in _METAL_WORDS.values() for name in aliases]
        return re.search(
            rf"\b(?:metal|{'|'.join(words)}|ZN|FE|CU|MN|CO|MG|CA)\b",
            body, re.I) is not None
    return re.search(r"\b(?:ligand|cofactor|prosthetic group|LIG)\b",
                     body, re.I) is not None


def _component_presence_requested(body: str, residue: Residue, kind: str) -> bool:
    """Whether prose asks for presence, rather than merely discussing state."""
    if kind == "metal":
        noun = r"(?:metal|zinc|iron|copper|manganese|cobalt|magnesium|calcium)"
    elif kind == "cap":
        noun = r"(?:ACE|NME|NHE|NH2|NMA|cap|caps)"
    else:
        noun = rf"(?:{re.escape(residue.name)}|ligand|cofactor|prosthetic group)"
    verb = r"(?:simulate|keep|include|retain|preserve)"
    return (re.search(rf"\b{verb}\b[^.\n]*\b{noun}\b", body, re.I) is not None
            or re.search(rf"\b{noun}\b[^.\n]*\b{verb}\b", body, re.I) is not None
            or (re.search(rf"\b{noun}\b", body, re.I) is not None
                and re.search(r"\bkeep\s+it\b", body, re.I) is not None))


def audit_task_contract(task_dir: str, bundle: str,
                        deposit_cache: str = None) -> dict:
    """Compare one prompt with its reference and every source PDB deposit."""
    task_path = pathlib.Path(task_dir).resolve()
    bundle_path = pathlib.Path(bundle).resolve()
    spec = json.loads((task_path / "task.json").read_text())
    prompt = (task_path / "prompt.md").read_text()
    declared = _declared(prompt)
    reference = _structure_records(bundle_path / "reference.pdb")
    findings = []
    # The stored selection claims to mirror the prompt. Six tasks showed it
    # does not, and because nothing reads the field the disagreement was
    # invisible; report it here so a future consumer inherits the check rather
    # than the defect.
    findings.extend(selection_range_findings(
        prompt, spec["reference"].get("selection") or {}))

    reference_polymer = [r for r in reference if _is_polymer(r)]
    declared_count = sum(len(values) for values in declared["selected"].values())
    declared_lengths = _declared_polymer_lengths(declared)
    reference_lengths = _reference_polymer_lengths(reference)
    # Keep occurrences rather than sets: a second ligand/cap and its site are
    # contract material too. Structural metals are not bulk counterions.
    for kind in ("other", "cap", "metal"):
        for residue in _occurrences(reference, kind):
            mentioned = (_component_is_named(declared["body"], residue, kind)
                         or _kind_is_named(declared["body"], kind))
            if not mentioned:
                findings.append({
                    "kind": f"reference_{kind}_unnamed",
                    "detail": (f"reference contains {residue.name} at "
                               f"{residue.site}, which the prompt never names"),
                    "component": residue.name, "site": residue.site,
                })
            elif not _component_presence_requested(
                    declared["body"], residue, kind):
                findings.append({
                    "kind": f"reference_{kind}_not_requested",
                    "detail": (f"reference contains {residue.name} at "
                               f"{residue.site}; the prompt mentions this "
                               "component or its state but never asks to include it"),
                    "component": residue.name, "site": residue.site,
                })

    pdb_ids = spec.get("reference", {}).get("pdb_ids") or []
    cache = pathlib.Path(deposit_cache or (task_path.parent.parent / "_deposits"))
    reference_counts = {kind: _occurrence_counts(reference, kind)
                        for kind in ("other", "cap", "metal")}
    reference_ss = None
    try:
        reference_ss = _reference_disulfide_positions(bundle_path)
    except (Exception, SystemExit) as exc:
        findings.append({"kind": "reference_topology_unreadable",
                         "detail": str(exc), "component": "topology"})

    for pdb_id in pdb_ids:  # every source matters; the prototype used [:1]
        deposit_file = _deposit_path(pdb_id, cache)
        if deposit_file is None:
            findings.append({"kind": "deposit_unavailable",
                             "detail": f"could not fetch {pdb_id} to compare",
                             "component": pdb_id, "pdb_id": pdb_id})
            continue
        deposit = _structure_records(deposit_file)
        selected = _selected_deposit(deposit, declared)
        if declared_count and not selected:
            findings.append({
                "kind": "deposit_polymer_selection_empty",
                "detail": (f"{pdb_id}: none of the prompt's chain/range selection "
                           "exists in the deposit"),
                "component": "polymer", "pdb_id": pdb_id,
            })
        expected_sites = {(r.chain, r.number, r.icode) for r in selected}
        observed_sites = {(r.chain, r.number, r.icode) for r in selected}
        for chain, sites in declared["build_sites"].items():
            in_selection = declared["selected"].get(chain, set())
            omitted = {value for start, end in declared["excluded"].get(chain, [])
                       for value in range(min(start, end), max(start, end) + 1)}
            for number, icode in sorted(sites):
                # These three used to be dropped by a silent membership test,
                # which is how 011_membrane_6kuy came to tell an agent both to
                # leave residues 173-182 out and to build them. A build site the
                # prompt contradicts is a defect in the prompt, not a residue to
                # quietly skip.
                if number in omitted:
                    findings.append({
                        "kind": "prompt_build_site_is_excluded",
                        "detail": (f"{pdb_id}: the prompt asks to build "
                                   f"{chain}:{number}{icode} and also to "
                                   "leave it out"),
                        "component": "polymer", "pdb_id": pdb_id,
                        "site": f"{chain}:{number}{icode}",
                    })
                    continue
                if number not in in_selection:
                    findings.append({
                        "kind": "prompt_build_site_outside_selection",
                        "detail": (f"{pdb_id}: the prompt asks to build "
                                   f"{chain}:{number}{icode}, which no stated "
                                   "range covers"),
                        "component": "polymer", "pdb_id": pdb_id,
                        "site": f"{chain}:{number}{icode}",
                    })
                    continue
                if (chain, number, icode) in observed_sites:
                    findings.append({
                        "kind": "prompt_build_site_is_observed",
                        "detail": (f"{pdb_id}: the prompt asks to build "
                                   f"{chain}:{number}{icode}, which the "
                                   "deposit resolves"),
                        "component": "polymer", "pdb_id": pdb_id,
                        "site": f"{chain}:{number}{icode}",
                    })
                    continue
                expected_sites.add((chain, number, icode))
        if expected_sites and len(expected_sites) != len(reference_polymer):
            findings.append({
                "kind": "reference_polymer_selection_mismatch",
                "detail": (f"{pdb_id}: the deposit contributes {len(selected)} "
                           "selected polymer residue(s) and the prompt explicitly "
                           f"builds {len(expected_sites) - len(selected)}, but the "
                           f"reference contains {len(reference_polymer)}"),
                "component": "polymer", "pdb_id": pdb_id,
            })

        for kind in ("other", "cap", "metal"):
            deposit_components = _deposit_components(
                deposit_file, deposit, declared, kind)
            if (kind != "cap" and not reference_counts[kind]
                    and not _kind_is_named(declared["body"], kind)):
                continue
            if (kind == "other" and reference_counts[kind]
                    and not _kind_is_named(declared["body"], kind)):
                # The prompt/reference defect is already the occurrence-level
                # reference_other_unnamed finding. Comparing normalized LIG to
                # every crystallisation additive would add noise, not evidence.
                continue
            deposit_counts = Counter(r.name for r in deposit_components)
            # A reference ligand is normalized to LIG. Count is comparable to
            # a named deposit component; its residue name is deliberately not.
            reference_comparison = reference_counts[kind]
            if kind == "other" and deposit_components and reference_counts[kind]:
                deposit_counts = Counter({"named_component": len(deposit_components)})
                reference_comparison = Counter(
                    {"named_component": sum(reference_counts[kind].values())})
            if (deposit_counts != reference_comparison
                    and not _difference_is_declared(declared["body"], kind)):
                findings.append({
                    "kind": f"deposit_reference_{kind}_mismatch",
                    "detail": f"{pdb_id}: " + _difference_detail(
                        kind, deposit_counts, reference_comparison),
                    "component": kind, "pdb_id": pdb_id,
                    "deposit_sites": [f"{r.name}@{r.site}"
                                      for r in deposit_components],
                    "reference_sites": [f"{r.name}@{r.site}"
                                        for r in _occurrences(reference, kind)],
                })

        if reference_ss is not None:
            deposit_ss = _deposit_disulfide_positions(
                deposit_file, declared, selected)
            if deposit_ss != reference_ss and not re.search(
                    r"\b(?:disulfide|reduced|S[–—-]S)\b", declared["body"], re.I):
                findings.append({
                    "kind": "deposit_reference_disulfide_mismatch",
                    "detail": (f"{pdb_id}: deposit struct_conn pairs "
                               f"{sorted(deposit_ss)} differ from reference "
                               f"topology pairs {sorted(reference_ss)}, and the "
                               "prompt does not state the difference"),
                    "component": "disulfide", "pdb_id": pdb_id,
                })

    by_kind = {}
    for residue in reference:
        by_kind.setdefault(_classify(residue.name), set()).add(residue.name)
    return {
        "success": not findings,
        "task_id": spec.get("task_id", task_path.name),
        "declared_chains": sorted(declared["chains"]),
        "declared_polymer_residues": declared_count,
        "reference_polymer_residues": len(reference_polymer),
        "declared_polymer_lengths": declared_lengths,
        "reference_polymer_lengths": reference_lengths,
        "reference_component_kinds": {k: sorted(v)
                                      for k, v in sorted(by_kind.items())},
        "findings": findings,
    }


def audit_task_cast(dataset_dir: str, bundle_root: str,
                    deposit_cache: str = None) -> dict:
    """Run :func:`audit_task_contract` over a whole dataset directory."""
    dataset = pathlib.Path(dataset_dir).resolve()
    root = pathlib.Path(bundle_root).resolve()
    rows, clean = [], 0
    for task_path in sorted(p for p in (dataset / "tasks").iterdir() if p.is_dir()):
        spec = json.loads((task_path / "task.json").read_text())["reference"]
        bundle = root / f'{spec["node"]}_{spec["accession"]}'
        if not bundle.is_dir():
            rows.append({"task_id": task_path.name, "findings":
                         [{"kind": "bundle_missing", "detail": str(bundle)}]})
            continue
        report = audit_task_contract(str(task_path), str(bundle), deposit_cache)
        if report["findings"]:
            rows.append({"task_id": report["task_id"],
                         "findings": report["findings"]})
        else:
            clean += 1
    return {"success": not rows, "tasks_clean": clean,
            "tasks_with_findings": len(rows), "tasks": rows}
