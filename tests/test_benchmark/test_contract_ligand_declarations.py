"""Every ligand atom among a task's md contract atoms has a scorer declaration.

The md contract atoms are MDDB's PCA atom list, picked by atom name, so a ligand
named like a backbone (6MJ7's free arginine, 6RNT's 2'-AMP) contributes atoms.
The scorer can place those only through one declared SMILES per residue name
(``atom_mapping.ligand_correspondence``). Tasks 105 and 106 shipped without it
and every submission scored the md checks "not evaluable" (2026-10-31); the
cast's 042 carries one. Needs the reference bundles (``MDDATABENCH_BUNDLE_ROOT``).
"""

import json
import os
import sys
from pathlib import Path

import pytest

from mddatabench.topology import POLYMER_RESIDUES

REPO = Path(__file__).resolve().parents[2]
TASKS = REPO / "benchmarks" / "mddatabench" / "tasks"
ROOT = os.environ.get("MDDATABENCH_BUNDLE_ROOT")


def _bundle(task):
    if not ROOT:
        pytest.skip("MDDATABENCH_BUNDLE_ROOT is not set")
    reference = task["reference"]
    bundle = Path(ROOT) / f"{reference['node']}_{reference['accession']}"
    if not (bundle / "pca_atom_indices.json").is_file():
        pytest.skip(f"no bundle at {bundle}")
    return bundle


def _contract_ligands(bundle):
    indices = set(json.loads((bundle / "pca_atom_indices.json").read_text())["atom_indices"])
    names, index = set(), 0
    for line in (bundle / "reference.pdb").read_text().splitlines():
        if line.startswith(("ATOM", "HETATM")):
            name = line[17:21].strip()
            if index in indices and name not in POLYMER_RESIDUES:
                names.add(name)
            index += 1
    return names


@pytest.mark.parametrize("task_dir", sorted(p.parent for p in TASKS.glob("*/task.json")),
                         ids=lambda p: p.name)
def test_contract_ligand_atoms_are_declared(task_dir):
    task = json.loads((task_dir / "task.json").read_text())
    declared = {}
    for entry in task["reference"].get("extra_components") or []:
        declared.setdefault(entry.get("residue_name"), []).append(entry)
    for name in _contract_ligands(_bundle(task)):
        assert len(declared.get(name, [])) == 1 and declared[name][0].get("smiles"), (
            f"{task_dir.name}: contract atoms in non-polymer {name} without one declared SMILES")


@pytest.mark.parametrize("task_id", ["105_ligand_6mj7", "106_metal_6rnt"])
def test_test_split_declarations_are_reproduced(task_id):
    sys.path.insert(0, str(REPO / "scripts"))
    bt = pytest.importorskip("build_test_tasks")
    pytest.importorskip("rdkit")
    task = json.loads((TASKS / task_id / "task.json").read_text())
    report = Path("/data1/rkp00079/rku00161/testset-20261031/build/build_report.json")
    if not report.is_file():
        pytest.skip("build report not available")
    ligands = {t["task_id"]: t["ligands"] for t in json.loads(report.read_text())["tasks"]}
    assert bt.contract_ligand_declarations(_bundle(task), ligands[task_id]) == \
        task["reference"]["extra_components"]
