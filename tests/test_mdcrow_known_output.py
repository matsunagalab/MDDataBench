"""Conversion does not change a score: a known submission, laid out as MDCrow
and the recorder would leave it, scores check-for-check as it did.

The known outputs are passed sif_only attempts (neither MDClaw's nor
MDCrow's): their portable files are rearranged into ``record/openmm/sim0``
and MDCrow's ``ckpt/*/records`` (symlinks), a ``meta.json`` is written from
their own production.json and amber_metadata.json, the converter runs, and
both submissions go through ``score_portable``.

Slow, and needs the scorer stack and the reference bundles:

    MDCROW_KNOWN_ATTEMPTS=<attempt dir>[:<attempt dir>...]
    MDDATABENCH_BUNDLE_ROOT=/data1/rkp00079/rku00161/references
"""

import json
import os
from pathlib import Path

import pytest

pytestmark = pytest.mark.slow

ATTEMPTS = [Path(p) for p in os.environ.get("MDCROW_KNOWN_ATTEMPTS", "").split(":") if p]
BUNDLES = Path(os.environ.get("MDDATABENCH_BUNDLE_ROOT", "/nonexistent"))
ROOT = Path(__file__).resolve().parents[1]


def mdcrow_layout(submission: Path, attempt: Path) -> None:
    """Lay a portable submission out the way an MDCrow attempt is recorded."""
    production = json.loads((submission / "production.json").read_text())
    amber = json.loads((submission / "amber_metadata.json").read_text())
    openmm_dir = attempt / "record" / "openmm"
    sim = openmm_dir / "sim0"
    records = attempt / "workspace" / "ckpt" / "ckpt_0" / "records"
    sim.mkdir(parents=True)
    records.mkdir(parents=True)
    links = {openmm_dir / "modeller_0.pdb": "prepared.pdb",
             sim / "system.xml": "system.system.xml",
             sim / "state_pre_min.xml": "system.state.xml",
             sim / "state_post_min.xml": "minimized.xml",
             sim / "pre_min.pdb": "system.topology.pdb",
             sim / "minimized.pdb": "minimized_structure.pdb",
             sim / "state_log.csv": "energy.dat",
             records / "TRAJ_sim0_known.dcd": "trajectory.dcd"}
    for link, name in links.items():
        os.symlink((submission / name).resolve(), link)
    step_ps = production["timestep_fs"] / 1000.0
    steps = round(production["simulation_time_ns"] * 1000.0 / step_ps)
    ensemble = production["system_signature"]["ensemble"]
    meta = {
        "index": 0, "platform": production.get("platform"),
        "system": {"barostat": ({"type": "MonteCarloBarostat",
                                 "pressure_bar": production["system_signature"]["pressure_bar"]}
                                if ensemble == "NPT" else None)},
        "integrator": {"type": production.get("integrator"), "step_size_ps": step_ps,
                       "temperature_kelvin": production["temperature_kelvin"]},
        "forcefield": {"files": amber["forcefield_provenance"]["openmm_xml"]},
        "max_hydrogen_mass_dalton": 3.0 if production.get("hmr") else 1.008,
        "input_structure": str(openmm_dir / "modeller_0.pdb"),
        "reporters": [{"type": "DCDReporter",
                       "file": str(attempt / "workspace" / "TRAJ_sim0_known.dcd"),
                       "interval_steps": round(production["output_frequency_ps"] / step_ps)}],
        "segments": [{"start_step": 0, "end_step": 1000, "completed": True},
                     {"start_step": 0, "end_step": steps, "completed": True}],
    }
    (sim / "meta.json").write_text(json.dumps(meta))


@pytest.mark.skipif(not ATTEMPTS, reason="MDCROW_KNOWN_ATTEMPTS not set")
@pytest.mark.parametrize("known", ATTEMPTS, ids=[p.parent.name + "/" + p.name for p in ATTEMPTS])
def test_known_submission_scores_the_same_after_conversion(known, tmp_path):
    from mddatabench.mdcrow_baseline.convert import convert
    from mddatabench.portable import score_portable

    manifest = json.loads((known / "manifest.json").read_text())
    task = json.loads(Path(manifest["paths"]["task_file"]).read_text())
    bundle = BUNDLES / f"{task['reference']['node']}_{task['reference']['accession']}"
    original = known / "workspace" / "submission"
    attempt = tmp_path / "attempt"
    mdcrow_layout(original, attempt)
    report = convert(str(attempt))
    assert report["chosen"] == "sim0", report

    before = score_portable(original, bundle, task)
    after = score_portable(attempt / "submission", bundle, task)
    assert (after["passed"], after["total"]) == (before["passed"], before["total"])
    by_id = {c["check_id"]: c for c in before["checks"]}
    for check in after["checks"]:
        assert check["passed"] == by_id[check["check_id"]]["passed"], check["check_id"]
