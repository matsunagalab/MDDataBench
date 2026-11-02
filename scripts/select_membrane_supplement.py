#!/usr/bin/env python3
"""Choose the one membrane task that supplements test-v7 (set ``v7m``).

Applies the rule of docs/test-set-v7-selection.md, Part 5, which was written down
before this script ran.  Reads test-v7's pool and listing, the 158 task contracts
and their bundles, RCSB entries and entity sequences, MDPrepBench's PDB IDs,
MDStudyBench S01 and the mdclaw checkout's text.  It runs no MD, MDClaw or agent
and reads no campaign result.

    PYTHONPATH=<MDDataBench> python3 scripts/select_membrane_supplement.py [--need 4]

Writes under the set's work directory:

``selection/candidates.json``     the whole funnel: every membrane project, its
                                  ordering key and the step that removed it.
``selection/selection_log.json``  every candidate tried, kept or dropped.
``selection/selected.json``       the first candidate that passes as the pick, the
                                  rest as reserves, in the shape ``build_test_tasks.plan``
                                  reads.  A candidate named in ``not_statable`` stays
                                  in the list: ``plan`` moves past it, as for v6 and v7.
"""

from __future__ import annotations

import argparse
import collections
import json
import re
import subprocess
import sys
import time
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import heldout_sets as hsets                                         # noqa: E402
import select_test_set as sts                                        # noqa: E402
import verify_candidates as vc                                       # noqa: E402

from mddatabench import _task_builder as tb                         # noqa: E402
from mddatabench import composition as cp                           # noqa: E402

MAX_RESIDUES = 1700
MAX_ATOMS = 120_000
THRESHOLD = sts.THRESHOLD
CHAIN_MIN = sts.CHAIN_MIN
RMSD_MAX = sts.RMSD_MAX

# Shared machinery, exempt against entries the mdclaw checkout only mentions
# (rule 2): the deposit entity's own description names a heterotrimeric
# G-protein subunit or scFv16.
MACHINERY = re.compile(
    r"guanine[- ]nucleotide[- ]binding"
    r"|\bG[- ]?(alpha|beta|gamma)\b|\bG\(?[iosqtz1-9/]*\)?[- ]?subunit"
    r"|\bg\s*alpha|\bg\s*beta|\bg\s*gamma|\bmini[- ]?g|\bscfv[- ]?16\b"
    r"|single[- ]chain (fv|variable fragment|antibody)[- ]?(fragment )?(scfv)?[- ]?16\b",
    re.I)

ENTITY_QUERY = """query($ids: [String!]!) { entries(entry_ids: $ids) { rcsb_id
  polymer_entities { rcsb_polymer_entity { pdbx_description }
    entity_poly { rcsb_entity_polymer_type pdbx_seq_one_letter_code_can pdbx_strand_id } } } }"""


def is_machinery(description) -> bool:
    """Every part of the entity is machinery; a receptor fused to a Gs peptide is not."""
    parts = [part for part in str(description or "").split(",") if part.strip()]
    return bool(parts) and all(MACHINERY.search(part) for part in parts)


def entities(workdir: Path, pdb_ids):
    """Each deposit's polymer entities: description, sequence, chains (cached)."""
    path = workdir / "cache" / "rcsb" / "entity_descriptions.json"
    data = json.loads(path.read_text()) if path.exists() else {}
    todo = sorted(set(pdb_ids) - set(data))
    for start in range(0, len(todo), 100):
        batch = todo[start:start + 100]
        body = json.dumps({"query": ENTITY_QUERY, "variables": {"ids": batch}}).encode()
        request = urllib.request.Request(sts.GRAPHQL, data=body, headers={
            "Content-Type": "application/json", **vc.USER_AGENT})
        with urllib.request.urlopen(request, timeout=300) as response:
            found = json.load(response)
        by_id = {e["rcsb_id"].upper(): e for e in (found.get("data") or {}).get("entries") or [] if e}
        for pdb in batch:
            rows = []
            for poly in (by_id.get(pdb) or {}).get("polymer_entities") or []:
                ep = poly.get("entity_poly") or {}
                rows.append({"description": (poly.get("rcsb_polymer_entity") or {}).get("pdbx_description"),
                             "type": ep.get("rcsb_entity_polymer_type"),
                             "sequence": (ep.get("pdbx_seq_one_letter_code_can") or "").replace("\n", ""),
                             "chains": ep.get("pdbx_strand_id")})
            data[pdb] = rows
    if todo:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(data))
    return data


def entity_of(sequence, rows):
    """The deposit entity a chain aligns to: largest 3-mer containment, then longest."""
    mine = sts.kmer_set([("protein", sequence)])
    best, score = None, -1.0
    for row in rows:
        if row.get("type") != "Protein":
            continue
        value = sts.containment(mine, sts.kmer_set([("protein", row["sequence"])]))
        if value > score or (value == score and best and len(row["sequence"]) > len(best["sequence"])):
            best, score = row, value
    return best, score


def chain_max(per_chain, members, skip=()):
    """Largest containment of any chain >= 30 residues against any member's chain."""
    top = (0.0, None, None)
    for mine in per_chain:
        if mine["length"] < CHAIN_MIN or mine["label"] in skip:
            continue
        for member in members:
            for theirs in member["chain_kmers"]:
                value = sts.containment(mine["kmers"], theirs["kmers"])
                if value > top[0]:
                    top = (value, member["task_id"], f"{mine['label']}~{theirs['label']}")
    return top


def whole_max(chains, members, skip=()):
    kmers = sts.kmer_set([(t, s) for label, t, s in chains if label not in skip])
    return max(((sts.containment(kmers, m["kmers"]), m["task_id"]) for m in members),
               default=(0.0, None))


def assess(chains, rows, tasks, hard, mention_only):
    """The sequence rules of step 2 on one list of (label, type, sequence)."""
    per_chain = sts.chain_kmers(chains)
    exempt, mapped = [], {}
    for label, kind, sequence in chains:
        if kind != "protein":
            continue
        entity, score = entity_of(sequence, rows)
        mapped[label] = {"description": (entity or {}).get("description"),
                         "chains": (entity or {}).get("chains"), "containment": round(score, 3)}
        if entity and is_machinery(entity["description"]):
            exempt.append(label)
    task_chain = chain_max(per_chain, tasks)
    hard_chain, hard_whole = chain_max(per_chain, hard), whole_max(chains, hard)
    mention_chain = chain_max(per_chain, mention_only, skip=exempt)
    mention_whole = whole_max(chains, mention_only, skip=exempt)
    mention_chain_all = chain_max(per_chain, mention_only)
    failures = []
    if hard_whole[0] >= THRESHOLD:
        failures.append(f"whole system {hard_whole[0]:.2f} against {hard_whole[1]}")
    if hard_chain[0] >= THRESHOLD:
        failures.append(f"chain {hard_chain[2]} {hard_chain[0]:.2f} against {hard_chain[1]}")
    if mention_whole[0] >= THRESHOLD:
        failures.append(f"whole system {mention_whole[0]:.2f} against the mention {mention_whole[1]}")
    if mention_chain[0] >= THRESHOLD:
        failures.append(f"chain {mention_chain[2]} {mention_chain[0]:.2f} against the mention "
                        f"{mention_chain[1]}")
    return {"max_chain_vs_tasks": round(task_chain[0], 4), "max_chain_vs_tasks_at": task_chain[1:],
            "whole_vs_hard": (round(hard_whole[0], 4), hard_whole[1]),
            "chain_vs_hard": (round(hard_chain[0], 4), *hard_chain[1:]),
            "whole_vs_mentions_without_exempt": (round(mention_whole[0], 4), mention_whole[1]),
            "chain_vs_mentions_without_exempt": (round(mention_chain[0], 4), *mention_chain[1:]),
            "chain_vs_mentions_all_chains": (round(mention_chain_all[0], 4), *mention_chain_all[1:]),
            "exempt_chains": exempt, "chain_entities": mapped, "failures": failures,
            "_order": task_chain[0]}


def force_field_problem(meta, reference_pdb):
    """Step 4, buildable force field: the field, and every lipid of the reference."""
    fields = meta.get("FF") or []
    fields = fields if isinstance(fields, list) else [fields]
    charmm = any(str(f).upper().startswith("CHARMM36") for f in fields)
    if not charmm and not tb.buildable_force_field(fields):
        return f"force field {fields} is neither CHARMM36-family nor one the builder names"
    lipids = {name.upper(): count for name, count in cp.lipid_species(str(reference_pdb)).items()}
    # The file truncates to three columns; what the project lists is the full name.
    listed = set(meta.get("RSNAME") or []) & sts.LIPID_NAMES
    if not lipids:
        return "the scorer finds no lipid in the reference"
    unstated = sorted(name for name in listed if name not in tb.LIPIDS)
    if unstated:
        return f"lipids the builder cannot state: {unstated}"
    undecomposed = sorted(name for name in listed if name not in cp.LIPID_COMPONENTS)
    if undecomposed:
        return f"lipids the scorer cannot decompose: {undecomposed}"
    return None


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--need", type=int, default=4,
                        help="stop after this many distinct PDB IDs pass step 4 (pick + 3)")
    parser.add_argument("--screen-only", action="store_true")
    parser.add_argument("--max-atoms", type=int, default=MAX_ATOMS,
                        help="atom cap of step 3 (rule as written: 120,000)")
    args = parser.parse_args(argv)
    hs = hsets.get("v7m")
    workdir, pool_dir = hs.workdir, hsets.V7.workdir
    log = lambda msg: print(msg, file=sys.stderr, flush=True)       # noqa: E731

    eligible = json.loads((pool_dir / "selection" / "eligible.json").read_text())
    index = sts.listing_index(pool_dir)
    cast = sts.load_cast(workdir, index, hs)
    tasks = [c for c in cast if c["role"] in ("cast", "previous_test")]
    external, mentions = sts.load_external(workdir, hs)
    prep = set(hs.mdprepbench_pdbs)
    hard = cast + [e for e in external if e["pdb"] in prep or e["pdb"] is None]
    mention_only = [e for e in external if e["pdb"] and e["pdb"] not in prep]
    head = subprocess.run(["git", "-C", str(sts.MDCLAW_CHECKOUT), "rev-parse", "HEAD"],
                          capture_output=True, text=True, check=True).stdout.strip()
    head_tokens = set(sts.mdclaw_tokens(sts.MDCLAW_CHECKOUT, head)) - set(hs.mdclaw_not_pdb)
    new_at_head = sorted(head_tokens - set(mentions))
    log(f"tasks {len(tasks)}, hard {len(hard)}, mention-only {len(mention_only)}; "
        f"mdclaw HEAD {head[:7]} adds tokens {new_at_head}")

    rows = [r for r in eligible if sts.category_of(r) == "membrane"]
    task_ids = {(c["node"], c["accession"]) for c in tasks}
    task_pdbs = {c["pdb"].upper() for c in hard if c.get("pdb")}
    pdb_of = lambda r: r["metadata"]["PDBIDS"][0].upper()           # noqa: E731
    deposit_rows = entities(workdir, {pdb_of(r) for r in rows})
    current = sts.rcsb_entries(workdir, {pdb_of(r) for r in rows})

    funnel, ranked = [], []
    for row in rows:
        meta, key = row["metadata"], (row["node"], row["accession"])
        pdb = pdb_of(row)
        chains = sts.metadata_chains(meta)
        residues = sts.residues_of(meta)
        atoms = int(sts.vc_float(meta.get("SYSTATS")) or 0)
        seen = assess(chains, deposit_rows.get(pdb) or [], tasks, hard, mention_only)
        item = {"node": key[0], "accession": key[1], "pdb": pdb, "name": meta.get("NAME"),
                "residues": residues, "atoms": atoms, "lipids": sts.lipid_species(meta),
                "lipid_residues": meta.get("LIPIRES"), "mdcount": row.get("mdcount"),
                "force_field": meta.get("FF"), "temperature": meta.get("TEMP"),
                "window_ns": row.get("window_ns"), "windows": row.get("windows"),
                **{k: v for k, v in seen.items() if k != "_order"}}
        if key in task_ids:
            item["removed_by"] = "1 already a task"
        elif pdb in task_pdbs:
            item["removed_by"] = "1 PDB ID among the tasks, MDPrepBench or the withdrawn"
        elif pdb in mentions or pdb in new_at_head:
            item["removed_by"] = f"2 own PDB ID mentioned in mdclaw ({mentions.get(pdb, 'HEAD')})"
        elif residues > MAX_RESIDUES or atoms > args.max_atoms:
            item["removed_by"] = f"3 size: {residues} residues, {atoms} atoms"
        elif seen["failures"]:
            item["removed_by"] = "2 distinctness: " + "; ".join(seen["failures"])
        elif current.get(pdb, {}).get("missing"):
            item["removed_by"] = "4 not a current RCSB entry"
        else:
            ranked.append((seen["_order"], key[1], row, item))
        funnel.append(item)
    ranked.sort(key=lambda x: (x[0], x[1]))
    counts = collections.Counter((i.get("removed_by") or "passes 1-3").split(":")[0].split(" (")[0]
                                 for i in funnel)
    log(json.dumps(counts, indent=1))
    log("ranked: " + ", ".join(f"{i['pdb']}({i['accession']}) {o:.3f}" for o, _, _, i in ranked))
    selection = workdir / "selection"
    selection.mkdir(parents=True, exist_ok=True)
    (selection / "candidates.json").write_text(json.dumps(
        {"generated": time.strftime("%Y-%m-%d %H:%M:%S %Z"), "rule": hs.rule_doc,
         "mdclaw_commit": hs.mdclaw_commit, "mdclaw_head": head, "new_at_head": new_at_head,
         "counts": counts, "order": [i["accession"] for _, _, _, i in ranked], "funnel": funnel},
        indent=1, ensure_ascii=False, default=str))
    if args.screen_only:
        return 0

    attempts, kept = [], []
    passed_pdbs = []
    for _, accession, row, item in ranked:
        if len(passed_pdbs) >= args.need:
            break
        node, pdb = row["node"], item["pdb"]
        record = {"accession": accession, "node": node, "pdb": pdb, "rank": len(attempts) + 1,
                  "order_key": item["max_chain_vs_tasks"], "atoms": item["atoms"],
                  "residues": item["residues"]}
        try:
            verified = vc.verify(workdir, node, accession, pdb)
        except Exception as exc:                                    # noqa: BLE001
            attempts.append(dict(record, kept=False, reason=f"verification error: {exc!r}"))
            log(f"{pdb} {accession}: error {exc!r}")
            continue
        record["stability"] = verified.get("stability")
        reason = None if verified.get("verdict") == "ok" else verified.get("reason")
        if reason is None:
            stab = verified["stability"]["last_third_rmsd_angstrom"]
            if stab is None or stab > RMSD_MAX:
                reason = f"unstable reference: last-third RMSD {stab} A > {RMSD_MAX}"
        if reason is None:
            chains = [(c["label"], c["type"], c["sequence"]) for c in verified["reference_chains"]]
            exact = assess(chains, deposit_rows.get(pdb) or [], tasks, hard, mention_only)
            record["reference_sequences"] = {k: v for k, v in exact.items() if k != "_order"}
            if exact["failures"]:
                reason = "distinctness on the reference: " + "; ".join(exact["failures"])
        if reason is None:
            reference = vc.reference_structure(workdir, node, accession)
            reason = (sts.content_check("membrane", verified, row["metadata"], reference)
                      or force_field_problem(row["metadata"], reference))
        record.update(kept=reason is None, reason=reason)
        attempts.append(record)
        log(f"{pdb} {accession}: {'PASS' if reason is None else 'drop: ' + reason}")
        if reason is None:
            if pdb not in passed_pdbs:
                passed_pdbs.append(pdb)
            kept.append({
                "category": "membrane", "node": node, "accession": accession, "pdb_id": pdb,
                "title": (current.get(pdb, {}).get("struct") or {}).get("title"),
                "mddb_name": row["metadata"].get("NAME"),
                "polymer_residues": item["residues"], "atoms_SYSTATS": item["atoms"],
                "LIPIRES": row["metadata"].get("LIPIRES"), "lipids": item["lipids"],
                "force_field": row["metadata"].get("FF"), "water": row["metadata"].get("WAT"),
                "temperature_K": row["metadata"].get("TEMP"),
                "ensemble": row["metadata"].get("ENSEMBLE"),
                "replicas": row.get("mdcount") or 1, "window_ns": row.get("window_ns"),
                "windows": row.get("windows"), "frames_per_replica": row.get("frames_per_replica"),
                "order_key": item["max_chain_vs_tasks"],
                "last_third_rmsd_angstrom": verified["stability"]["last_third_rmsd_angstrom"],
                "drift_angstrom": verified["stability"]["drift_angstrom"],
                "license": row["metadata"].get("LICENSE"),
                "distinctness": record["reference_sequences"],
                "reference_chains": [{k: c[k] for k in ("label", "type")}
                                     | {"length": len(c["sequence"])}
                                     for c in verified["reference_chains"]],
                "chain_matches": verified.get("chain_matches"),
                "record": verified["record"], "selection": verified["selection"]})
    (selection / "selection_log.json").write_text(json.dumps(attempts, indent=1, ensure_ascii=False,
                                                             default=str))
    picks = kept[:1]
    for rank, item in enumerate(kept[1:], 1):
        item["reserve_rank"] = rank
    (selection / "selected.json").write_text(json.dumps(
        {"generated": time.strftime("%Y-%m-%d %H:%M:%S %Z"), "set": hs.name, "split": hs.split,
         "rule": hs.rule_doc, "threshold": THRESHOLD, "rmsd_max_angstrom": RMSD_MAX,
         "max_residues": MAX_RESIDUES, "max_atoms": args.max_atoms,
         "selected": picks, "reserves": kept[1:], "shortfall": {}},
        indent=1, ensure_ascii=False, default=str))
    log(f"tried {len(attempts)}, passed {[k['pdb_id'] for k in kept]}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
