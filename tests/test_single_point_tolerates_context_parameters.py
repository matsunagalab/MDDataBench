"""A state saved under a barostat still evaluates against a System without one.

040_ligand_3n2u sif_only r3 (campaign v2): the submitted state.xml carried
``MonteCarloPressure`` from an NPT context, the submitted system.xml had no
barostat, and ``Context.setState`` refused the state, so the energy gate
reported "energy evaluation failed" instead of an energy.
"""

import openmm as mm
from openmm import unit

from mddatabench import energetics


def _argon_system(with_barostat):
    system = mm.System()
    nb = mm.NonbondedForce()
    nb.setNonbondedMethod(mm.NonbondedForce.CutoffPeriodic)
    nb.setCutoffDistance(0.9 * unit.nanometer)
    for _ in range(8):
        system.addParticle(39.9)
        nb.addParticle(0.0, 0.34, 0.99)
    system.addForce(nb)
    system.setDefaultPeriodicBoxVectors(mm.Vec3(3, 0, 0), mm.Vec3(0, 3, 0), mm.Vec3(0, 0, 3))
    if with_barostat:
        system.addForce(mm.MonteCarloBarostat(1.0 * unit.bar, 300 * unit.kelvin))
    return system


def _npt_state_xml():
    system = _argon_system(with_barostat=True)
    context = mm.Context(system, mm.VerletIntegrator(1.0 * unit.femtosecond), mm.Platform.getPlatformByName("Reference"))
    context.setPositions([mm.Vec3(0.4 * i, 0.5 * i, 0.6 * i) for i in range(8)])
    state = context.getState(getPositions=True, getVelocities=True, getParameters=True, enforcePeriodicBox=True)
    assert "MonteCarloPressure" in dict(state.getParameters())
    return mm.XmlSerializer.serialize(state)


def test_npt_state_evaluates_against_a_system_without_barostat():
    point = energetics.single_point(_argon_system(with_barostat=False), _npt_state_xml())
    assert point["ok"], point
    assert point["energy_is_finite"] and point["particle_count"] == 8


def test_the_parameters_still_apply_when_the_system_defines_them():
    point = energetics.single_point(_argon_system(with_barostat=True), _npt_state_xml())
    assert point["ok"], point


def test_a_state_saved_without_parameters_still_evaluates():
    """mdclaw's state.xml carries no parameters; the lenient load must not ask for them.

    2026-09-14: both energy checks of every scored attempt failed with
    "Invoked getParameters() on a State which does not contain parameters".
    """
    system = _argon_system(with_barostat=False)
    context = mm.Context(system, mm.VerletIntegrator(1.0 * unit.femtosecond), mm.Platform.getPlatformByName("Reference"))
    context.setPositions([mm.Vec3(0.4 * i, 0.5 * i, 0.6 * i) for i in range(8)])
    state_xml = mm.XmlSerializer.serialize(context.getState(getPositions=True, enforcePeriodicBox=True))
    result = energetics.single_point(_argon_system(with_barostat=False), state_xml)
    assert result["ok"], result
    assert result["energy_kj_mol"] is not None
