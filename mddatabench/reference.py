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

API = "https://mmb.mddbr.eu/api/rest/v1/projects"


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


def fetch_reference(accession: str, out: str, n_frames: int = 500,
                    frames: str = None) -> dict:
    """Fetch one project's reference bundle and write its provenance record."""
    out = Path(out)
    out.mkdir(parents=True, exist_ok=True)
    project = get_json(f"{API}/{accession}")
    metadata = project.get("metadata", {})
    if frames is None:
        total = int(project.get("totalFrames") or metadata.get("SNAPSHOTS"))
        frames = f"1:{total}:{max(1, total // n_frames)}"
    pca = get_json(f"{API}/{accession}/analyses/pca")["data"]

    download(f"{API}/{accession}/structure", out / "reference.pdb")
    trajectory = download(f"{API}/{accession}/trajectory?frames={frames}",
                          out / "reference_frames.f32")
    (out / "pca_atom_indices.json").write_text(
        json.dumps({"atom_indices": pca["atoms"],
                    "published_eigenvalues": pca["eigenvalues"][:20]}, indent=2))

    frame_bytes = 3 * metadata.get("SYSTATS") * 4
    provenance = {
        "database": "MDDB",
        "api": API,
        "accession": accession,
        "license": metadata.get("LICENSE"),
        "license_url": metadata.get("LINKCENSE"),
        "citation": metadata.get("CITATION"),
        "pdb_ids": metadata.get("PDBIDS"),
        "conditions": {k: metadata.get(k) for k in
                       ("FF", "WAT", "TEMP", "ENSEMBLE", "BOXTYPE", "TIMESTEP",
                        "LENGTH", "PROGRAM", "METHOD")},
        "system": {k: metadata.get(k) for k in
                   ("PROTRES", "PROTATS", "SYSTATS", "SOL", "NA", "CL")},
        "frame_selector": frames,
        "frame_bytes": frame_bytes,
        "n_frames": trajectory.stat().st_size // frame_bytes,
        "sha256": {p.name: sha256(p) for p in sorted(out.glob("*"))
                   if p.name != "provenance.json"},
    }
    (out / "provenance.json").write_text(json.dumps(provenance, indent=2))
    return provenance
