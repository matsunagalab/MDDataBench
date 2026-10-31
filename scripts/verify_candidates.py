#!/usr/bin/env python3
"""Verify MDDB test-set candidates against their PDB deposits (no MD, no agent).

Step 2 of the held-out test-set selection (docs/test-set-selection.md).  It is
imported by ``select_test_set.py``, which verifies candidates lazily in greedy
order, and it can also be run on its own for a list of ``node:accession``.

For one candidate it:

1. downloads (and caches under ``<workdir>/cache``) the MDDB reference
   ``structure.pdb`` and the ``rmsds`` analysis, and the RCSB deposit in PDB
   format;
2. extracts the reference polymer chains (geometry split, as the scorer does:
   ``mddatabench.composition.split_monomers``), each as a one-letter sequence;
   residues outside a chain (ligands, lipids, ions) are dropped, and a
   reference whose chains keep any residue other than a standard one, a named
   ionisation/bonding variant, or a terminal cap is rejected;
3. aligns every reference chain to the deposit's SEQRES -- by sequence, never by
   residue number -- with unknown SEQRES residues kept as an ``X`` wildcard, and
   classifies it as in docs/memo.md 2026-08-23: a contiguous match
   (``SEQRES に連続一致``), two spans with a removed insert
   (``SEQRES に 2 区間 (融合部除去)``), an approximate contiguous match with
   listed substitutions (``詳細`` / ``差分``), or ``説明不能`` (unexplained);
4. writes the verification record in exactly the shape
   ``mddatabench._task_builder.selection(record, deposit)`` consumes, and calls
   ``selection()`` on it;
5. measures stability from MDDB's own ``rmsds`` (first-frame reference, first
   group): last-third mean and drift (last-third mean minus first-third mean);
6. lists metal ions the reference keeps and whether each is bound (within
   3.5 A of a protein/nucleic heavy atom: N, O or S).

Usage::

    PYTHONPATH=<MDDataBench> python3 scripts/verify_candidates.py \
        --workdir /data1/rkp00079/rku00161/testset-20261031 mmb:A0001 bsc:A02K9
"""

from __future__ import annotations

import argparse
import json
import math
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

import numpy as np

from mddatabench import _task_builder as tb
from mddatabench import composition as cp
from mddatabench.reference import NODES

USER_AGENT = {"User-Agent": "MDDataBench-testset-verify/1.0"}

# --- downloads ---------------------------------------------------------------


def _get(url, timeout=600, retries=5, pause=2.0, binary=False):
    last = None
    for attempt in range(retries):
        try:
            request = urllib.request.Request(url, headers=USER_AGENT)
            with urllib.request.urlopen(request, timeout=timeout) as response:
                data = response.read()
                return data if binary else data.decode("utf-8", errors="replace")
        except urllib.error.HTTPError as exc:
            last = exc
            if exc.code in (404, 410):
                raise
        except Exception as exc:                                    # noqa: BLE001
            last = exc
        time.sleep(pause * (2 ** attempt))
    raise RuntimeError(f"{url}: {type(last).__name__}: {last}")


def cached_text(path: Path, url: str, timeout=600) -> str:
    if path.exists() and path.stat().st_size > 0:
        return path.read_text(errors="replace")
    text = _get(url, timeout=timeout)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(text)
    tmp.rename(path)
    return text


def cached_json(path: Path, url: str, timeout=600):
    return json.loads(cached_text(path, url, timeout))


def reference_structure(workdir: Path, node: str, accession: str) -> Path:
    path = workdir / "cache" / "structures" / node / f"{accession}.pdb"
    cached_text(path, f"{NODES[node]}/{accession}/structure")
    return path


def deposit_pdb(workdir: Path, pdb_id: str) -> Path | None:
    """The deposit in PDB format, or None when RCSB has no PDB-format file."""
    path = workdir / "cache" / "rcsb" / "pdb" / f"{pdb_id.upper()}.pdb"
    missing = path.with_suffix(".missing")
    if missing.exists():
        return None
    try:
        cached_text(path, f"https://files.rcsb.org/download/{pdb_id.upper()}.pdb")
    except urllib.error.HTTPError as exc:
        if exc.code == 404:
            missing.parent.mkdir(parents=True, exist_ok=True)
            missing.write_text("no PDB-format file at RCSB (large or mmCIF-only entry)\n")
            return None
        raise
    return path


def rmsds(workdir: Path, node: str, accession: str):
    path = workdir / "cache" / "analyses" / node / f"{accession}_rmsds.json"
    return cached_json(path, f"{NODES[node]}/{accession}/analyses/rmsds")


# --- reference chains --------------------------------------------------------

# CHARMM nucleotide names; DNA or RNA is decided by the O2' atom.
CHARMM_NUCLEIC = {"ADE": "a", "GUA": "g", "CYT": "c", "THY": "t", "URA": "u"}

# Polymer residues a reference may carry (rule v4): the standard amino acids and
# nucleotides, their named ionisation / tautomer / bonding / terminal variants,
# and -- at a chain end only -- the force-field terminal caps.  Anything else in
# a reference polymer (MSE kept as MSE, 2OUE's MRA and RAP) is a non-standard
# residue the reference kept, and the candidate is rejected.
STANDARD_AMINO = {"ALA", "ARG", "ASN", "ASP", "CYS", "GLN", "GLU", "GLY", "HIS", "ILE", "LEU",
                  "LYS", "MET", "PHE", "PRO", "SER", "THR", "TRP", "TYR", "VAL"}
ALLOWED_POLYMER = (STANDARD_AMINO | set(cp.CANONICAL_RESIDUE) | set(tb.NUCLEIC)
                   | set(CHARMM_NUCLEIC))
TERMINAL_CAPS = {"ACE", "NME", "NMA", "NHE", "NH2"}
PROTEIN_CODES = set("ACDEFGHIKLMNPQRSTVWY")


def residue_code(residue):
    """(polymer type, one-letter code) for a residue, or None for a non-polymer."""
    name = residue.name.strip().upper()
    canonical = cp.CANONICAL_RESIDUE.get(name, name)
    if canonical in tb.AMINO:
        return "protein", tb.AMINO[canonical]
    if canonical in tb.NUCLEIC or name in tb.NUCLEIC:
        code = tb.NUCLEIC.get(name) or tb.NUCLEIC.get(canonical)
        return ("dna", code) if code.islower() else ("rna", code)
    if name in CHARMM_NUCLEIC:
        rna = residue.atom("O2'") is not None or residue.atom("O2*") is not None
        code = CHARMM_NUCLEIC[name]
        return ("rna", code.upper()) if rna else ("dna", code)
    return None


def reference_polymers(path: Path) -> list[dict]:
    """Polymer chains of a reference structure, split where the backbone breaks.

    A chain is a covalently connected run (``composition.split_monomers``), so
    a fusion construct the reference ligated is one chain and two pieces it
    kept apart are two.  Residues that are not amino acids or nucleotides are
    dropped -- unknown ATOM residues are ligands or lipids (memo 2026-08-23) --
    except inside a chain: an unknown residue bonded into the backbone between
    two standard ones is a modified residue the reference kept (2OUE's
    2'-O-methyladenosine ``MRA``), and it is written ``X`` so the chain is not
    cut there.  Unknown residues at a chain's ends (caps) are dropped.
    """
    residues = cp.read_residues(str(path))
    out, labels = [], {}
    for monomer in cp.split_monomers(residues):
        coded = [(r, residue_code(r)) for r in monomer]
        known = [i for i, (_, c) in enumerate(coded) if c]
        if not known:
            continue
        ends = coded[:known[0]] + coded[known[-1] + 1:]
        coded = coded[known[0]:known[-1] + 1]
        nonstandard = [f"{r.name.strip()}{r.resseq}" for r, _ in coded
                       if r.name.strip().upper() not in ALLOWED_POLYMER]
        nonstandard += [f"{r.name.strip()}{r.resseq}" for r, _ in ends
                        if r.name.strip().upper() not in TERMINAL_CAPS]
        types = {c[0] for _, c in coded if c}
        kind_of_x = "protein" if types == {"protein"} else ("dna" if "dna" in types else "rna")
        coded = [(r, c if c else (kind_of_x, "X")) for r, c in coded]
        kind = "protein" if types == {"protein"} else (
            "dna" if types == {"dna"} else "rna" if types == {"rna"} else "mixed")
        chain = coded[0][0].chain.strip() or "_"
        labels[chain] = labels.get(chain, 0) + 1
        label = chain if labels[chain] == 1 else f"{chain}.{labels[chain]}"
        out.append({"label": label, "chain": chain, "type": kind,
                    "sequence": "".join(c[1] for _, c in coded),
                    "first": coded[0][0].resseq, "last": coded[-1][0].resseq,
                    "nonstandard": nonstandard})
    return out


def metals_in_reference(path: Path, cutoff: float = 3.5) -> list[dict]:
    """Metal ions the reference keeps, and whether a polymer atom binds each."""
    metals = cp.read_metals(str(path))
    if not metals:
        return []
    donors = []
    for line in open(path, errors="replace"):
        if not line.startswith(("ATOM", "HETATM")):
            continue
        name = line[17:21].strip().upper()
        if name in cp.SOLVENT_RESIDUES or name in cp.LIPID_RESIDUES:
            continue
        element = (line[76:78].strip() or line[12:16].strip()[:1]).upper()
        if element in ("N", "O", "S"):
            donors.append((f"{name}{line[22:27].strip()}:{line[12:16].strip()}",
                           [float(line[30 + 8 * i:38 + 8 * i]) for i in range(3)]))
    xyz = np.array([d[1] for d in donors]) if donors else np.zeros((0, 3))
    out = []
    for label, position in metals:
        if len(xyz):
            dist = np.linalg.norm(xyz - position, axis=1)
            close = sorted((float(dist[i]), donors[i][0]) for i in np.where(dist <= cutoff)[0])
        else:
            close = []
        out.append({"metal": label, "bound": bool(close),
                    "ligands": [f"{who} {d:.2f}" for d, who in close[:6]]})
    return out


# --- alignment to SEQRES -------------------------------------------------------


def _matches(seq, sub, start):
    """Equal, or either side unknown: an X in SEQRES is a residue the deposit
    names non-standardly, an X in the reference a modified residue it kept."""
    return all(s == q or s == "X" or q == "X" for s, q in zip(seq[start:start + len(sub)], sub))


def contiguous_hits(seqres, query):
    if len(query) > len(seqres):
        return []
    return [i for i in range(len(seqres) - len(query) + 1) if _matches(seqres, query, i)]


def two_span_hit(seqres, query, min_piece=5):
    """query = query[:k] + query[k:], placed at p1 < p2 with a gap between them."""
    best = None
    for k in range(min_piece, len(query) - min_piece + 1):
        left, right = query[:k], query[k:]
        for p1 in contiguous_hits(seqres, left):
            for p2 in contiguous_hits(seqres[p1 + k:], right):
                gap = p2
                start2 = p1 + k + p2
                if gap <= 0:
                    continue
                candidate = (gap, p1, k, start2)
                # Fewest removed residues first; ties: earliest placement.
                if best is None or candidate < best:
                    best = candidate
        if best is not None and best[0] == 0:
            break
    if best is None:
        return None
    gap, p1, k, start2 = best
    return {"span1": (p1 + 1, p1 + k), "span2": (start2 + 1, start2 + len(query) - k),
            "removed": gap}


def approximate_hit(seqres, query, max_mismatch):
    best = None
    for i in range(len(seqres) - len(query) + 1):
        diffs = []
        for j, q in enumerate(query):
            s = seqres[i + j]
            if s != q and s != "X" and q != "X":
                diffs.append(j)
                if len(diffs) > max_mismatch:
                    break
        if len(diffs) <= max_mismatch and (best is None or len(diffs) < len(best[1])):
            best = (i, diffs)
    return best


def max_substitutions(length):
    """Substitutions tolerated in an approximate match: 2, or 2 % of the chain."""
    return max(2, int(math.floor(0.02 * length)))


def observed_coverage(deposit, chain, lo, hi):
    mapping = tb.seqres_to_auth(str(deposit), chain)
    return sum(1 for p in range(lo, hi + 1) if p in mapping)


def build_record(reference_pdb: Path, deposit: Path) -> tuple[dict, list[dict]]:
    """The selection() input record for one reference against its deposit."""
    full = tb.seqres(str(deposit))
    chains = reference_polymers(reference_pdb)
    record = {"鎖": [], "詳細": []}
    for entry in chains:
        query = entry["sequence"]
        base = {"参照鎖": entry["label"], "長さ": len(query)}
        exact = []
        for chain_id, seqres in full.items():
            for hit in contiguous_hits(seqres, query):
                lo, hi = hit + 1, hit + len(query)
                cover = observed_coverage(deposit, chain_id, lo, hi)
                exact.append((-cover, chain_id, lo, hi))
        if exact:
            # Most observed residues inside the span first, then the deposit's
            # own chain order: assign_distinct_chains later moves twins apart.
            order = list(full)
            exact.sort(key=lambda x: (x[0], order.index(x[1]), x[2]))
            _, chain_id, lo, hi = exact[0]
            record["鎖"].append(dict(base, 寄託鎖=chain_id, 種別="SEQRES に連続一致",
                                    SEQRES位置=f"{lo}-{hi}"))
            entry["match"] = "contiguous"
            continue
        split = None
        for chain_id, seqres in full.items():
            hit = two_span_hit(seqres, query)
            if hit and (split is None or hit["removed"] < split[1]["removed"]):
                split = (chain_id, hit)
        if split:
            chain_id, hit = split
            record["鎖"].append(dict(
                base, 寄託鎖=chain_id, 種別="SEQRES に 2 区間 (融合部除去)",
                区間1="{}-{}".format(*hit["span1"]), 区間2="{}-{}".format(*hit["span2"]),
                除去長=hit["removed"]))
            entry["match"] = "two_spans"
            continue
        approx = None
        for chain_id, seqres in full.items():
            hit = approximate_hit(seqres, query, max_substitutions(len(query)))
            if hit and (approx is None or len(hit[1]) < len(approx[1][1])):
                approx = (chain_id, hit)
        record["鎖"].append(dict(base, 寄託鎖=approx[0] if approx else None, 種別="説明不能"))
        if approx:
            chain_id, (start, diffs) = approx
            seqres = full[chain_id]
            record["詳細"].append(dict(
                base, 寄託鎖=chain_id,
                SEQRES位置=f"{start + 1}-{start + len(query)}",
                差分=[f"{start + j + 1}:{seqres[start + j]}->{query[j]}" for j in diffs]))
            entry["match"] = "approximate"
        else:
            entry["match"] = "unexplained"
    return record, chains


def stability(series: dict) -> dict:
    data = [e for e in (series.get("data") or []) if e.get("values")]
    first = next((e for e in data if e.get("reference") == "firstframe"), data[0] if data else None)
    if not first:
        return {"last_third_rmsd_angstrom": None, "drift_angstrom": None, "frames": 0}
    values = [float(v) for v in first["values"]]
    n = len(values)
    last = values[2 * n // 3:]
    head = values[:n // 3] or values[:1]
    mean_last = sum(last) / len(last)
    return {"last_third_rmsd_angstrom": round(mean_last, 3),
            "drift_angstrom": round(mean_last - sum(head) / len(head), 3),
            "frames": n, "series": {k: first.get(k) for k in ("reference", "group")}}


def verify(workdir: Path, node: str, accession: str, pdb_id: str) -> dict:
    """Everything the selection needs to know about one candidate."""
    out = {"node": node, "accession": accession, "pdb_id": pdb_id}
    reference = reference_structure(workdir, node, accession)
    try:
        out["stability"] = stability(rmsds(workdir, node, accession))
    except urllib.error.HTTPError as exc:
        out.update(verdict="reject", reason=f"MDDB serves no rmsds analysis (HTTP {exc.code}); "
                                             "the reference's stability cannot be measured")
        return out
    deposit = deposit_pdb(workdir, pdb_id)
    chains = reference_polymers(reference)
    out["reference_chains"] = [{k: c[k] for k in ("label", "chain", "type", "sequence")} for c in chains]
    out["reference_metals"] = metals_in_reference(reference)
    kept = [f"{c['label']}:{name}" for c in chains for name in c["nonstandard"]]
    out["nonstandard_polymer_residues"] = kept
    if kept:
        out.update(verdict="reject", reason=f"reference keeps non-standard polymer residue(s) {kept}")
        return out
    if deposit is None:
        out.update(verdict="reject", reason="no PDB-format deposit at RCSB")
        return out
    record, chains = build_record(reference, deposit)
    out["record"] = record
    out["chain_matches"] = {c["label"]: c.get("match") for c in chains}
    unexplained = [c["label"] for c in chains if c.get("match") == "unexplained"]
    if not chains:
        out.update(verdict="reject", reason="reference has no polymer chain")
        return out
    if unexplained:
        out.update(verdict="reject", reason=f"unexplained reference chain(s) {unexplained}")
        return out
    try:
        out["selection"] = tb.selection(record, str(deposit))
    except SystemExit as exc:
        out.update(verdict="reject", reason=f"selection() refused: {exc}")
        return out
    except Exception as exc:                                        # noqa: BLE001
        out.update(verdict="reject", reason=f"selection() failed: {type(exc).__name__}: {exc}")
        return out
    out["verdict"] = "ok"
    return out


def validate_cast(workdir: Path, tasks_dir: Path, bundles: Path) -> dict:
    """Re-derive the 98 shipped selections with this record builder.

    The script that produced the original records was never committed, so the
    builder here is checked against what it produced: for every shipped task the
    record is rebuilt from the cached bundle's reference.pdb and the deposit,
    ``selection()`` is run on it, and the per-deposit-chain ranges are compared
    with ``reference.selection.ranges`` in task.json.
    """
    rows = []
    for task_json in sorted(tasks_dir.glob("*/task.json")):
        task = json.loads(task_json.read_text())
        ref = task["reference"]
        pdb_id = ref["pdb_ids"][0]
        bundle = bundles / f"{ref['node']}_{ref['accession']}" / "reference.pdb"
        row = {"task": task["task_id"], "pdb": pdb_id}
        try:
            deposit = deposit_pdb(workdir, pdb_id)
            if deposit is None:
                row.update(status="no_pdb_format")
                rows.append(row)
                continue
            record, chains = build_record(bundle, deposit)
            row["matches"] = [c.get("match") for c in chains]
            chosen = tb.selection(record, str(deposit))
            mine = {}
            for entry in chosen:
                mine.setdefault(entry["deposit_chain"], []).extend(
                    [[str(a), str(b)] for a, b in entry["ranges"]])
            shipped = {k: [[str(a), str(b)] for a, b in v]
                       for k, v in (ref.get("selection") or {}).get("ranges", {}).items()}
            norm = lambda d: sorted((k, sorted(map(tuple, v))) for k, v in d.items())  # noqa: E731
            row["mine"], row["shipped"] = mine, shipped
            if norm(mine) == norm(shipped):
                row["status"] = "identical"
            elif sorted(sorted(map(tuple, v)) for v in mine.values()) == \
                    sorted(sorted(map(tuple, v)) for v in shipped.values()):
                row["status"] = "same_ranges_other_chain_ids"
            else:
                row["status"] = "differs"
        except BaseException as exc:                                # noqa: BLE001
            row.update(status="error", error=f"{type(exc).__name__}: {exc}")
        rows.append(row)
    summary = {}
    for row in rows:
        summary[row["status"]] = summary.get(row["status"], 0) + 1
    return {"summary": summary, "rows": rows}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--workdir", default="/data1/rkp00079/rku00161/testset-20261031")
    parser.add_argument("--validate-cast", action="store_true",
                        help="rebuild the shipped 98 selections and compare")
    parser.add_argument("--tasks", default=str(Path(__file__).resolve().parents[1]
                                              / "benchmarks" / "mddatabench" / "tasks"))
    parser.add_argument("--bundles", default="/data1/rkp00079/rku00161/references")
    parser.add_argument("targets", nargs="*", help="node:accession[:PDBID]")
    args = parser.parse_args(argv)
    workdir = Path(args.workdir)
    if args.validate_cast:
        result = validate_cast(workdir, Path(args.tasks), Path(args.bundles))
        (workdir / "selection").mkdir(parents=True, exist_ok=True)
        (workdir / "selection" / "builder_validation_on_cast.json").write_text(
            json.dumps(result, indent=1, ensure_ascii=False, default=str))
        print(json.dumps(result["summary"]))
        for row in result["rows"]:
            if row["status"] != "identical":
                print(row["task"], row["status"], row.get("matches"), row.get("mine"),
                      row.get("shipped"), row.get("error", ""))
        return 0
    for target in args.targets:
        node, accession, *rest = target.split(":")
        pdb_id = rest[0] if rest else None
        if not pdb_id:
            project = _get(f"{NODES[node]}/{accession}")
            pdb_id = (json.loads(project).get("metadata") or {}).get("PDBIDS")[0]
        print(json.dumps(verify(workdir, node, accession, pdb_id), ensure_ascii=False, indent=1,
                         default=str))


if __name__ == "__main__":
    sys.exit(main())
