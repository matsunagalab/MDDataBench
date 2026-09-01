"""Slow release check for topology-derived task boundary contracts."""

from __future__ import annotations

import json
import os
import pathlib

import pytest

from mddatabench import contract_audit as ca


DATASET = pathlib.Path(__file__).resolve().parents[2] / "benchmarks" / "mddatabench"
BUNDLE_ROOT = os.environ.get("MDDATABENCH_BUNDLE_ROOT")

pytestmark = [
    pytest.mark.slow,
    pytest.mark.skipif(
        not BUNDLE_ROOT or not pathlib.Path(BUNDLE_ROOT).is_dir(),
        reason="set MDDATABENCH_BUNDLE_ROOT to a fetched bundle tree",
    ),
]


def test_all_98_task_boundaries_match_their_reference_topologies():
    tasks = sorted(DATASET.glob("tasks/*/task.json"))
    assert len(tasks) == 98
    failures = []
    for task_json in tasks:
        task_dir = task_json.parent
        spec = json.loads(task_json.read_text())
        reference_spec = spec["reference"]
        selection = reference_spec["selection"]
        prompt = (task_dir / "prompt.md").read_text()
        reference, _ = ca._reference_backbone_contract(
            pathlib.Path(BUNDLE_ROOT)
            / f"{reference_spec['node']}_{reference_spec['accession']}")
        for pdb_id in reference_spec["pdb_ids"]:
            deposit = DATASET / "_deposits" / f"{pdb_id.upper()}.cif"
            findings = ca._boundary_contract_findings(
                prompt, selection, ca._declared(prompt),
                ca.deposit_polymer_scheme(deposit), reference)
            if findings:
                failures.append((task_dir.name, pdb_id, findings))
    assert failures == []
