"""Fetch the MDDataBench reference bundle for one MDDB project.

Ships fetch code, not data.  Every artifact is re-derivable from the MDDB
accession recorded in the task contract, and the task contract carries the
SHA-256 of what this script produced on the recorded retrieval date.

MDDB serves the full trajectory as raw little-endian float32 xyz with no
header (frame stride = 3 * n_atoms * 4 bytes).  ``/files/trajectory.bin``
ignores HTTP Range, so frame subsetting must go through the
``/trajectory?frames=start:stop:step`` endpoint instead.
"""

from __future__ import annotations

import hashlib
import json
import urllib.request
from pathlib import Path

# MDDB is a federated network of eight nodes, not one database.  The node
# registry lives only on the global API (mdposit); asking any node for
# ``nodes`` answers "only available in the global API".  Accessions are
# node-local -- ``A01M6`` is a MemProtMD membrane system on oxf, something else
# on mmb, and a DynamicPDB entry on bsc -- so a task contract has to carry the
# node alongside the accession.  ``mmb.mddbr.eu`` is a strict subset of the
# registered mmb node (4554 of 9062 projects) and is kept only as a fallback.
NODES = {
    "mmb":  "https://irb-dev.mddbr.eu/api/rest/v1/projects",
    "oxf":  "https://oxford.mddbr.eu/api/rest/v1/projects",
    "cin":  "https://cineca.mddbr.eu/api/rest/v1/projects",
    "bsc":  "https://bsc.mddbr.eu/api/rest/v1/projects",
    "inr":  "https://inria.mddbr.eu/api/rest/v1/projects",
    "jsc":  "https://jsc.mddbr.eu/api/rest/v1/projects",
    "rpbs": "https://rpbs.mddbr.eu/api/rest/v1/projects",
    "ufl":  "https://devmddb.rc.ufl.edu/api/rest/v1/projects",
    "global": "https://mdposit.mddbr.eu/api/rest/v1/projects",
}
API = NODES["mmb"]

# Nodes deposit different topology formats: Amber prmtop on mmb/cin/rpbs,
# GROMACS tpr on bsc/oxf/inr, CHARMM psf on part of inr.  Ask for them in that
# order and record which one arrived.
TOPOLOGIES = ("topology.prmtop", "topology.tpr", "topology.psf", "topology.top")


def get_json(url: str) -> dict:
    with urllib.request.urlopen(url, timeout=120) as response:
        return json.load(response)


def download(url: str, destination: Path) -> Path:
    with urllib.request.urlopen(url, timeout=1800) as response:
        destination.write_bytes(response.read())
    return destination


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def replica_id(accession: str, replica: int | None) -> str:
    """MDDB addresses one MD of a multi-replica project as ``ACCESSION.N``.

    ``A02K9`` and ``A02K9.1`` both give replica 1; ``.2`` and ``.3`` give the
    others, and every analysis and the trajectory endpoint honour the suffix.
    This is what lets the calibration pool windows across replicas: a band
    measured inside one trajectory misses the run-to-run spread, which is the
    spread a submitted independent run actually has (measured on 20 ATLAS
    systems: pooled SD is 1.21x the within-replica SD, up to 1.82x).
    """
    return accession if not replica or replica == 1 else f"{accession}.{replica}"


def frame_count(project: dict, base: str, target: str) -> int:
    """Frames in this MD.  ``totalFrames`` is absent on inr and oxf, and it
    counts every replica when present, so fall back to the length of an
    analysis series, which is per-MD."""
    total = project.get("totalFrames")
    if total:
        return int(total) // max(int(project.get("mdcount") or 1), 1)
    snapshots = (project.get("metadata") or {}).get("SNAPSHOTS")
    if snapshots:
        return int(snapshots)
    series = get_json(f"{base}/{target}/analyses/rmsds").get("data") or []
    for entry in series:
        if entry.get("values"):
            return len(entry["values"])
    raise SystemExit(f"{target}: cannot determine the frame count")


def fetch_reference(accession: str, out: str, n_frames: int = 0,
                    frames: str = None, node: str = "mmb",
                    replica: int | None = None) -> dict:
    """Fetch one project's reference bundle and write its provenance record."""
    out = Path(out)
    out.mkdir(parents=True, exist_ok=True)
    if node not in NODES:
        raise SystemExit(f"unknown MDDB node {node!r}; known: {', '.join(sorted(NODES))}")
    base = NODES[node]
    target = replica_id(accession, replica)
    project = get_json(f"{base}/{target}")
    metadata = project.get("metadata", {})
    if frames is None:
        total = frame_count(project, base, target)
        frames = f"1:{total}:{max(1, total // n_frames)}"
    pca = get_json(f"{base}/{target}/analyses/pca")["data"]

    download(f"{base}/{target}/structure", out / "reference.pdb")
    # The project's own Amber topology. Every prep expectation that used to be
    # inferred -- disulfides from CYX names and SG-SG distance, protonation from
    # residue names in a PDB -- is stated outright here, as a bond list and a
    # residue table. It also settles what the reference did with a metal:
    # MCV1900208 carries the zinc as type Zn2+, charge +2.0, rmin 1.271 A and
    # zero bonds, which is the same 12-6 nonbonded model, with the same
    # parameters, that our own submissions build.
    topology = None
    for name in TOPOLOGIES:
        if name in (project.get("files") or []):
            suffix = name.split(".", 1)[1]
            download(f"{base}/{target}/files/{name}", out / f"reference.{suffix}")
            topology = name
            break
    if topology is None:
        raise SystemExit(f"{target}: no topology file among {', '.join(TOPOLOGIES)}")
    # Two of the project's own analyses, computed over its whole trajectory.
    # They are what the md side compares against, and they arrive as numbers
    # rather than frames: the per-atom fluctuation profile is the reference for
    # the rank comparison, and the per-frame radius of gyration supplies the
    # window band without downloading a single coordinate -- 952 non-overlapping
    # one-nanosecond windows out of a series that is already there.
    # ``rgyr`` is kept because a task's radius-of-gyration band can be measured
    # from it without downloading a coordinate, ``fluctuation`` because it is the
    # profile the rank comparison is against.
    for name in ("fluctuation", "rgyr"):
        (out / f"reference_{name}.json").write_text(
            json.dumps(get_json(f"{base}/{target}/analyses/{name}"), indent=2))
    # Frames are downloaded only when asked for. Nothing reads them: they were
    # the subspace test's input, and that was retired on 2026-08-22. Fetching
    # 500 frames of a hundred references would be gigabytes nothing opens.
    trajectory = None
    if n_frames:
        trajectory = download(f"{base}/{target}/trajectory?frames={frames}",
                              out / "reference_frames.f32")
    (out / "pca_atom_indices.json").write_text(
        json.dumps({"atom_indices": pca["atoms"],
                    "published_eigenvalues": pca["eigenvalues"][:20]}, indent=2))

    frame_bytes = 3 * (metadata.get("SYSTATS") or 0) * 4
    provenance = {
        "database": "MDDB",
        "api": base,
        "node": node,
        "accession": accession,
        "md": target,
        "replica": replica or 1,
        "replica_count": project.get("mdcount") or 1,
        "topology_file": topology,
        "license": metadata.get("LICENSE"),
        "license_url": metadata.get("LINKCENSE"),
        "citation": metadata.get("CITATION"),
        "pdb_ids": metadata.get("PDBIDS"),
        "conditions": {k: metadata.get(k) for k in
                       ("FF", "WAT", "TEMP", "ENSEMBLE", "BOXTYPE", "TIMESTEP",
                        "LENGTH", "PROGRAM", "METHOD")},
        "system": {k: metadata.get(k) for k in
                   ("PROTRES", "PROTATS", "SYSTATS", "SOL", "NA", "CL")},
        "frame_selector": frames if trajectory else None,
        "frame_bytes": frame_bytes,
        "n_frames": (trajectory.stat().st_size // frame_bytes) if trajectory else 0,
        "sha256": {p.name: sha256(p) for p in sorted(out.glob("*"))
                   if p.name != "provenance.json"},
    }
    (out / "provenance.json").write_text(json.dumps(provenance, indent=2))
    return provenance
