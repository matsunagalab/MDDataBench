"""Recompute potential energies from the submitted system, never read them.

The runner writes a ``minimization_report.json`` saying what its energies were.
That is the same class of claim as ``simulation_time_ns``, which the solvent
clock exists to distrust, so these checks deserialise the submitted
``system.xml`` and evaluate it themselves at the submitted states.

Two things are graded, both of them gates:

- the built system is energetically sane: a finite single-point energy whose
  magnitude per particle is below a ceiling.  The ceiling is the one
  MDPrepBench uses (``_MAX_ABS_PREP_ENERGY_PER_PARTICLE_KJ_MOL``); it catches
  clash-driven 1e20 kJ/mol systems and nothing else, deliberately.
- minimisation actually lowered the energy.

The per-particle value itself is NOT graded.  Measured 2026-08-21 on ff14SB +
TIP3P it sits at -17.00 / -16.93 / -16.94 kJ/mol/atom for D01 / D02 / D03,
which is tight enough to be tempting and is three systems on one force field
and one water model.  Under this suite's rule that nothing is scored against an
uncalibrated threshold it is recorded as a diagnostic until the accumulated
values justify a band.
"""

from __future__ import annotations

from mddatabench import _threads  # noqa: F401  must precede numpy

import math

import numpy as np
import openmm as mm

# Above this a finite energy is still physically meaningless: a bad box or a
# forced overlap. Borrowed from MDPrepBench, where it was set to catch
# Packmol-forced membrane outputs at 1e20 kJ/mol.
MAX_ABS_ENERGY_PER_PARTICLE_KJ_MOL = 1.0e6


def single_point(system, state_xml_text: str) -> dict:
    """Potential energy and maximum force of ``system`` at a serialised state."""
    try:
        state = mm.XmlSerializer.deserialize(state_xml_text)
    except Exception as exc:                                        # noqa: BLE001
        return {"ok": False, "reason": f"state XML did not deserialise: {type(exc).__name__}"}

    try:
        platform = mm.Platform.getPlatformByName("CPU")
    except Exception:                                               # noqa: BLE001
        platform = mm.Platform.getPlatformByName("Reference")
    try:
        context = mm.Context(system, mm.VerletIntegrator(1.0 * mm.unit.femtosecond), platform)
        context.setState(state)
        snapshot = context.getState(getEnergy=True, getForces=True, getPositions=True)
        energy = snapshot.getPotentialEnergy().value_in_unit(mm.unit.kilojoule_per_mole)
        forces = snapshot.getForces(asNumpy=True).value_in_unit(
            mm.unit.kilojoule_per_mole / mm.unit.nanometer)
        positions = snapshot.getPositions(asNumpy=True).value_in_unit(mm.unit.nanometer)
    except Exception as exc:                                        # noqa: BLE001
        return {"ok": False, "reason": f"energy evaluation failed: {type(exc).__name__}: {exc}"}
    finally:
        context = None

    particles = max(1, system.getNumParticles())
    return {"ok": True,
            "energy_kj_mol": float(energy),
            "energy_per_particle_kj_mol": float(energy) / particles,
            "max_force_kj_mol_nm": float(np.abs(forces).max()),
            "energy_is_finite": bool(math.isfinite(float(energy))),
            "positions_are_finite": bool(np.isfinite(positions).all()),
            "particle_count": int(particles)}


def is_physical(point: dict, ceiling=MAX_ABS_ENERGY_PER_PARTICLE_KJ_MOL) -> tuple[bool, str]:
    """Gate: finite energy and positions, magnitude per particle below the ceiling."""
    if not point["ok"]:
        return False, point["reason"]
    if not point["energy_is_finite"]:
        return False, f"potential energy is not finite: {point['energy_kj_mol']!r}"
    if not point["positions_are_finite"]:
        return False, "positions contain NaN or Inf"
    per_particle = abs(point["energy_per_particle_kj_mol"])
    if per_particle > ceiling:
        return False, (f"energy is finite but physically implausible: "
                       f"{point['energy_kj_mol']:.6g} kJ/mol "
                       f"({per_particle:.6g} kJ/mol/particle)")
    return True, (f"{point['energy_kj_mol']:.0f} kJ/mol over {point['particle_count']} particles "
                  f"({point['energy_per_particle_kj_mol']:.2f} kJ/mol/particle)")
