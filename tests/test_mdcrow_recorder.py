"""The recorder writes what OpenMM actually ran, and the converter maps it.

Runs a tiny water box the way MDCrow's SetUpandRunFunction does (Modeller,
ForceField.createSystem, Simulation on a platform asked for by name,
minimise, equilibrate, reset currentStep, produce) in a subprocess, because
the recorder patches OpenMM process-wide. Needs openmm; the platform request
for "CPU" is answered with "Reference" so it runs without a GPU.
"""

import json
import subprocess
import sys
import textwrap
from pathlib import Path

import pytest

openmm = pytest.importorskip("openmm")

ROOT = Path(__file__).resolve().parents[1]

SCRIPT = textwrap.dedent("""
    import sys
    from pathlib import Path
    sys.path.insert(0, {recorder_dir!r})
    from recorder import Recorder
    attempt = Path({attempt!r})
    recorder = Recorder(attempt / "record" / "openmm", substitute_platform="Reference").install()

    import openmm, openmm.app as app, openmm.unit as u
    from openmm import Platform
    forcefield = app.ForceField("amber14-all.xml", "amber14/tip3p.xml")
    modeller = app.Modeller(app.Topology(), [])
    modeller.addSolvent(forcefield, boxSize=openmm.Vec3(1.6, 1.6, 1.6) * u.nanometer)
    system = forcefield.createSystem(modeller.topology, nonbondedMethod=app.PME,
                                     nonbondedCutoff=0.7 * u.nanometer, constraints=app.HBonds)
    system.addForce(openmm.MonteCarloBarostat(1 * u.bar, 300 * u.kelvin, 25))
    integrator = openmm.LangevinMiddleIntegrator(300 * u.kelvin, 1 / u.picosecond,
                                                 0.002 * u.picoseconds)
    simulation = app.Simulation(modeller.topology, system, integrator,
                                Platform.getPlatformByName("CPU"))
    simulation.context.setPositions(modeller.positions)
    workspace = attempt / "workspace"
    simulation.reporters.append(app.DCDReporter(str(workspace / "TRAJ_sim0_x.dcd"), 10))
    simulation.minimizeEnergy(maxIterations=50)
    simulation.context.setVelocitiesToTemperature(300 * u.kelvin)
    simulation.step(20)
    simulation.currentStep = 0
    simulation.step(60)
    print(simulation.context.getPlatform().getName())
""")


def test_recorder_then_convert(tmp_path):
    attempt = tmp_path / "attempt"
    (attempt / "workspace").mkdir(parents=True)
    script = SCRIPT.format(recorder_dir=str(ROOT / "mddatabench" / "mdcrow_baseline"),
                           attempt=str(attempt))
    completed = subprocess.run([sys.executable, "-c", script], cwd=attempt / "workspace",
                               capture_output=True, text=True, timeout=600)
    assert completed.returncode == 0, completed.stderr[-3000:]
    assert completed.stdout.strip().splitlines()[-1] == "Reference"

    sim = attempt / "record" / "openmm" / "sim0"
    meta = json.loads((sim / "meta.json").read_text())
    assert meta["platform"] == "Reference"
    assert meta["forcefield"]["files"] == ["amber14-all.xml", "amber14/tip3p.xml"]
    assert meta["system"]["barostat"]["pressure_bar"] == pytest.approx(1.0)
    assert meta["integrator"]["step_size_ps"] == pytest.approx(0.002)
    assert [(s["start_step"], s["end_step"], s["completed"]) for s in meta["segments"]] == \
        [(0, 20, True), (0, 60, True)]
    assert meta["reporters"][0]["type"] == "DCDReporter"
    assert meta["state_log"]["interval_steps"] == 10
    events = [json.loads(line)["event"] for line in
              (attempt / "record" / "openmm" / "events.jsonl").read_text().splitlines()]
    assert "platform_substituted" in events
    # Minimisation lowered the energy, as recorded around the call itself.
    assert meta["post_min_energy_kj_mol"] < meta["pre_min_energy_kj_mol"]
    # The state log has what the scorer reads and MDCrow's own log lacks.
    header = (sim / "state_log.csv").read_text().splitlines()[0]
    for column in ("Temperature (K)", "Box Volume (nm^3)", "Density (g/mL)"):
        assert column in header
    # Serialised System and states load back.
    system = openmm.XmlSerializer.deserialize((sim / "system.xml").read_text())
    state = openmm.XmlSerializer.deserialize((sim / "state_pre_min.xml").read_text())
    assert system.getNumParticles() == len(state.getPositions())

    from mddatabench.mdcrow_baseline.convert import convert
    report = convert(str(attempt))
    assert report["chosen"] == "sim0"
    production = json.loads((attempt / "submission" / "production.json").read_text())
    assert production["production_steps"] == 60
    assert production["system_signature"]["ensemble"] == "NPT"
    amber = json.loads((attempt / "submission" / "amber_metadata.json").read_text())
    assert amber["parameters"]["water_model"] == "amber14/tip3p"
