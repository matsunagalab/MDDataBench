"""Read-only adapter for submissions made without the MDClaw CLI."""

from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path


PORTABLE_FILES = {
    "prepared.pdb",
    "system.topology.pdb",
    "system.system.xml",
    "system.state.xml",
    "amber_metadata.json",
    "minimized_structure.pdb",
    "minimized.xml",
    "trajectory.dcd",
    "energy.dat",
    "production.json",
}


def _node(root: Path, node_id: str, node_type: str, parents: list[str],
          artifacts: dict, metadata: dict | None = None) -> Path:
    node = root / "nodes" / node_id
    (node / "artifacts").mkdir(parents=True)
    (node / "node.json").write_text(json.dumps({
        "schema_version": 3,
        "node_id": node_id,
        "node_type": node_type,
        "status": "completed",
        "parent_node_ids": parents,
        "dependency_node_ids": [],
        "artifacts": artifacts,
        "metadata": metadata or {},
    }, indent=2))
    return node


def _link(source: Path, destination: Path) -> None:
    os.symlink(source.resolve(), destination)


def score_portable(submission: Path, bundle: Path, task: dict) -> dict:
    """Score a fixed portable layout through the unchanged DAG scorer.

    The temporary DAG contains symlinks only.  It neither repairs nor copies the
    submission, and disappears after scoring.
    """
    from mddatabench.scoring import _unrunnable, score

    missing = sorted(name for name in PORTABLE_FILES if not (submission / name).is_file())
    if missing:
        return _unrunnable(task, f"portable submission is missing: {', '.join(missing)}")
    try:
        production = json.loads((submission / "production.json").read_text())
    except (OSError, json.JSONDecodeError) as exc:
        return _unrunnable(task, f"production.json is invalid: {exc}")

    with tempfile.TemporaryDirectory(prefix="mddatabench-portable-") as temporary:
        root = Path(temporary)
        prep = _node(root, "prep_001", "prep", [],
                     {"merged_pdb": "artifacts/prepared.pdb"})
        topo = _node(root, "topo_001", "topo", ["prep_001"], {
            "topology_pdb": "artifacts/system.topology.pdb",
            "system_xml": "artifacts/system.system.xml",
            "state_xml": "artifacts/system.state.xml",
            "amber_metadata": "artifacts/amber_metadata.json",
        })
        minimized = _node(root, "min_001", "min", ["topo_001"], {
            "final_structure": "artifacts/minimized_structure.pdb",
            "state": "artifacts/minimized.xml",
        })
        prod = _node(root, "prod_001", "prod", ["min_001"], {
            "trajectory": "artifacts/trajectory.dcd",
            "energy": "artifacts/energy.dat",
        }, production)
        mapping = {
            prep: ["prepared.pdb"],
            topo: ["system.topology.pdb", "system.system.xml", "system.state.xml",
                   "amber_metadata.json"],
            minimized: ["minimized_structure.pdb", "minimized.xml"],
            prod: ["trajectory.dcd", "energy.dat"],
        }
        for node, names in mapping.items():
            for name in names:
                _link(submission / name, node / "artifacts" / name)
        return score(root, bundle, task)
