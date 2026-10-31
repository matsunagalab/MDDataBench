#!/usr/bin/env python3
"""Scan every MDDB node and apply the MDDataBench eligibility filters.

Step 1 of the held-out test-set selection (docs/test-set-selection.md).

What it does
------------
1. Pages through ``/projects?limit=100&page=N`` on each of the eight MDDB nodes
   in ``mddatabench.reference.NODES`` (the global API is not a superset, so every
   node is asked directly) and caches each page as JSON under
   ``<workdir>/cache/listing/<node>/``.  A rerun reads the cache.
2. For the DynaRepo node (inr), whose listing historically lacked length
   information, fetches each project's ``rmsds`` analysis (cached under
   ``<workdir>/cache/analyses/``) and counts frames from its series length, as
   the original selection did (docs/memo.md 2026-08-22 (7)).
3. Applies the eligibility filters of docs/memo.md 2026-08-22 (5)-(7) in order,
   records the pool count after each one, and writes the surviving projects as
   compact records to ``<workdir>/selection/eligible.json`` and the counts to
   ``<workdir>/selection/pool_counts.json``.

Nothing here runs MD, an agent or MDClaw, and nothing reads campaign results:
the inputs are MDDB metadata only.

Usage::

    PYTHONPATH=<MDDataBench> python3 scripts/scan_mddb_pool.py \
        --workdir /data1/rkp00079/rku00161/testset-20261031
"""

from __future__ import annotations

import argparse
import collections
import concurrent.futures as cf
import json
import math
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

from mddatabench.reference import NODES
from mddatabench._task_builder import WATERS

DIRECT_NODES = ("mmb", "oxf", "cin", "bsc", "inr", "jsc", "rpbs", "ufl")
PAGE = 100
TOPOLOGIES = ("topology.prmtop", "topology.tpr", "topology.psf", "topology.top")
# Window per node: 1 ns everywhere; 2.5 ns for DynaRepo (100 ps frames).
WINDOW_NS = {"inr": 2.5}
MIN_WINDOWS = 10
MIN_FRAMES_PER_WINDOW = 25


# Listing requests: a node that does not answer page 1 within this budget is
# recorded as unreachable (oxf timed out on 2026-10-31).
LISTING_TIMEOUT = 120
LISTING_RETRIES = 3


def http_json(url, timeout=300, retries=5, pause=2.0):
    last = None
    for attempt in range(retries):
        try:
            request = urllib.request.Request(url, headers={"User-Agent": "MDDataBench-testset-scan/1.0"})
            with urllib.request.urlopen(request, timeout=timeout) as response:
                return json.load(response)
        except urllib.error.HTTPError as exc:
            last = exc
            if exc.code == 404:
                raise
        except Exception as exc:                                    # noqa: BLE001
            last = exc
        time.sleep(pause * (2 ** attempt))
    raise RuntimeError(f"{url}: {type(last).__name__}: {last}")


def cached_json(path: Path, url: str, timeout=300, retries=5):
    if path.exists():
        try:
            return json.loads(path.read_text())
        except json.JSONDecodeError:
            path.unlink()
    data = http_json(url, timeout=timeout, retries=retries)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(data))
    tmp.rename(path)
    return data


def fetch_node(node: str, workdir: Path, log) -> dict:
    base = NODES[node]
    out = workdir / "cache" / "listing" / node
    first = cached_json(out / "page_0001.json", f"{base}?limit={PAGE}&page=1",
                        timeout=LISTING_TIMEOUT, retries=LISTING_RETRIES)
    total = int(first.get("filteredCount") or 0)
    pages = max(1, math.ceil(total / PAGE))
    projects, errors = {}, []

    def absorb(data):
        for p in data.get("projects", []):
            # A listing entry can be an error object instead of a project
            # (bsc A002M: "missing metadata, which should never happen").
            if "accession" not in p:
                errors.append(p.get("error") or str(p)[:200])
                continue
            projects.setdefault(p["accession"], p)

    absorb(first)
    for page in range(2, pages + 1):
        absorb(cached_json(out / f"page_{page:04d}.json", f"{base}?limit={PAGE}&page={page}"))
    log(f"{node}: filteredCount={total} pages={pages} unique={len(projects)} errors={len(errors)}")
    return {"node": node, "filteredCount": total, "projects": projects, "errors": errors}


def rmsds_frames(node, accession, workdir):
    path = workdir / "cache" / "analyses" / node / f"{accession}_rmsds.json"
    try:
        data = cached_json(path, f"{NODES[node]}/{accession}/analyses/rmsds", timeout=300)
    except Exception as exc:                                        # noqa: BLE001
        return None, str(exc)
    for entry in data.get("data") or []:
        if entry.get("values"):
            return len(entry["values"]), None
    return None, "empty rmsds"


# --- metadata readers --------------------------------------------------------
# MDDB writes absence as strings ("none", "No") as well as null; bool() reads
# those as true.  docs/memo.md 2026-08-22 (5) and (6) record both traps.
def absent(value):
    if value is None:
        return True
    if isinstance(value, (list, tuple, dict)) and not value:
        return True
    if isinstance(value, str) and value.strip().lower() in ("", "none", "no", "null", "n/a", "na"):
        return True
    return False


def as_float(value):
    try:
        out = float(value)
    except (TypeError, ValueError):
        return None
    return out if math.isfinite(out) else None


def normalise_water(value):
    if absent(value):
        return None
    text = str(value).strip().upper().replace(" ", "")
    for key, name in WATERS.items():
        if text == key.strip().upper().replace(" ", ""):
            return name
    return None


def is_coarse_grained(meta):
    if not absent(meta.get("CG_SELECTION")):
        return True
    ff = " ".join(str(x) for x in (meta.get("FF") or [])).lower()
    if "martini" in ff or "sirah" in ff:
        return True
    if "martini" in str(meta.get("WAT") or "").lower():
        return True
    return False


def open_license(meta, node):
    text = str(meta.get("LICENSE") or "").strip()
    low = text.lower()
    if not text:
        # DynaRepo returns no licence for Dynabench; accepted there with the
        # discrepancy recorded per task (CLAUDE.md invariant).
        return node == "inr"
    if "noncommercial" in low or "non-commercial" in low or "noderiv" in low or "no deriv" in low:
        return False
    return any(key in low for key in ("creative commons attribution", "cc by", "cc-by", "cc0",
                                      "public domain", "apache", "mit license", "academic free",
                                      "bsd"))


def frame_info(project, node, workdir):
    meta = project.get("metadata") or {}
    step = as_float(meta.get("FRAMESTEP"))
    frames, source = None, None
    if node == "inr":
        frames, err = rmsds_frames(node, project["accession"], workdir)
        source = "rmsds" if frames else f"rmsds:{err}"
    if not frames:
        if as_float(meta.get("mdFrames")):
            frames, source = int(as_float(meta.get("mdFrames"))), "mdFrames"
        elif project.get("totalFrames"):
            frames = int(project["totalFrames"]) // max(int(project.get("mdcount") or 1), 1)
            source = "totalFrames/mdcount"
        elif as_float(meta.get("SNAPSHOTS")):
            frames, source = int(as_float(meta.get("SNAPSHOTS"))), "SNAPSHOTS"
    return step, frames, source


def window_ok(step, frames, window):
    if not step or not frames or step <= 0:
        return False, 0, 0
    per_window = int(round(window / step, 6))
    if per_window < MIN_FRAMES_PER_WINDOW:
        return False, per_window, 0
    windows = frames // per_window
    return windows >= MIN_WINDOWS, per_window, windows


def compact(project, node, step, frames, frame_source, per_window, windows):
    meta = project.get("metadata") or {}
    keep = ("NAME", "DESCRIPTION", "COLLECTIONS", "PDBIDS", "FF", "WAT", "TEMP", "ENSEMBLE",
            "PCOUPLING", "PRESSURE", "BOXTYPE", "TIMESTEP", "FRAMESTEP", "PROGRAM", "VERSION",
            "METHOD", "LICENSE", "LINKCENSE", "CITATION", "SYSTATS", "PROTATS", "PROTRES",
            "DNARES", "RNARES", "DNAATS", "RNAATS", "LIPIRES", "LIPIATS", "CARBRES", "CARBATS",
            "SOLVRES", "COUNION", "NOCNION", "OTHRATS", "SYSTRES", "SOL", "NA", "CL",
            "SEQUENCES", "PROTSEQ", "NUCLSEQ", "CHAINNAMES", "LIGANDS", "LIGANDNAMES",
            "INPUT_LIGANDS", "INCHIKEYS", "MEMBRANES", "MULTIMERIC", "PTM", "RSNAME",
            "SYSKEYS", "REFERENCES", "DOMAINS", "mdFrames", "mdTime", "mdName", "LENGTH",
            "CG_SELECTION", "WARNINGS", "CUSTOMS", "FORCED_REFERENCES", "INTERACTIONS")
    return {
        "node": node, "accession": project["accession"],
        "mdcount": project.get("mdcount"), "mds": project.get("mds"),
        "chains": project.get("chains"), "files": project.get("files"),
        "analyses": project.get("analyses"),
        "frames_per_replica": frames, "frame_source": frame_source,
        "frames_per_window": per_window, "windows": windows,
        "window_ns": WINDOW_NS.get(node, 1.0),
        "metadata": {k: meta.get(k) for k in keep if k in meta},
    }


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--workdir", default="/data1/rkp00079/rku00161/testset-20261031")
    parser.add_argument("--nodes", default=",".join(DIRECT_NODES))
    args = parser.parse_args(argv)
    workdir = Path(args.workdir)
    (workdir / "selection").mkdir(parents=True, exist_ok=True)
    log = lambda msg: print(msg, file=sys.stderr, flush=True)       # noqa: E731

    nodes = [n for n in args.nodes.split(",") if n]
    listings, failures = {}, {}
    with cf.ThreadPoolExecutor(max_workers=len(nodes)) as pool:
        futures = {pool.submit(fetch_node, n, workdir, log): n for n in nodes}
        for future in cf.as_completed(futures):
            node = futures[future]
            try:
                listings[node] = future.result()
            except Exception as exc:                                # noqa: BLE001
                failures[node] = f"{type(exc).__name__}: {exc}"
                log(f"{node}: FAILED {failures[node]}")

    # Frame counts for inr come from the rmsds analysis (one request each).
    inr = listings.get("inr", {}).get("projects", {})
    with cf.ThreadPoolExecutor(max_workers=4) as pool:
        list(pool.map(lambda acc: rmsds_frames("inr", acc, workdir), sorted(inr)))

    counts = collections.OrderedDict()
    pool_now = [(n, p) for n in nodes if n in listings for p in listings[n]["projects"].values()]
    per_node = lambda rows: dict(collections.Counter(n for n, _ in rows))     # noqa: E731
    counts["all projects (union of nodes)"] = (len(pool_now), per_node(pool_now))

    def step(label, keep):
        nonlocal pool_now
        pool_now = [(n, p) for n, p in pool_now if keep(n, p)]
        counts[label] = (len(pool_now), per_node(pool_now))

    md = lambda p: p.get("metadata") or {}                          # noqa: E731
    step("Classical MD", lambda n, p: str(md(p).get("METHOD") or "").strip().lower() == "classical md")
    step("all-atom (CG_SELECTION absent, no Martini/SIRAH)", lambda n, p: not is_coarse_grained(md(p)))
    step("PDB ID present", lambda n, p: bool([x for x in (md(p).get("PDBIDS") or []) if not absent(x)]))
    step("supported water model", lambda n, p: normalise_water(md(p).get("WAT")) is not None)
    step("numeric temperature", lambda n, p: as_float(md(p).get("TEMP")) is not None)
    step("topology prmtop/tpr/psf/top", lambda n, p: any(t in (p.get("files") or []) for t in TOPOLOGIES))
    step("fluctuation + rgyr analyses", lambda n, p: {"fluctuation", "rgyr"} <= set(p.get("analyses") or []))

    info = {}
    for n, p in pool_now:
        s, f, src = frame_info(p, n, workdir)
        ok, per, win = window_ok(s, f, WINDOW_NS.get(n, 1.0))
        info[(n, p["accession"])] = (s, f, src, per, win, ok)
    step(">=10 windows x >=25 frames (1 ns; 2.5 ns on inr)", lambda n, p: info[(n, p["accession"])][5])
    step("exactly one PDB ID", lambda n, p: len([x for x in md(p).get("PDBIDS") or [] if not absent(x)]) == 1)
    step("open licence (CC BY/CC0/Apache/MIT/AFL/BSD; none only on inr)", lambda n, p: open_license(md(p), n))

    eligible = []
    for n, p in pool_now:
        s, f, src, per, win, _ = info[(n, p["accession"])]
        eligible.append(compact(p, n, s, f, src, per, win))
    (workdir / "selection" / "eligible.json").write_text(json.dumps(eligible, indent=1))
    collections_count = collections.Counter(
        (r["node"], ",".join(r["metadata"].get("COLLECTIONS") or []) or "-") for r in eligible)
    report = {
        "generated": time.strftime("%Y-%m-%d %H:%M:%S %Z"),
        "node_listing": {n: {"api": NODES[n], "filteredCount": listings[n]["filteredCount"],
                             "fetched": len(listings[n]["projects"]),
                             "listing_errors": listings[n]["errors"]} for n in listings},
        "node_failures": failures,
        "filters": [{"filter": k, "remaining": v[0], "per_node": v[1]} for k, v in counts.items()],
        "eligible_by_collection": {f"{a}:{b}": c for (a, b), c in sorted(collections_count.items())},
    }
    (workdir / "selection" / "pool_counts.json").write_text(json.dumps(report, indent=1))
    for row in report["filters"]:
        log(f"{row['remaining']:6d}  {row['filter']}  {row['per_node']}")
    for key, value in report["eligible_by_collection"].items():
        log(f"   {value:5d}  {key}")
    if failures:
        log(f"node failures: {failures}")


if __name__ == "__main__":
    main()
