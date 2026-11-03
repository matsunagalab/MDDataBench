"""Observation hooks around ``openmm.app.Simulation`` for the MDCrow baseline.

MDCrow b3b0b57 runs OpenMM inside its own process and keeps a trajectory, a
PDB of the minimised system and a tab-separated log of step, potential energy
and temperature. It never serialises the System, never keeps a state before
or after minimisation, and its log has no box volume or density. The portable
submission needs all of these.

This module records them from the live objects while MDCrow runs, so the
converter only has to map files. Nothing here changes what is simulated:

- the System is serialised as built, after ``Simulation.__init__``;
- states are read with ``getState`` before and after ``minimizeEnergy``;
- one extra ``StateDataReporter`` is attached at the first step, writing to
  its own file at the interval of MDCrow's own DCD reporter;
- ``Simulation._simulate`` (behind ``step`` and ``runForClockTime``) is
  wrapped to note where each run segment started and whether it returned.

``substitute_platform`` is the one intervention: MDCrow asks for OpenMM's
``CPU`` platform by name; the runner sends that request to ``CUDA``. It is
off unless the runner turns it on, and every substitution is logged.

Layout, under ``out_dir``::

    events.jsonl              every hook event, in order
    modeller_<k>.pdb          a Modeller built outside openmm (its input structure)
    sim<n>/system.xml         the System as built
    sim<n>/meta.json          integrator, barostat, force field files, reporters, segments
    sim<n>/pre_min.pdb        positions before the first minimisation
    sim<n>/state_pre_min.xml  state before the first minimisation
    sim<n>/minimized.pdb      positions after the last minimisation
    sim<n>/state_post_min.xml state after the last minimisation
    sim<n>/state_log.csv      StateDataReporter: step, time, energies, T, volume, density

Requires only openmm. Imports nothing from mddatabench.
"""

from __future__ import annotations

import functools
import json
import os
import sys
import threading
import time
from pathlib import Path

import openmm
import openmm.app as app
import openmm.unit as unit

_LOCK = threading.RLock()
_DEFAULT_LOG_INTERVAL = 1000


def _now() -> float:
    return round(time.time(), 3)


def _quantity(value, target):
    try:
        return float(value.value_in_unit(target))
    except AttributeError:
        return float(value)


class Recorder:
    """Install with :meth:`install`; one instance per process."""

    def __init__(self, out_dir, substitute_platform: str | None = None):
        self.out = Path(out_dir).resolve()
        self.out.mkdir(parents=True, exist_ok=True)
        self.substitute_platform = substitute_platform
        self.simulations = 0
        self.modellers = 0
        self.last_modeller_pdb = None
        self._installed = False
        self._originals = {}
        self._forcefield_by_system = {}
        self._systems = []          # keep Systems alive so id() stays unique

    # ---- bookkeeping -------------------------------------------------------

    def event(self, kind: str, **fields) -> None:
        with _LOCK, open(self.out / "events.jsonl", "a") as handle:
            handle.write(json.dumps({"t": _now(), "event": kind, **fields}, default=str) + "\n")

    def _sim_dir(self, simulation) -> Path | None:
        index = getattr(simulation, "_mddb_index", None)
        return None if index is None else self.out / f"sim{index}"

    def _meta(self, simulation) -> dict:
        return simulation._mddb_meta

    def _write_meta(self, simulation) -> None:
        directory = self._sim_dir(simulation)
        with _LOCK:
            tmp = directory / "meta.json.tmp"
            tmp.write_text(json.dumps(self._meta(simulation), indent=2, default=str))
            os.replace(tmp, directory / "meta.json")

    # ---- describing objects ------------------------------------------------

    @staticmethod
    def describe_system(system) -> dict:
        forces = []
        nonbonded = None
        barostat = None
        for index in range(system.getNumForces()):
            force = system.getForce(index)
            name = type(force).__name__
            forces.append(name)
            if isinstance(force, openmm.NonbondedForce):
                methods = {openmm.NonbondedForce.NoCutoff: "NoCutoff",
                           openmm.NonbondedForce.CutoffNonPeriodic: "CutoffNonPeriodic",
                           openmm.NonbondedForce.CutoffPeriodic: "CutoffPeriodic",
                           openmm.NonbondedForce.Ewald: "Ewald",
                           openmm.NonbondedForce.PME: "PME",
                           openmm.NonbondedForce.LJPME: "LJPME"}
                nonbonded = {"method": methods.get(force.getNonbondedMethod(),
                                                   str(force.getNonbondedMethod())),
                             "cutoff_nm": _quantity(force.getCutoffDistance(), unit.nanometer)}
            if "Barostat" in name:
                entry = {"type": name}
                for getter, key, target in (
                        ("getDefaultPressure", "pressure_bar", unit.bar),
                        ("getDefaultTemperature", "temperature_kelvin", unit.kelvin),
                        ("getFrequency", "frequency_steps", None)):
                    if hasattr(force, getter):
                        value = getattr(force, getter)()
                        entry[key] = (_quantity(value, target) if target is not None
                                      else int(value))
                barostat = entry
        return {"particles": system.getNumParticles(),
                "constraints": system.getNumConstraints(),
                "periodic": bool(system.usesPeriodicBoundaryConditions()),
                "forces": forces, "nonbonded": nonbonded, "barostat": barostat}

    @staticmethod
    def describe_integrator(integrator) -> dict:
        entry = {"type": type(integrator).__name__}
        if hasattr(integrator, "getStepSize"):
            entry["step_size_ps"] = _quantity(integrator.getStepSize(), unit.picosecond)
        if hasattr(integrator, "getTemperature"):
            entry["temperature_kelvin"] = _quantity(integrator.getTemperature(), unit.kelvin)
        if hasattr(integrator, "getFriction"):
            entry["friction_per_ps"] = _quantity(integrator.getFriction(), unit.picosecond ** -1)
        return entry

    @staticmethod
    def max_hydrogen_mass(topology, system) -> float | None:
        masses = [_quantity(system.getParticleMass(atom.index), unit.dalton)
                  for atom in topology.atoms()
                  if atom.element is not None and atom.element.symbol == "H"]
        return max(masses) if masses else None

    # ---- hooks ---------------------------------------------------------------

    def _hook_platform(self) -> None:
        original = openmm.Platform.getPlatformByName
        self._originals["getPlatformByName"] = original
        recorder = self

        @functools.wraps(original)
        def getPlatformByName(name):
            if recorder.substitute_platform and name == "CPU":
                recorder.event("platform_substituted", requested=name,
                               used=recorder.substitute_platform)
                return original(recorder.substitute_platform)
            return original(name)

        openmm.Platform.getPlatformByName = staticmethod(getPlatformByName)

    def _hook_forcefield(self) -> None:
        init = app.ForceField.__init__
        create = app.ForceField.createSystem
        recorder = self

        @functools.wraps(init)
        def __init__(self, *files):
            init(self, *files)
            self._mddb_files = [str(f) for f in files]

        # wraps(): ForceField.createSystem checks its own signature for unused
        # keyword arguments (openmm 8.6 argtracker); the wrapper must present it.
        @functools.wraps(create)
        def createSystem(self, topology, *args, **kwargs):
            system = create(self, topology, *args, **kwargs)
            generators = [type(g).__name__ for g in getattr(self, "_templateGenerators", [])]
            record = {"files": list(getattr(self, "_mddb_files", [])),
                      "template_generators": generators,
                      "kwargs": {k: str(v) for k, v in kwargs.items()}}
            recorder._forcefield_by_system[id(system)] = record
            recorder._systems.append(system)
            recorder.event("create_system", **record)
            return system

        app.ForceField.__init__ = __init__
        app.ForceField.createSystem = createSystem

    def _hook_modeller(self) -> None:
        init = app.Modeller.__init__
        recorder = self

        @functools.wraps(init)
        def __init__(self, topology, positions):
            init(self, topology, positions)
            # openmm.app builds Modellers of its own inside addSolvent and the
            # like; only one built by the caller is an input structure.
            caller = sys._getframe(1).f_globals.get("__name__", "")
            if caller.startswith("openmm."):
                return
            try:
                with _LOCK:
                    index = recorder.modellers
                    recorder.modellers += 1
                path = recorder.out / f"modeller_{index}.pdb"
                with open(path, "w") as handle:
                    app.PDBFile.writeFile(topology, positions, handle, keepIds=True)
                recorder.last_modeller_pdb = str(path)
                recorder.event("modeller", index=index, path=str(path),
                               atoms=topology.getNumAtoms(), caller=caller)
            except Exception as exc:                                  # noqa: BLE001
                recorder.event("modeller_record_failed", error=repr(exc))

        app.Modeller.__init__ = __init__

    def _hook_simulation(self) -> None:
        init = app.Simulation.__init__
        minimize = app.Simulation.minimizeEnergy
        simulate = app.Simulation._simulate
        recorder = self

        @functools.wraps(init)
        def __init__(self, topology, system, integrator, platform=None,
                     platformProperties=None, state=None):
            init(self, topology, system, integrator, platform, platformProperties, state)
            try:
                recorder._on_simulation(self, topology, system, integrator)
            except Exception as exc:                                  # noqa: BLE001
                recorder.event("simulation_record_failed", error=repr(exc))

        @functools.wraps(minimize)
        def minimizeEnergy(self, *args, **kwargs):
            recorder._on_minimize(self, before=True)
            result = minimize(self, *args, **kwargs)
            recorder._on_minimize(self, before=False)
            return result

        @functools.wraps(simulate)
        def _simulate(self, *args, **kwargs):
            segment = recorder._on_segment_start(self)
            completed = False
            try:
                result = simulate(self, *args, **kwargs)
                completed = True
                return result
            finally:
                recorder._on_segment_end(self, segment, completed)

        app.Simulation.__init__ = __init__
        app.Simulation.minimizeEnergy = minimizeEnergy
        app.Simulation._simulate = _simulate

    def install(self) -> "Recorder":
        if self._installed:
            return self
        self._hook_platform()
        self._hook_forcefield()
        self._hook_modeller()
        self._hook_simulation()
        self._installed = True
        self.event("recorder_installed", substitute_platform=self.substitute_platform,
                   openmm=openmm.__version__)
        return self

    # ---- what each hook records --------------------------------------------

    def _on_simulation(self, simulation, topology, system, integrator) -> None:
        with _LOCK:
            index = self.simulations
            self.simulations += 1
        simulation._mddb_index = index
        directory = self._sim_dir(simulation)
        directory.mkdir(parents=True, exist_ok=True)
        (directory / "system.xml").write_text(openmm.XmlSerializer.serialize(system))
        simulation._mddb_meta = {
            "index": index,
            "created": _now(),
            "platform": simulation.context.getPlatform().getName(),
            "platform_properties": {
                name: simulation.context.getPlatform().getPropertyValue(simulation.context, name)
                for name in simulation.context.getPlatform().getPropertyNames()},
            "system": self.describe_system(system),
            "integrator": self.describe_integrator(integrator),
            "forcefield": self._forcefield_by_system.get(id(system)),
            "max_hydrogen_mass_dalton": self.max_hydrogen_mass(topology, system),
            "input_structure": self.last_modeller_pdb,
            "minimizations": 0,
            "reporters": [],
            "segments": [],
            "state_log": None,
        }
        self._write_meta(simulation)
        self.event("simulation", index=index, particles=system.getNumParticles(),
                   platform=simulation._mddb_meta["platform"])

    def _state(self, simulation):
        return simulation.context.getState(getPositions=True, getVelocities=True,
                                           getEnergy=True, getParameters=True)

    def _on_minimize(self, simulation, before: bool) -> None:
        directory = self._sim_dir(simulation)
        if directory is None:
            return
        try:
            meta = self._meta(simulation)
            state = self._state(simulation)
            energy = _quantity(state.getPotentialEnergy(), unit.kilojoule_per_mole)
            if before:
                if meta["minimizations"] == 0:
                    (directory / "state_pre_min.xml").write_text(
                        openmm.XmlSerializer.serialize(state))
                    with open(directory / "pre_min.pdb", "w") as handle:
                        app.PDBFile.writeFile(simulation.topology, state.getPositions(),
                                              handle, keepIds=True)
                    meta["pre_min_energy_kj_mol"] = energy
            else:
                meta["minimizations"] += 1
                (directory / "state_post_min.xml").write_text(
                    openmm.XmlSerializer.serialize(state))
                with open(directory / "minimized.pdb", "w") as handle:
                    app.PDBFile.writeFile(simulation.topology, state.getPositions(),
                                          handle, keepIds=True)
                meta["post_min_energy_kj_mol"] = energy
                meta["post_min_step"] = int(simulation.currentStep)
            self._write_meta(simulation)
            self.event("minimize_" + ("start" if before else "end"),
                       index=meta["index"], energy_kj_mol=energy)
        except Exception as exc:                                      # noqa: BLE001
            self.event("minimize_record_failed", error=repr(exc))

    def _attach_state_log(self, simulation) -> None:
        meta = self._meta(simulation)
        reporters = []
        interval = None
        for reporter in simulation.reporters:
            entry = {"type": type(reporter).__name__}
            out = getattr(reporter, "_out", None)
            name = getattr(out, "name", None) if out is not None else None
            if isinstance(name, str):
                entry["file"] = os.path.abspath(name)
            report_interval = getattr(reporter, "_reportInterval", None)
            if report_interval is not None:
                entry["interval_steps"] = int(report_interval)
            reporters.append(entry)
            if entry["type"] == "DCDReporter" and interval is None:
                interval = entry.get("interval_steps")
        meta["reporters"] = reporters
        interval = int(interval or _DEFAULT_LOG_INTERVAL)
        path = self._sim_dir(simulation) / "state_log.csv"
        simulation.reporters.append(app.StateDataReporter(
            str(path), interval, step=True, time=True, potentialEnergy=True,
            kineticEnergy=True, totalEnergy=True, temperature=True, volume=True,
            density=True))
        simulation._mddb_log_attached = True
        meta["state_log"] = {"file": str(path), "interval_steps": interval}

    def _on_segment_start(self, simulation) -> dict | None:
        if self._sim_dir(simulation) is None:
            return None
        try:
            if not getattr(simulation, "_mddb_log_attached", False):
                self._attach_state_log(simulation)
            meta = self._meta(simulation)
            segment = {"start_step": int(simulation.currentStep), "t0": _now(),
                       "completed": False}
            meta["segments"].append(segment)
            self._write_meta(simulation)
            return segment
        except Exception as exc:                                      # noqa: BLE001
            self.event("segment_record_failed", error=repr(exc))
            return None

    def _on_segment_end(self, simulation, segment, completed: bool) -> None:
        if segment is None:
            return
        try:
            segment.update(end_step=int(simulation.currentStep), t1=_now(),
                           completed=bool(completed))
            self._write_meta(simulation)
            self.event("segment", index=self._meta(simulation)["index"], **segment)
        except Exception as exc:                                      # noqa: BLE001
            self.event("segment_record_failed", error=repr(exc))
