"""The MDCrow converter maps recorded files; it never makes one up.

Stdlib only: the recorded files are stand-ins, the rules are what is tested.
"""

import json
import os
from pathlib import Path

from mddatabench.mdcrow_baseline import convert as cv
from mddatabench.mdcrow_baseline.campaign import classify, wilson
from mddatabench.portable import PORTABLE_FILES


def _sim(openmm_dir: Path, index: int, dcd: Path, *, segments, minimized=True,
         files=("amber99sbildn.xml", "tip3p.xml"), barostat=True, modeller="modeller_0.pdb"):
    sim = openmm_dir / f"sim{index}"
    sim.mkdir(parents=True)
    names = ["system.xml", "state_log.csv", "pre_min.pdb"]
    if minimized:
        names += ["state_pre_min.xml", "state_post_min.xml", "minimized.pdb"]
    for name in names:
        (sim / name).write_text(f"{name} of sim{index}\n")
    meta = {
        "index": index, "platform": "CUDA",
        "system": {"particles": 10, "barostat": ({"type": "MonteCarloBarostat",
                                                  "pressure_bar": 1.0} if barostat else None),
                   "nonbonded": {"method": "PME", "cutoff_nm": 1.0}},
        "integrator": {"type": "LangevinMiddleIntegrator", "step_size_ps": 0.002,
                       "temperature_kelvin": 300.0},
        "forcefield": {"files": list(files), "template_generators": [], "kwargs": {}},
        "max_hydrogen_mass_dalton": 1.008,
        "input_structure": str(openmm_dir / modeller) if modeller else None,
        "reporters": [{"type": "DCDReporter", "file": str(dcd), "interval_steps": 5000}],
        "segments": segments,
    }
    (sim / "meta.json").write_text(json.dumps(meta))
    return sim


def _attempt(tmp_path: Path) -> Path:
    attempt = tmp_path / "attempt"
    (attempt / "workspace" / "ckpt" / "ckpt_0" / "records").mkdir(parents=True)
    (attempt / "record" / "openmm").mkdir(parents=True)
    (attempt / "record" / "openmm" / "modeller_0.pdb").write_text("input\n")
    return attempt


EQ_AND_PROD = [{"start_step": 0, "end_step": 1000, "completed": True},
               {"start_step": 0, "end_step": 500000, "completed": True}]


def test_maps_every_portable_file_and_moved_dcd(tmp_path):
    attempt = _attempt(tmp_path)
    records = attempt / "workspace" / "ckpt" / "ckpt_0" / "records"
    (records / "TRAJ_sim0.dcd").write_text("dcd")
    # The reporter opened the DCD in the cwd; MDCrow moved it to records/.
    _sim(attempt / "record" / "openmm", 0, attempt / "workspace" / "TRAJ_sim0.dcd",
         segments=EQ_AND_PROD)
    report = cv.convert(str(attempt))
    submission = attempt / "submission"
    assert report["chosen"] == "sim0"
    assert {p.name for p in submission.iterdir()} == PORTABLE_FILES
    assert (submission / "trajectory.dcd").resolve() == (records / "TRAJ_sim0.dcd").resolve()
    assert (submission / "system.state.xml").read_text() == "state_pre_min.xml of sim0\n"
    assert (submission / "minimized.xml").read_text() == "state_post_min.xml of sim0\n"
    assert (submission / "prepared.pdb").read_text() == "input\n"
    # Links, not copies: nothing is rewritten.
    assert all(os.path.islink(submission / n) for n in cv.LINKED)


def test_production_is_the_last_run_from_step_zero(tmp_path):
    attempt = _attempt(tmp_path)
    dcd = attempt / "workspace" / "TRAJ.dcd"
    dcd.write_text("dcd")
    _sim(attempt / "record" / "openmm", 0, dcd, segments=EQ_AND_PROD)
    cv.convert(str(attempt))
    production = json.loads((attempt / "submission" / "production.json").read_text())
    assert production["production_steps"] == 500000
    assert abs(production["simulation_time_ns"] - 1.0) < 1e-12
    assert production["timestep_fs"] == 2.0
    assert production["output_frequency_ps"] == 10.0
    assert production["system_signature"] == {"ensemble": "NPT", "pressure_bar": 1.0}
    assert production["hmr"] is False


def test_nvt_has_no_pressure_written(tmp_path):
    attempt = _attempt(tmp_path)
    dcd = attempt / "workspace" / "TRAJ.dcd"
    dcd.write_text("dcd")
    _sim(attempt / "record" / "openmm", 0, dcd, segments=EQ_AND_PROD, barostat=False)
    cv.convert(str(attempt))
    production = json.loads((attempt / "submission" / "production.json").read_text())
    assert production["system_signature"]["ensemble"] == "NVT"
    assert "pressure_bar" not in production


def test_water_model_is_the_file_name_as_given(tmp_path):
    assert cv.water_model(["amber14-all.xml", "amber14/tip3pfb.xml"]) == "amber14/tip3pfb"
    assert cv.water_model(["amber99sbildn.xml", "tip3p.xml"]) == "tip3p"
    assert cv.water_model(["amber14-all.xml"]) is None
    attempt = _attempt(tmp_path)
    dcd = attempt / "workspace" / "TRAJ.dcd"
    dcd.write_text("dcd")
    _sim(attempt / "record" / "openmm", 0, dcd, segments=EQ_AND_PROD,
         files=("amber14-all.xml",))
    cv.convert(str(attempt))
    amber = json.loads((attempt / "submission" / "amber_metadata.json").read_text())
    assert amber["parameters"] == {}
    assert amber["forcefield_provenance"]["openmm_xml"] == ["amber14-all.xml"]


def test_last_eligible_simulation_wins(tmp_path):
    attempt = _attempt(tmp_path)
    openmm_dir = attempt / "record" / "openmm"
    for name in ("a.dcd", "b.dcd", "c.dcd"):
        (attempt / "workspace" / name).write_text(name)
    _sim(openmm_dir, 0, attempt / "workspace" / "a.dcd", segments=EQ_AND_PROD)
    _sim(openmm_dir, 1, attempt / "workspace" / "b.dcd", segments=EQ_AND_PROD)
    # sim2 was interrupted mid-production: it is not a submission.
    _sim(openmm_dir, 2, attempt / "workspace" / "c.dcd",
         segments=[{"start_step": 0, "end_step": 1000, "completed": True},
                   {"start_step": 0, "end_step": 1200, "completed": False}])
    report = cv.convert(str(attempt))
    assert report["chosen"] == "sim1"
    assert [s["eligible"] for s in report["simulations"]] == [True, True, False]
    assert "last run segment did not return" in report["simulations"][2]["reasons"]


def test_no_submission_without_minimisation_or_dcd(tmp_path):
    attempt = _attempt(tmp_path)
    openmm_dir = attempt / "record" / "openmm"
    (attempt / "workspace" / "a.dcd").write_text("a")
    _sim(openmm_dir, 0, attempt / "workspace" / "a.dcd", segments=EQ_AND_PROD,
         minimized=False)
    _sim(openmm_dir, 1, attempt / "workspace" / "missing.dcd", segments=EQ_AND_PROD)
    report = cv.convert(str(attempt))
    assert report["submission"] is None
    assert not (attempt / "submission").exists()
    assert json.loads((attempt / "conversion.json").read_text())["chosen"] is None


def test_missing_input_structure_is_left_missing(tmp_path):
    attempt = _attempt(tmp_path)
    dcd = attempt / "workspace" / "TRAJ.dcd"
    dcd.write_text("dcd")
    _sim(attempt / "record" / "openmm", 0, dcd, segments=EQ_AND_PROD, modeller=None)
    report = cv.convert(str(attempt))
    assert not (attempt / "submission" / "prepared.pdb").exists()
    assert report["missing"]


def _score(passed, total=20):
    return {"passed": passed, "total": total,
            "checks": [{"check_id": f"c{i}", "passed": i < passed} for i in range(total)]}


def test_classify():
    ok = {"exit_reason": "completed"}
    done = {"state": "COMPLETED"}
    assert classify(ok, done, {}, _score(20), "0")["passed"] is True
    assert classify(ok, done, {}, _score(19), "0")["failure_code"] == "checks_failed"
    assert classify(ok, done, {"reason": "x"}, None, "none")["failure_code"] == "agent_no_submission"
    assert classify({"exit_reason": "deadline"}, done, {}, None, "none")["failure_code"] == "agent_timeout"
    # A run that finished before the deadline is still scored, and can pass.
    assert classify({"exit_reason": "deadline"}, done, {}, _score(20), "0")["passed"] is True
    assert classify(None, {"state": "NODE_FAIL"}, None, None, "none")["failure_stage"] == "infra"
    assert classify(None, {"state": "OUT_OF_MEMORY"}, None, None, "none")["failure_stage"] == "infra"
    assert classify({"exit_reason": "exception", "error": "APIConnectionError('x')"}, done,
                    None, None, "none")["failure_code"] == "infra_gateway"
    assert classify({"exit_reason": "exception", "error": "ValueError('parse')"}, done,
                    None, None, "none")["failure_code"] == "agent_exception"
    assert classify(None, {"state": "TIMEOUT"}, None, None, "none")["failure_code"] == "agent_timeout"
    assert classify(ok, done, {}, None, "1")["failure_code"] == "scorer_error"


def test_wilson_matches_known_values():
    low, high = wilson(0, 31)
    assert low == 0.0 and abs(high - 0.1103) < 1e-3
    low, high = wilson(31, 31)
    assert abs(low - 0.8897) < 1e-3 and high == 1.0
