#!/usr/bin/env python3
"""Choose the 30-task held-out MDDataBench test set from the eligible MDDB pool.

Step 3 of the held-out test-set selection; the rule it applies is pre-registered
in docs/test-set-selection.md and nothing here deviates from it silently.

Inputs: ``<workdir>/selection/eligible.json`` from ``scan_mddb_pool.py``, the 98
shipped task contracts (plus the withdrawn 038 and 061 and the development task
1EDN), their cached reference bundles, RCSB entry metadata and entity sequences
fetched over GraphQL (cached), MDPrepBench's PDB IDs, MDStudyBench S01's
reference sequence, and the text of the mdclaw checkout (read only).  It never runs MD, MDClaw or
an agent and never reads campaign results.

What it does, in order:

1. Puts every eligible project into at most one category pool (membrane,
   antibody, complex, nanobody, ligand, nucleic, metal, soluble_charmm,
   soluble_amber), by its node/collection and its metadata content.
2. Removes projects that share a PDB ID with the development set (the 98,
   038, 061, the 2026-08-20 task 1EDN, MDPrepBench, MDStudyBench and every PDB
   entry the mdclaw checkout documents), exceed the largest cast task of the
   same category in reference atoms or polymer residues, fail the
   sequence-distinctness rule on MDDB's own reference sequences (PROTSEQ /
   NUCLSEQ; protein 3-mers, nucleotide 6-mers), or name an obsolete RCSB entry.
3. Processes the categories scarcest pool first (soluble last, since they
   receive any slot another category cannot fill) and within each category runs
   a deterministic greedy farthest-point (max-min) selection.  The anchors are the cast tasks of the same category; the seed is
   the candidate farthest from them; every later pick is the candidate whose
   minimum distance to (anchors + picks so far) is largest.  Ties go to the
   smaller (node, accession).  Each pick is verified only when it is reached
   (``verify_candidates.verify``): the reference structure is aligned to the
   deposit's SEQRES, ``selection()`` is called on the record, the reference
   trajectory's stability is measured, sequence distinctness is re-checked on
   the reference structure's own sequences, and the category's content is
   checked on the reference.  A pick that fails is dropped and the step is
   repeated.  Because a dropped candidate never influenced an earlier pick,
   this lazy order gives exactly the result of verifying the whole pool first.
4. After the 30 picks, continues each category's greedy sequence to produce an
   ordered reserve list (RESERVES per category), checked against all 30 picks
   and all earlier reserves.
5. Writes ``<workdir>/selection/selected.json`` and
   ``<workdir>/selection/selection_log.json`` (every pick attempt and why it
   was kept or dropped).

Usage::

    PYTHONPATH=<MDDataBench> python3 scripts/select_test_set.py \
        --workdir /data1/rkp00079/rku00161/testset-20261031

``--set v7`` selects test-v7 (docs/test-set-v7-selection.md): its own work
directory, the v6 test tasks added to the development set (and to the anchors),
and the mdclaw checkout read at the commit the set pins (``heldout_sets.py``).
The default, ``v6``, reproduces the v6 selection.
"""

from __future__ import annotations

import argparse
import collections
import json
import math
import re
import sys
import time
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import heldout_sets as hsets                                         # noqa: E402
import verify_candidates as vc                                       # noqa: E402

from mddatabench import _task_builder as tb                         # noqa: E402
from mddatabench import composition as cp                           # noqa: E402

REPO = Path(__file__).resolve().parents[1]
TASKS = REPO / "benchmarks" / "mddatabench" / "tasks"
BUNDLES = Path("/data1/rkp00079/rku00161/references")

# Withdrawn on 2026-08-30 (docs/memo.md) but used during development, so they
# count as part of the cast for exclusion and sequence distinctness.
WITHDRAWN = [
    {"task_id": "038_ligand_1ikt", "axis": "ligand", "node": "cin", "accession": "A0007",
     "pdb": "1IKT"},
    {"task_id": "061_metal_6m0j", "axis": "metal", "node": "mmb", "accession": "MCV1900237",
     "pdb": "6M0J"},
]

# Development tasks that never entered the cast: D03 of 2026-08-20 was
# endothelin-1, solved end to end with MDClaw (docs/memo.md 2026-08-20 and
# 2026-08-21).  D01/D02 were the PLpro references 6W9C/6WRH, already in it.
DEVELOPMENT_EXTRA = [
    {"task_id": "D03_1edn (dev task 2026-08-20)", "axis": "soluble_amber", "node": "mmb",
     "accession": "A00EC", "pdb": "1EDN"},
]

# Everything else MDClaw was developed or documented against (rule v4,
# coordinator decision 2026-10-31).  These get the same three distinctness
# tests as the cast, on their deposits' entity sequences: they have no MDDB
# reference.  They are never diversity anchors.  The lists live in
# heldout_sets.py, per set; these names are v6's, kept for importers.
#
# MDPrepBench's 40 tasks: PDB IDs read (read-only) from
# /data1/rkp00048/rku00208/MDPrepBench/benchmarks/mdprepbench/tasks/*.
MDPREPBENCH_PDBS = list(hsets.MDPREPBENCH_PDBS)

# MDStudyBench (github.com/matsunagalab/MDStudyBench, main): one task, S01, on
# T4 lysozyme C54T/C97A/L99A.  It names no PDB ID, only a reference sequence,
# which is fetched from the task contract.
MDSTUDYBENCH_TASK = hsets.V6.mdstudybench_tasks[0][1]

# PDB IDs mentioned in the mdclaw checkout (skills/, tests/, examples/, docs/,
# matched case-insensitively as whole 4-character tokens and kept when RCSB has
# the entry), read from the git tree of the commit the set pins (v6: ac0e328,
# the checkout's HEAD on 2026-10-31, whose tree reproduces the 171 mentions v6
# recorded from the working tree).  These tokens matched a current RCSB entry
# but are not a mention of it; each was checked by reading its context.
MDCLAW_CHECKOUT = Path("/home/rku00161/mdclaw")
MDCLAW_DIRS = ("skills", "tests", "examples", "docs")
MDCLAW_NOT_PDB = hsets.MDCLAW_NOT_PDB

# Processing order is the quota order; a category that cannot be filled hands
# its remaining slots to the soluble categories (alternating, ATLAS first).
QUOTAS = [("membrane", 4), ("antibody", 3), ("complex", 4), ("nanobody", 3),
          ("ligand", 4), ("nucleic", 4), ("metal", 2),
          ("soluble_charmm", 3), ("soluble_amber", 3)]
RESERVES = 3
THRESHOLD = 0.70
RMSD_MAX = 4.0
CHAIN_MIN = 30
K = 3
# Nucleotide k-mers are 6-mers, not 3-mers: a deviation from the stated rule,
# recorded in docs/test-set-selection.md.  Over a 4-letter alphabet every
# 3-mer is common (64 of them), so 3-mer containment calls 9 of the cast's 12
# DNA-only references "the same system" as the nucleosome 1KX5, whose 294 nt
# carry nearly all 64.  A 6-mer carries 12 bits, about a protein 3-mer's
# 3*log2(20) = 13; with 6-mers the largest containment between two cast
# nucleic references is 0.111.  ``--nucleic-k 3`` applies the rule literally.
NUCLEIC_K = 6

METAL_NAMES = {"ZN", "ZN2", "ZNB", "MG", "MG2", "CA", "CAL", "FE", "FE2", "FE3", "CU", "CU1",
               "CU2", "MN", "MN2", "CO", "NI", "CD", "HG", "SR", "BA", "YB"}
LIPID_NAMES = set(tb.LIPIDS) | set(cp.LIPID_RESIDUES)

# --- sequences ---------------------------------------------------------------

IG_START = re.compile(r"C.{9,15}W[VFYIL][RQKH]")
IG_J = re.compile(r"[WF]G.G")


def ig_variable_end(sequence: str):
    """End (exclusive) of an immunoglobulin variable domain, or None.

    A V domain is recognised by both of its conserved framework motifs: Cys22
    followed 10-16 residues later by Trp36 (``C...W[VFYIL][RQKH]``) in the first
    55 residues, and the J-region ``WGxG`` (heavy, VHH) or ``FGxG`` (light)
    starting between residues 85 and 140.  The domain ends 10 residues after the
    J motif starts (``WGQGTxVTVSS`` / ``FGxGTKLEIK``), which is the "first ~110
    residues" of the rule made exact (108 for a kappa light chain, 117-131 for a
    heavy chain or VHH in the cast).
    """
    if not IG_START.search(sequence[:55]):
        return None
    for match in IG_J.finditer(sequence):
        if 85 <= match.start() <= 140:
            return min(len(sequence), match.start() + 11)
    return None


def ig_kind(sequence: str):
    """"heavy" (WGxG J motif, also VHH), "light" (FGxG) or None."""
    if ig_variable_end(sequence) is None:
        return None
    for match in IG_J.finditer(sequence):
        if 85 <= match.start() <= 140:
            return "heavy" if match.group(0)[0] == "W" else "light"
    return None


def kmer_set(chains, k=None):
    """k-mers of a list of (type, sequence); never across a chain boundary.

    Protein chains give 3-mers, nucleic chains ``NUCLEIC_K``-mers (unless ``k``
    forces one length for all).  Each k-mer carries its polymer type, so an RNA
    ``ACG`` is not a protein ``ACG``.  ``X`` (unknown) never forms a k-mer.
    """
    out = set()
    for kind, sequence in chains:
        tag = {"protein": "P", "dna": "D", "rna": "R"}.get(kind, "M")
        length = k or (K if kind == "protein" else NUCLEIC_K)
        text = sequence.upper()
        for i in range(len(text) - length + 1):
            piece = text[i:i + length]
            if "X" not in piece:
                out.add((tag, piece))
    return out


def containment(a, b):
    if not a or not b:
        return 0.0
    return len(a & b) / min(len(a), len(b))


def chain_kmers(chains):
    """Per-chain k-mer sets for the chain-level rule; Ig chains cut to their V domain."""
    out = []
    for label, kind, sequence in chains:
        ig = kind == "protein" and ig_variable_end(sequence) is not None
        used = sequence[:ig_variable_end(sequence)] if ig else sequence
        out.append({"label": label, "type": kind, "length": len(sequence), "ig": ig,
                    "kmers": kmer_set([(kind, used)])})
    return out


def metadata_chains(meta):
    chains = []
    for i, s in enumerate(meta.get("PROTSEQ") or []):
        if s:
            chains.append((f"P{i + 1}", "protein", str(s)))
    dna = int(vc_float(meta.get("DNARES")) or 0)
    rna = int(vc_float(meta.get("RNARES")) or 0)
    for i, s in enumerate(meta.get("NUCLSEQ") or []):
        if not s:
            continue
        s = str(s)
        kind = "rna" if "U" in s.upper() else ("dna" if "T" in s.upper() or dna else
                                               "rna" if rna else "dna")
        chains.append((f"N{i + 1}", kind, s))
    return chains


def vc_float(value):
    try:
        out = float(value)
    except (TypeError, ValueError):
        return None
    return out if math.isfinite(out) else None


# --- RCSB --------------------------------------------------------------------

GRAPHQL = "https://data.rcsb.org/graphql"
QUERY = """query($ids: [String!]!) { entries(entry_ids: $ids) {
  rcsb_id
  struct { title }
  struct_keywords { pdbx_keywords text }
  exptl { method }
  rcsb_entry_info { polymer_entity_count deposited_polymer_entity_instance_count
    deposited_modeled_polymer_monomer_count deposited_unmodeled_polymer_monomer_count
    nonpolymer_entity_count inter_mol_covalent_bond_count disulfide_bond_count
    resolution_combined deposited_atom_count }
  polymer_entities { rcsb_polymer_entity { pdbx_description }
    entity_poly { type nstd_monomer pdbx_strand_id rcsb_entity_polymer_type }
    rcsb_entity_source_organism { ncbi_scientific_name } }
  nonpolymer_entities { nonpolymer_comp { chem_comp { id formula_weight name type } } }
} }"""


def rcsb_entries(workdir: Path, ids):
    cache_dir = workdir / "cache" / "rcsb" / "entry"
    cache_dir.mkdir(parents=True, exist_ok=True)
    out, todo = {}, []
    for pdb in sorted({i.upper() for i in ids}):
        path = cache_dir / f"{pdb}.json"
        if path.exists():
            out[pdb] = json.loads(path.read_text())
        else:
            todo.append(pdb)
    for start in range(0, len(todo), 100):
        batch = todo[start:start + 100]
        body = json.dumps({"query": QUERY, "variables": {"ids": batch}}).encode()
        for attempt in range(5):
            try:
                request = urllib.request.Request(GRAPHQL, data=body, headers={
                    "Content-Type": "application/json", **vc.USER_AGENT})
                with urllib.request.urlopen(request, timeout=300) as response:
                    data = json.load(response)
                break
            except Exception:                                       # noqa: BLE001
                time.sleep(2 * 2 ** attempt)
        else:
            raise RuntimeError(f"RCSB GraphQL failed for {batch[:3]}...")
        found = {e["rcsb_id"].upper(): e for e in (data.get("data") or {}).get("entries") or [] if e}
        for pdb in batch:
            entry = found.get(pdb, {"rcsb_id": pdb, "missing": True})
            (cache_dir / f"{pdb}.json").write_text(json.dumps(entry))
            out[pdb] = entry
    return out


SEQ_QUERY = """query($ids: [String!]!) { entries(entry_ids: $ids) { rcsb_id
  polymer_entities { entity_poly { rcsb_entity_polymer_type pdbx_seq_one_letter_code_can } } } }"""


def entity_chains(workdir: Path, ids, name):
    """Deposit entity sequences (protein / DNA / RNA) per PDB ID, cached."""
    path = workdir / "cache" / "rcsb" / f"{name}_sequences.json"
    data = json.loads(path.read_text()) if path.exists() else {"entries": []}
    have = ({e["rcsb_id"].upper() for e in data.get("entries") or [] if e.get("rcsb_id")}
            | set(data.get("requested") or []))
    # A cache written for another ID set must not answer for this one: fetch
    # whatever it lacks (v6's cache holds every v6 ID, so v6 fetches nothing).
    todo = sorted({i.upper() for i in ids} - have)
    for start in range(0, len(todo), 100):
        body = json.dumps({"query": SEQ_QUERY,
                           "variables": {"ids": todo[start:start + 100]}}).encode()
        request = urllib.request.Request(GRAPHQL, data=body, headers={
            "Content-Type": "application/json", **vc.USER_AGENT})
        with urllib.request.urlopen(request, timeout=300) as response:
            part = json.load(response)
        data.setdefault("entries", [])
        data["entries"] += [e for e in (part.get("data") or {}).get("entries") or [] if e]
    if todo or not path.exists():
        data["requested"] = sorted(set(data.get("requested") or []) | set(todo))
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(data))
    entries = data.get("entries") or (data.get("data") or {}).get("entries") or []
    out = {}
    for entry in entries:
        chains = []
        for i, poly in enumerate(entry.get("polymer_entities") or [], 1):
            ep = poly.get("entity_poly") or {}
            kind = {"Protein": "protein", "DNA": "dna", "RNA": "rna"}.get(
                ep.get("rcsb_entity_polymer_type"), "other")
            seq = (ep.get("pdbx_seq_one_letter_code_can") or "").replace("\n", "")
            if kind != "other" and seq:
                chains.append((f"entity{i}", kind, seq))
        out[entry["rcsb_id"].upper()] = chains
    return out


PDB_TOKEN = re.compile(r"(?i)(?<![A-Za-z0-9])([1-9][A-Za-z0-9]{3})(?![A-Za-z0-9])")


def _checkout_files(checkout: Path, commit: str):
    """(relative path, bytes) of every file under MDCLAW_DIRS, in scan order.

    With ``commit`` the files come from that commit's git tree, so the scan does
    not depend on what the working tree holds when it runs; without it, from the
    working tree.  Either way the order is v6's: directory by directory, each
    sorted the way ``sorted(Path.rglob("*"))`` sorts (by path components).
    """
    if not commit:
        for sub in MDCLAW_DIRS:
            for path in sorted((checkout / sub).rglob("*")):
                if not path.is_file() or "__pycache__" in path.parts:
                    continue
                try:
                    yield str(path.relative_to(checkout)), path.read_bytes()
                except OSError:
                    continue
        return
    import io
    import subprocess
    import tarfile
    archive = subprocess.run(["git", "-C", str(checkout), "archive", "--format=tar", commit,
                              "--", *MDCLAW_DIRS], capture_output=True, check=True).stdout
    with tarfile.open(fileobj=io.BytesIO(archive)) as tar:
        members = {m.name: m for m in tar.getmembers() if m.isfile()}
        for sub in MDCLAW_DIRS:
            names = sorted((n for n in members if n.split("/")[0] == sub),
                           key=lambda n: tuple(n.split("/")))
            for name in names:
                if "__pycache__" not in name.split("/"):
                    yield name, tar.extractfile(members[name]).read()


def mdclaw_tokens(checkout: Path = MDCLAW_CHECKOUT, commit: str = ""):
    """Every PDB-shaped token in the checkout's text files, with its first location."""
    seen = {}
    for relative, raw in _checkout_files(checkout, commit):
        if b"\0" in raw[:65536]:
            continue                           # binary: images, bytecode
        text = raw.decode("utf-8", errors="replace")
        for number, line in enumerate(text.splitlines(), 1):
            for match in PDB_TOKEN.finditer(line):
                value = match.group(1).upper()
                if re.search(r"[A-Z]", value) and value not in seen:
                    seen[value] = f"{relative}:{number}"
    return seen


def mdclaw_mentions(workdir: Path, hs=None):
    """PDB IDs the mdclaw checkout mentions, with one example location each."""
    hs = hs or hsets.get()
    seen = mdclaw_tokens(MDCLAW_CHECKOUT, hs.mdclaw_commit)
    existing = rcsb_entries(workdir, seen)
    return {pdb: where for pdb, where in seen.items()
            if not existing.get(pdb, {}).get("missing") and pdb not in hs.mdclaw_not_pdb}


def _reference_sequences(task):
    sequences = []

    def walk(node):
        if isinstance(node, dict):
            for key, value in node.items():
                if key == "reference_sequence" and isinstance(value, str):
                    sequences.append(value)
                else:
                    walk(value)
        elif isinstance(node, list):
            for value in node:
                walk(value)
    walk(task)
    return list(dict.fromkeys(sequences))


def load_external(workdir: Path, hs=None):
    """MDPrepBench, MDStudyBench and mdclaw-documented systems as cast-like items."""
    hs = hs or hsets.get()
    prep = list(hs.mdprepbench_pdbs)
    mentions = mdclaw_mentions(workdir, hs)
    ids = set(prep) | set(mentions)
    chains_by_pdb = entity_chains(workdir, ids, "development_external")
    items = []
    for pdb in sorted(ids):
        sources = []
        if pdb in prep:
            sources.append("MDPrepBench")
        if pdb in mentions:
            sources.append(f"mdclaw {mentions[pdb]}")
        chains = chains_by_pdb.get(pdb) or []
        items.append({"task_id": f"{'+'.join(s.split()[0] for s in sources)}:{pdb}",
                      "sources": sources, "pdb": pdb, "chains": chains})
    for short, url in hs.mdstudybench_tasks:
        study = workdir / "cache" / "mdstudybench" / f"{short}_task.json"
        if not study.exists():
            study.parent.mkdir(parents=True, exist_ok=True)
            study.write_text(vc._get(url))
        task = json.loads(study.read_text())
        # S01 (T4 lysozyme L99A) keeps v6's label; any later task gets its own id.
        label = "S01_t4l_l99a" if short == "S01" else str(task.get("task_id") or short)
        items.append({"task_id": f"MDStudyBench:{label}", "sources": [f"MDStudyBench {short}"],
                      "pdb": None, "chains": [(f"seq{i}", "protein", s)
                                              for i, s in enumerate(_reference_sequences(task), 1)]})
    for item in items:
        item.update(axis=None, withdrawn=True, external=True, metadata={}, reference_system={},
                    role="external",
                    kmers=kmer_set([(t, s) for _, t, s in item["chains"]]),
                    chain_kmers=chain_kmers(item["chains"]))
    return items, mentions


def prep_flags(entry):
    info = entry.get("rcsb_entry_info") or {}
    flags = set()
    if (info.get("deposited_polymer_entity_instance_count") or 0) > 1:
        flags.add("multi_chain_deposit")
    if (info.get("deposited_unmodeled_polymer_monomer_count") or 0) > 0:
        flags.add("unmodeled_residues")
    if (info.get("nonpolymer_entity_count") or 0) > 0:
        flags.add("nonpolymer_components")
    if (info.get("disulfide_bond_count") or 0) > 0:
        flags.add("disulfides")
    for poly in entry.get("polymer_entities") or []:
        if ((poly.get("entity_poly") or {}).get("nstd_monomer") or "").lower().startswith("y"):
            flags.add("modified_residues")
        if len(poly.get("rcsb_entity_source_organism") or []) > 1:
            flags.add("chimeric_entity")
    methods = {(m.get("method") or "").upper() for m in entry.get("exptl") or []}
    if any("NMR" in m for m in methods):
        flags.add("nmr")
    return flags


def keywords(entry):
    return ((entry.get("struct_keywords") or {}).get("pdbx_keywords") or "").strip().upper()


def primary_class(entry):
    """The deposit's class: its PDB keyword up to the first '/', ',' or '('.

    ``HYDROLASE/HYDROLASE INHIBITOR`` and ``HYDROLASE`` are one class.
    """
    return re.split(r"[/,(]", keywords(entry))[0].strip()


def method(entry):
    return "/".join(sorted({(m.get("method") or "").upper() for m in entry.get("exptl") or []}))


def ig_descriptions(entry):
    pattern = re.compile(r"\b(heavy chain|light chain|fab\b|antibody|immunoglobulin|igg|"
                         r"ig gamma|ig kappa|ig lambda|kappa|nanobody|vhh|scfv|"
                         r"single[- ]domain antibody|sybody)", re.I)
    return [p for p in entry.get("polymer_entities") or []
            if pattern.search(((p.get("rcsb_polymer_entity") or {}).get("pdbx_description") or ""))]


# --- categories --------------------------------------------------------------


def lipid_species(meta):
    return sorted(set(meta.get("RSNAME") or []) & LIPID_NAMES)


def metal_species(meta):
    return sorted(set(meta.get("RSNAME") or []) & METAL_NAMES)


def nucleic_kind(meta):
    dna = vc_float(meta.get("DNARES")) or 0
    rna = vc_float(meta.get("RNARES")) or 0
    prot = vc_float(meta.get("PROTRES")) or 0
    base = "dna" if dna and not rna else "rna" if rna and not dna else "dna+rna" if dna else None
    if base is None:
        return None
    return f"protein+{base}" if prot else base


def category_of(row):
    """The one pool a project belongs to, or None.

    Precedence: a bilayer makes it membrane; DNA/RNA makes it nucleic; a kept
    metal ion makes it metal; then the source collections of the cast's axes.
    """
    meta, node = row["metadata"], row["node"]
    collections_ = set(meta.get("COLLECTIONS") or [])
    lipids = vc_float(meta.get("LIPIRES")) or 0
    prot = vc_float(meta.get("PROTRES")) or 0
    if lipids >= tb.BILAYER_RESIDUES and prot > 0 and node == "mmb" and collections_ & {"ebrains", "mcns"}:
        return "membrane"
    if lipids >= tb.BILAYER_RESIDUES:
        return None
    if nucleic_kind(meta) and node == "mmb" and "bigna" in collections_:
        return "nucleic"
    if nucleic_kind(meta):
        return None
    if metal_species(meta) and prot > 0:
        return "metal"
    if node == "inr" and collections_ & {"dynabench", "dynarepo"}:
        # The cast's antibody axis is Dynabench and its complex axis Dynarepo.
        # A test antibody task needs a conventional antibody (a heavy and a
        # light V domain) and an antigen, like 9 of the cast's 10; a complex
        # task is a Dynarepo protein-protein complex without an Ig chain.
        # Dynabench entries with only a single-domain antibody, or none, fit
        # neither axis and are left out.
        seqs = [str(x) for x in meta.get("PROTSEQ") or []]
        kinds = [ig_kind(x) for x in seqs]
        antigens = [x for x, k in zip(seqs, kinds) if k is None]
        if "dynabench" in collections_:
            if "heavy" in kinds and "light" in kinds and antigens:
                return "antibody"
            return None
        if "dynarepo" in collections_ and len(seqs) >= 2 and not any(kinds):
            return "complex"
        return None
    if node == "mmb" and "nanobodies" in collections_:
        return "nanobody"
    if node == "cin" and "ligate" in collections_:
        return "ligand"
    if node == "bsc" and "atlas" in collections_:
        return "soluble_charmm"
    if node == "mmb" and "model" in collections_:
        return "soluble_amber"
    return None


# --- the cast ----------------------------------------------------------------


def listing_index(workdir: Path):
    index = {}
    for page in (workdir / "cache" / "listing").glob("*/page_*.json"):
        node = page.parent.name
        for p in json.loads(page.read_text()).get("projects", []):
            if "accession" in p:
                index[(node, p["accession"])] = p
    return index


def load_cast(workdir: Path, index, hs=None):
    """The development set's MDDB tasks, each with its reference sequences.

    ``role`` says what each one is: ``cast`` (the 98 of splits train/eval:
    anchors, size caps, the "vs 98" columns), ``previous_test`` (an earlier
    test split, now development data: excluded like the cast, an anchor when
    the set says so), ``withdrawn`` (038, 061 and the development task 1EDN:
    excluded, never anchors).  Only the tasks of the set's splits are read, so
    a later split in the tree (v6's 101-130 for a v6 rerun) changes nothing.
    """
    hs = hs or hsets.get()
    cast, previous = [], []
    for path in sorted(TASKS.glob("*/task.json")):
        task = json.loads(path.read_text())
        split = task.get("split")
        if split in hs.cast_splits:
            target, role = cast, "cast"
        elif split in hs.previous_test_splits:
            target, role = previous, "previous_test"
        else:
            continue
        ref = task["reference"]
        target.append({"task_id": task["task_id"], "axis": task["axis"], "node": ref["node"],
                       "accession": ref["accession"], "pdb": ref["pdb_ids"][0],
                       "reference_system": ref.get("reference_system") or {},
                       "withdrawn": False, "role": role, "split": split})
    cast += previous
    for extra in WITHDRAWN + DEVELOPMENT_EXTRA:
        cast.append(dict(extra, reference_system={}, withdrawn=True, role="withdrawn"))
    for item in cast:
        bundle = BUNDLES / f"{item['node']}_{item['accession']}" / "reference.pdb"
        if not bundle.exists():
            bundle = vc.reference_structure(workdir, item["node"], item["accession"])
        polymers = vc.reference_polymers(bundle)
        item["chains"] = [(c["label"], c["type"], c["sequence"]) for c in polymers]
        item["kmers"] = kmer_set([(t, s) for _, t, s in item["chains"]])
        item["chain_kmers"] = chain_kmers(item["chains"])
        project = index.get((item["node"], item["accession"])) or {}
        item["metadata"] = project.get("metadata") or {}
        rs = item["reference_system"]
        if not rs:
            meta = item["metadata"]
            rs = {k: meta.get(k) for k in ("PROTRES", "DNARES", "RNARES", "SYSTATS", "PROTATS")}
            item["reference_system"] = rs
    return cast


def is_anchor(item, hs) -> bool:
    """A diversity anchor of its axis: the 98, and earlier test tasks when the set says so."""
    role = item.get("role", "withdrawn" if item.get("withdrawn") else "cast")
    return role == "cast" or (role == "previous_test" and hs.previous_tests_are_anchors)


def residues_of(meta_or_rs):
    """Polymer residues; MDDB's sequences when PROTRES is missing (8 MoDEL entries)."""
    total = sum(int(vc_float(meta_or_rs.get(k)) or 0) for k in ("PROTRES", "DNARES", "RNARES"))
    if not vc_float(meta_or_rs.get("PROTRES")) and meta_or_rs.get("PROTSEQ"):
        total += sum(len(str(x)) for x in meta_or_rs.get("PROTSEQ") or [])
    return total


def caps_by_axis(cast):
    """Largest reference atoms and polymer residues per axis, over the 98 only."""
    caps = {}
    for item in cast:
        if item["withdrawn"] or item.get("role", "cast") != "cast":
            continue
        rs = item["reference_system"]
        atoms = int(vc_float(rs.get("SYSTATS")) or 0)
        residues = residues_of(rs)
        a, r = caps.get(item["axis"], (0, 0))
        caps[item["axis"]] = (max(a, atoms), max(r, residues))
    return caps


# --- features and distance ---------------------------------------------------


def features(meta, entry, category, kmers, nchains):
    residues = max(residues_of(meta), 1)
    ligand_atoms = (int(vc_float(meta.get("SYSTATS")) or 0) - int(vc_float(meta.get("PROTATS")) or 0)
                    - int(vc_float(meta.get("DNAATS")) or 0) - int(vc_float(meta.get("RNAATS")) or 0)
                    - int(vc_float(meta.get("LIPIATS")) or 0))
    return {
        "kmers": kmers,
        "residues": residues,
        "chains": nchains,
        "class": primary_class(entry),
        "temperature": vc_float(meta.get("TEMP")) or 0.0,
        "ff": tuple(sorted(str(x) for x in (meta.get("FF") or []))) if isinstance(meta.get("FF"), list)
        else (str(meta.get("FF")),),
        "method": method(entry),
        "prep": prep_flags(entry),
        "nucleic": nucleic_kind(meta),
        "ligand_atoms": max(ligand_atoms, 1),
        "lipids": tuple(lipid_species(meta)),
        "metals": tuple(metal_species(meta)),
        "category": category,
    }


def jaccard_distance(a, b):
    a, b = set(a), set(b)
    if not a and not b:
        return 0.0
    return 1.0 - len(a & b) / len(a | b)


def distance(a, b):
    """Equal-weight mean of sequence dissimilarity and simple features, each in [0, 1]."""
    parts = [
        1.0 - containment(a["kmers"], b["kmers"]),
        min(1.0, abs(math.log(a["residues"]) - math.log(b["residues"])) / math.log(10)),
        min(1.0, abs(a["chains"] - b["chains"]) / 3.0),
        0.0 if a["class"] and a["class"] == b["class"] else 1.0,
        min(1.0, abs(a["temperature"] - b["temperature"]) / 20.0),
        0.0 if a["ff"] == b["ff"] else 1.0,
        0.0 if a["method"] == b["method"] else 1.0,
        jaccard_distance(a["prep"], b["prep"]),
    ]
    category = a["category"]
    if category == b["category"]:
        if category == "nucleic":
            parts.append(0.0 if a["nucleic"] == b["nucleic"] else 1.0)
        elif category == "ligand":
            parts.append(min(1.0, abs(math.log(a["ligand_atoms"]) - math.log(b["ligand_atoms"]))
                             / math.log(10)))
        elif category == "membrane":
            parts.append(jaccard_distance(a["lipids"], b["lipids"]))
        elif category == "metal":
            parts.append(jaccard_distance(a["metals"], b["metals"]))
    return round(sum(parts) / len(parts), 6)


# --- checks on the reference -------------------------------------------------


def exact_distinctness(chains, cast, chosen):
    """The three sequence rules on reference-structure sequences."""
    kmers = kmer_set([(t, s) for _, t, s in chains])
    whole = max(((containment(kmers, c["kmers"]), c["task_id"]) for c in cast), default=(0.0, None))
    per_chain = chain_kmers(chains)
    chain_max = (0.0, None, None)
    for mine in per_chain:
        if mine["length"] < CHAIN_MIN:
            continue
        for c in cast:
            for theirs in c["chain_kmers"]:
                value = containment(mine["kmers"], theirs["kmers"])
                if value > chain_max[0]:
                    chain_max = (value, c["task_id"], f"{mine['label']}~{theirs['label']}")
    test_max = max(((containment(kmers, o["exact_kmers"]), o["id"]) for o in chosen),
                   default=(0.0, None))
    # A zero maximum names no task (any of them would do).
    whole = whole if whole[0] > 0 else (0.0, None)
    chain_max = chain_max if chain_max[0] > 0 else (0.0, None, None)
    test_max = test_max if test_max[0] > 0 else (0.0, None)
    return {"whole_vs_cast": round(whole[0], 4), "whole_vs_cast_task": whole[1],
            "chain_vs_cast": round(chain_max[0], 4), "chain_vs_cast_task": chain_max[1],
            "chain_vs_cast_pair": chain_max[2],
            "whole_vs_test": round(test_max[0], 4), "whole_vs_test_task": test_max[1],
            "ig_chains": [m["label"] for m in per_chain if m["ig"]],
            "kmers": kmers}


def content_check(category, verified, meta, reference_pdb):
    chains = verified["reference_chains"]
    proteins = [c for c in chains if c["type"] == "protein"]
    nucleic = [c for c in chains if c["type"] in ("dna", "rna")]
    igs = [c for c in proteins if ig_variable_end(c["sequence"])]
    if category == "membrane":
        lipids = cp.lipid_species(str(reference_pdb))
        if sum(lipids.values()) < tb.BILAYER_RESIDUES:
            return f"no bilayer in the reference ({lipids})"
    elif category == "antibody":
        kinds = {ig_kind(c["sequence"]) for c in igs}
        if not {"heavy", "light"} <= kinds or len(proteins) <= len(igs):
            return "reference lacks a heavy+light antibody or an antigen chain"
    elif category == "complex":
        if len(proteins) < 2 or igs:
            return "reference is not a non-antibody protein-protein complex"
    elif category == "nanobody":
        if not igs:
            return "reference has no immunoglobulin V domain"
    elif category == "ligand":
        residues = cp.read_residues(str(reference_pdb))
        if not any(vc.residue_code(r) is None and r.name.strip().upper() not in METAL_NAMES
                   for r in residues):
            return "reference carries no small-molecule ligand"
    elif category == "nucleic":
        if not nucleic:
            return "reference has no DNA/RNA chain"
    elif category == "metal":
        if not any(m["bound"] for m in verified["reference_metals"]):
            return "reference keeps no polymer-bound metal ion"
    elif category in ("soluble_charmm", "soluble_amber"):
        if len(proteins) != 1 or nucleic:
            return "reference is not a single protein chain"
    return None


# --- selection ---------------------------------------------------------------


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--set", default=hsets.DEFAULT, choices=sorted(hsets.SETS),
                        help="which held-out set (heldout_sets.py); default v6")
    parser.add_argument("--workdir", default=None, help="default: the set's work directory")
    parser.add_argument("--anchors", choices=["set", "cast"], default="set",
                        help="'cast' uses only the 98 as diversity anchors, whatever the set "
                             "says (a sensitivity record, written with --out-suffix)")
    parser.add_argument("--reserves", type=int, default=RESERVES)
    parser.add_argument("--max-verify", type=int, default=400,
                        help="give up on a category after this many verification attempts")
    parser.add_argument("--nucleic-k", type=int, default=NUCLEIC_K,
                        help="k-mer length for DNA/RNA chains (3 = the rule as written)")
    parser.add_argument("--out-suffix", default="",
                        help="suffix for selected/selection_log file names (alternative runs)")
    args = parser.parse_args(argv)
    globals()["NUCLEIC_K"] = args.nucleic_k
    hs = hsets.get(args.set)
    if args.anchors == "cast":
        import dataclasses
        hs = dataclasses.replace(hs, previous_tests_are_anchors=False)
    workdir = Path(args.workdir or hs.workdir)
    out_dir = workdir / "selection"
    log = lambda msg: print(msg, file=sys.stderr, flush=True)       # noqa: E731

    eligible = json.loads((out_dir / "eligible.json").read_text())
    index = listing_index(workdir)
    cast = load_cast(workdir, index, hs)
    caps = caps_by_axis(cast)
    external, mentions = load_external(workdir, hs)
    n_cast = len(cast)
    roles = collections.Counter(c["role"] for c in cast)
    cast = cast + external
    cast_pdbs = {c["pdb"].upper() for c in cast if c.get("pdb")}
    log(f"set {hs.name}; eligible {len(eligible)}; development set {len(cast)}: cast {n_cast} "
        f"({roles['cast']} + {roles['previous_test']} earlier test + {roles['withdrawn']} withdrawn"
        f"/development) + {len(external)} external (MDPrepBench {len(hs.mdprepbench_pdbs)}, "
        f"mdclaw-documented {len(mentions)} at {hs.mdclaw_commit[:7] or 'working tree'}, "
        f"MDStudyBench {len(hs.mdstudybench_tasks)}); caps {caps}")

    counts = collections.OrderedDict()
    pools = collections.defaultdict(list)
    for row in eligible:
        category = category_of(row)
        if category:
            pools[category].append(row)
    counts["categorised"] = {c: len(v) for c, v in pools.items()}

    def keep(label, test):
        for category in list(pools):
            pools[category] = [r for r in pools[category] if test(category, r)]
        counts[label] = {c: len(v) for c, v in pools.items()}

    keep("PDB ID not in the development set", lambda c, r: r["metadata"]["PDBIDS"][0].upper() not in cast_pdbs)
    keep("atoms and polymer residues within the category's largest cast task",
         lambda c, r: int(vc_float(r["metadata"].get("SYSTATS")) or 0) <= caps[c][0]
         and residues_of(r["metadata"]) <= caps[c][1])

    # Sequence screen on MDDB's own reference sequences (PROTSEQ / NUCLSEQ).
    screen = {}
    for category, rows in pools.items():
        for r in rows:
            chains = metadata_chains(r["metadata"])
            result = exact_distinctness(chains, cast, [])
            screen[(r["node"], r["accession"])] = (chains, result)
    keep("whole-system containment < 0.70 vs the development set (MDDB sequences)",
         lambda c, r: screen[(r["node"], r["accession"])][1]["whole_vs_cast"] < THRESHOLD)
    keep("every chain >= 30 residues < 0.70 vs every development-set chain (Ig: V domain)",
         lambda c, r: screen[(r["node"], r["accession"])][1]["chain_vs_cast"] < THRESHOLD)
    for c, v in counts.items():
        log(f"{c}: {v}")

    pdb_ids = {r["metadata"]["PDBIDS"][0].upper() for rows in pools.values() for r in rows}
    pdb_ids |= {c["pdb"].upper() for c in cast if c.get("pdb")}
    entries = rcsb_entries(workdir, pdb_ids)
    # An obsolete entry (2MM1, 7UW7, ...) is not served by RCSB's data API, so an
    # agent cannot look it up there, and its missing keywords, method and flags
    # would also read as maximal distance in the diversity step.
    keep("deposit is a current RCSB entry (not obsolete)",
         lambda c, r: not entries.get(r["metadata"]["PDBIDS"][0].upper(), {}).get("missing"))
    log(f"current RCSB entry: {counts['deposit is a current RCSB entry (not obsolete)']}")

    def feat_row(category, r):
        chains = screen[(r["node"], r["accession"])][0]
        return features(r["metadata"], entries.get(r["metadata"]["PDBIDS"][0].upper(), {}), category,
                        kmer_set([(t, s) for _, t, s in chains]), len(chains))

    cast_features = {}
    for c in cast:
        if c["withdrawn"] or not is_anchor(c, hs):
            continue
        cast_features.setdefault(c["axis"], []).append(
            (c["task_id"], features(c["metadata"], entries.get(c["pdb"].upper(), {}), c["axis"],
                                    c["kmers"], len(c["chains"]))))

    candidates = {cat: [(key, r, f) for key, r, f in sorted(
        [((r["node"], r["accession"]), r, feat_row(cat, r)) for r in rows], key=lambda x: x[0])]
        for cat, rows in pools.items()}

    attempts, chosen = [], []
    rejected = set()
    state = {}
    for category, _ in QUOTAS:
        anchors = [f for _, f in cast_features.get(category, [])]
        pool = candidates.get(category, [])
        mind = {key: min((distance(f, a) for a in anchors), default=1.0) for key, _, f in pool}
        state[category] = {"pool": pool, "mind": mind, "picked": []}

    def next_pick(category, taken_ids):
        st = state[category]
        best = None
        for key, r, f in st["pool"]:
            if key in rejected or key in taken_ids:
                continue
            score = st["mind"][key]
            if best is None or score > best[0] or (score == best[0] and key < best[1]):
                best = (score, key, r, f)
        return best

    def accept(category, score, key, r, f, chosen_now, role):
        meta = r["metadata"]
        pdb = meta["PDBIDS"][0].upper()
        record = {"category": category, "node": key[0], "accession": key[1], "pdb": pdb,
                  "role": role, "greedy_min_distance": score}
        try:
            verified = vc.verify(workdir, key[0], key[1], pdb)
        except Exception as exc:                                    # noqa: BLE001
            record.update(kept=False, reason=f"verification error: {type(exc).__name__}: {exc}")
            return record, None
        record["verdict"] = verified.get("verdict")
        if verified.get("verdict") != "ok":
            record.update(kept=False, reason=verified.get("reason"))
            return record, None
        stab = verified["stability"]
        if stab["last_third_rmsd_angstrom"] is None or stab["last_third_rmsd_angstrom"] > RMSD_MAX:
            record.update(kept=False, reason=f"unstable reference: last-third RMSD "
                                             f"{stab['last_third_rmsd_angstrom']} A > {RMSD_MAX}")
            return record, None
        chains = [(c["label"], c["type"], c["sequence"]) for c in verified["reference_chains"]]
        exact = exact_distinctness(chains, cast, chosen_now)
        if exact["whole_vs_cast"] >= THRESHOLD:
            record.update(kept=False, reason=f"whole-system containment {exact['whole_vs_cast']} "
                                             f"vs {exact['whole_vs_cast_task']}")
            return record, None
        if exact["chain_vs_cast"] >= THRESHOLD:
            record.update(kept=False, reason=f"chain containment {exact['chain_vs_cast']} vs "
                                             f"{exact['chain_vs_cast_task']} ({exact['chain_vs_cast_pair']})")
            return record, None
        if exact["whole_vs_test"] >= THRESHOLD:
            record.update(kept=False, reason=f"whole-system containment {exact['whole_vs_test']} "
                                             f"vs selected {exact['whole_vs_test_task']}")
            return record, None
        reference_pdb = vc.reference_structure(workdir, key[0], key[1])
        problem = content_check(category, verified, meta, reference_pdb)
        if problem:
            record.update(kept=False, reason=problem)
            return record, None
        record["kept"] = True
        return record, {"verified": verified, "exact": exact, "features": f, "row": r}

    def run_greedy(category, want, role, chosen_now):
        st = state[category]
        got, tries = [], 0
        while len(got) < want and tries < args.max_verify:
            taken = {(o["node"], o["accession"]) for o in chosen_now}
            best = next_pick(category, taken)
            if best is None:
                break
            score, key, r, f = best
            tries += 1
            record, kept = accept(category, score, key, r, f, chosen_now, role)
            attempts.append(record)
            log(f"[{category}/{role}] {key[0]}:{key[1]} {record['pdb']} d={score:.4f} "
                f"{'KEEP' if record['kept'] else 'drop: ' + str(record.get('reason'))}")
            if not kept:
                rejected.add(key)
                continue
            item = dict(record, id=f"{key[0]}:{key[1]}", exact_kmers=kept["exact"]["kmers"], **kept)
            got.append(item)
            chosen_now.append(item)
            # Update min distances with the new anchor.
            for k2, _, f2 in st["pool"]:
                d = distance(f2, f)
                if d < st["mind"][k2]:
                    st["mind"][k2] = d
            st["picked"].append(key)
        return got

    slots = collections.OrderedDict(QUOTAS)
    shortfall = {}
    # Scarcest pool first, so that the cross-category distinctness check cannot
    # starve a small category by spending its candidates' proteins elsewhere
    # (rule v1 used the quota order and lost four trypsin-calcium metal
    # candidates to a trypsin complex picked earlier).  The soluble categories
    # come last because they receive any unfillable slot.
    soluble = ("soluble_charmm", "soluble_amber")
    position = {c: i for i, (c, _) in enumerate(QUOTAS)}
    order = sorted((c for c, _ in QUOTAS if c not in soluble),
                   key=lambda c: (len(state[c]["pool"]), position[c])) + list(soluble)
    log(f"processing order: {[(c, len(state[c]['pool'])) for c in order]}")
    moved = 0
    for category in order:
        want = slots[category]
        got = run_greedy(category, want, "selected", chosen)
        if len(got) < want:
            missing = want - len(got)
            shortfall[category] = {"wanted": want, "found": len(got)}
            # Hand the slots to the soluble categories, ATLAS first, alternating
            # across all moved slots.
            for _ in range(missing):
                slots[soluble[moved % 2]] += 1
                moved += 1
            log(f"{category}: only {len(got)} of {want}; {missing} slot(s) moved to soluble")

    reserve_items = []
    for category in order:
        got = run_greedy(category, args.reserves, "reserve", chosen + reserve_items)
        for rank, item in enumerate(got, 1):
            item["reserve_rank"] = rank
        reserve_items.extend(got)

    shipped = [c for c in cast if c.get("role") == "cast"]
    previous_tests = [c for c in cast if c.get("role") == "previous_test"]

    def summary(item):
        meta = item["row"]["metadata"]
        verified, exact = item["verified"], item["exact"]
        mine = [(c["label"], c["type"], c["sequence"]) for c in verified["reference_chains"]]
        vs98 = exact_distinctness(mine, shipped, [])
        vs_previous = exact_distinctness(mine, previous_tests, []) if previous_tests else None
        entry = entries.get(item["pdb"], {})
        return {
            "category": item["category"], "role": item["role"],
            "reserve_rank": item.get("reserve_rank"),
            "node": item["node"], "accession": item["accession"], "pdb_id": item["pdb"],
            "replicas": item["row"].get("mdcount") or len(item["row"].get("mds") or []) or 1,
            "mds": item["row"].get("mds"),
            "title": (entry.get("struct") or {}).get("title"),
            "mddb_name": meta.get("NAME"),
            "collections": meta.get("COLLECTIONS"),
            "keywords": keywords(entry), "method": method(entry),
            "force_field": meta.get("FF"), "water": meta.get("WAT"),
            "temperature_K": meta.get("TEMP"), "ensemble": meta.get("ENSEMBLE"),
            "pressure": meta.get("PRESSURE"), "pcoupling": meta.get("PCOUPLING"),
            "framestep_ns": meta.get("FRAMESTEP"), "frames_per_replica": item["row"]["frames_per_replica"],
            "frame_source": item["row"]["frame_source"],
            "window_ns": item["row"]["window_ns"], "windows": item["row"]["windows"],
            "polymer_residues": residues_of(meta),
            "PROTRES": meta.get("PROTRES"), "DNARES": meta.get("DNARES"), "RNARES": meta.get("RNARES"),
            "LIPIRES": meta.get("LIPIRES"), "atoms_SYSTATS": meta.get("SYSTATS"),
            "PROTATS": meta.get("PROTATS"),
            "reference_chains": [{k: c[k] for k in ("label", "type")} | {"length": len(c["sequence"])}
                                 for c in verified["reference_chains"]],
            "reference_metals": verified["reference_metals"],
            "lipids": lipid_species(meta), "ligand_atoms_metadata": item["features"]["ligand_atoms"],
            "nucleic_kind": nucleic_kind(meta),
            "prep_flags": sorted(item["features"]["prep"]),
            "last_third_rmsd_angstrom": verified["stability"]["last_third_rmsd_angstrom"],
            "drift_angstrom": verified["stability"]["drift_angstrom"],
            "rmsds_series": verified["stability"].get("series"),
            "max_whole_containment_vs_98": vs98["whole_vs_cast"],
            "max_whole_containment_vs_98_task": vs98["whole_vs_cast_task"],
            "max_chain_containment_vs_98": vs98["chain_vs_cast"],
            "max_chain_containment_vs_98_task": vs98["chain_vs_cast_task"],
            **({"max_whole_containment_vs_previous_test": vs_previous["whole_vs_cast"],
                "max_whole_containment_vs_previous_test_task": vs_previous["whole_vs_cast_task"],
                "max_chain_containment_vs_previous_test": vs_previous["chain_vs_cast"],
                "max_chain_containment_vs_previous_test_task": vs_previous["chain_vs_cast_task"]}
               if vs_previous else {}),
            "max_whole_containment_vs_cast": exact["whole_vs_cast"],
            "max_whole_containment_vs_cast_task": exact["whole_vs_cast_task"],
            "max_chain_containment_vs_cast": exact["chain_vs_cast"],
            "max_chain_containment_vs_cast_task": exact["chain_vs_cast_task"],
            "max_chain_containment_vs_cast_pair": exact["chain_vs_cast_pair"],
            "ig_chains": exact["ig_chains"],
            "max_whole_containment_vs_earlier_test_picks": exact["whole_vs_test"],
            "max_whole_containment_vs_earlier_test_picks_task": exact["whole_vs_test_task"],
            "greedy_min_distance": item["greedy_min_distance"],
            "license": meta.get("LICENSE"), "license_url": meta.get("LINKCENSE"),
            "chain_matches": verified.get("chain_matches"),
            "record": verified["record"],
            "selection": verified["selection"],
        }

    # Final pairwise check over the 30 (whole system, reference sequences).
    pairwise = []
    for i, a in enumerate(chosen):
        for b in chosen[i + 1:]:
            pairwise.append((containment(a["exact_kmers"], b["exact_kmers"]), a["id"], b["id"]))
    pairwise.sort(reverse=True)

    result = {
        "generated": time.strftime("%Y-%m-%d %H:%M:%S %Z"),
        # v6's record keeps its own keys, so a rerun compares field for field.
        **({"set": hs.name, "split": hs.split} if hs.name != "v6" else {}),
        "rule": hs.rule_doc,
        "threshold": THRESHOLD, "rmsd_max_angstrom": RMSD_MAX, "k_protein": K,
        "k_nucleic": NUCLEIC_K,
        "pool_counts": counts,
        "category_caps_atoms_residues": caps,
        "development_set": {
            "cast_tasks": [c["task_id"] for c in cast if not c.get("external")],
            **({"previous_test_tasks": [c["task_id"] for c in previous_tests],
                "previous_tests_are_anchors": hs.previous_tests_are_anchors}
               if hs.previous_test_splits else {}),
            "mdprepbench_pdbs": list(hs.mdprepbench_pdbs),
            "mdstudybench": (hs.mdstudybench_tasks[0][1] if len(hs.mdstudybench_tasks) == 1
                             else [url for _, url in hs.mdstudybench_tasks]),
            "mdclaw_documented_pdbs": mentions,
            **({"mdclaw_commit": hs.mdclaw_commit} if hs.name != "v6" else {}),
            "mdclaw_tokens_not_pdb_mentions": hs.mdclaw_not_pdb,
        },
        "processing_order": order,
        "slots": dict(slots), "shortfall": shortfall,
        "max_pairwise_whole_containment_among_selected": pairwise[:5],
        "selected": [summary(i) for i in chosen],
        "reserves": [summary(i) for i in reserve_items],
    }
    (out_dir / f"selected{args.out_suffix}.json").write_text(json.dumps(result, indent=1, ensure_ascii=False,
                                                      default=lambda o: sorted(o) if isinstance(o, set) else str(o)))
    (out_dir / f"selection_log{args.out_suffix}.json").write_text(json.dumps(attempts, indent=1, ensure_ascii=False,
                                                           default=str))
    log(f"selected {len(chosen)}, reserves {len(reserve_items)}; shortfall {shortfall}")


if __name__ == "__main__":
    main()
