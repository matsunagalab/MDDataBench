"""Map one MDCrow attempt onto the portable submission layout.

The converter reads and links. It never builds a System, minimises, runs MD,
edits a structure or fills in a value it did not find. Every file in the
portable layout comes from one recorded file, or, for the two JSON files,
from values the recorder read off the live OpenMM objects.

Which simulation is submitted
-----------------------------
MDCrow may build several OpenMM Simulations in one attempt (a failed try, a
short test, the run it reports). The submitted one is the **last** simulation
that

1. was minimised (states before and after exist),
2. has a DCD reporter whose file exists, and
3. whose last run segment returned normally (not interrupted by the deadline
   or an error).

If none qualifies the attempt has no submission.

File map (``sim`` = the chosen ``record/openmm/sim<n>``)
-------------------------------------------------------
=========================  ==============================================
portable file              source
=========================  ==============================================
prepared.pdb               the structure passed to ``Modeller(...)`` most
                           recently before the Simulation was built
system.topology.pdb        ``sim/pre_min.pdb``
system.system.xml          ``sim/system.xml``
system.state.xml           ``sim/state_pre_min.xml``
minimized_structure.pdb    ``sim/minimized.pdb``
minimized.xml              ``sim/state_post_min.xml``
trajectory.dcd             MDCrow's own DCD (``records/TRAJ_*.dcd``)
energy.dat                 ``sim/state_log.csv``
production.json            written from ``sim/meta.json``
amber_metadata.json        written from ``sim/meta.json``
=========================  ==============================================

``production.json``:

- ``simulation_time_ns``: steps of the production run x step size. The
  production run is the last segment that started at step 0 and everything
  after it (MDCrow equilibrates, resets ``currentStep`` to 0, then runs
  production). The DCD, MDCrow's own, also holds the equilibration frames;
  they are left in.
- ``temperature_kelvin``, ``timestep_fs``: the integrator's.
- ``pressure_bar`` and ``ensemble``: NPT with the barostat's pressure if the
  System has a barostat, else NVT (or NVE without a thermostat).
- ``output_frequency_ps``: the DCD reporter interval x step size.

``amber_metadata.json``:

- ``forcefield_provenance.openmm_xml``: the files given to ``ForceField``.
- ``parameters.water_model``: the water file among them, written as given
  minus ``.xml`` (``amber14/tip3pfb.xml`` -> ``amber14/tip3pfb``). Absent if
  no file is a water model; the scorer then reads the System.

Stdlib only. Writes ``<attempt>/submission/`` (symlinks plus the two JSON
files) and ``<attempt>/conversion.json`` (the decision and its reasons).
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import sys
from pathlib import Path

WATER_STEMS = {"tip3p", "tip3pfb", "tip4pew", "tip4pfb", "tip5p", "spce", "opc", "opc3",
               "tip3p-pme-b", "tip3p-pme-f", "water", "spce_standard", "tip3p_standard",
               "tip4p2005", "swm4ndp"}

LINKED = {
    "system.topology.pdb": "pre_min.pdb",
    "system.system.xml": "system.xml",
    "system.state.xml": "state_pre_min.xml",
    "minimized_structure.pdb": "minimized.pdb",
    "minimized.xml": "state_post_min.xml",
    "energy.dat": "state_log.csv",
}


def _json(path: Path):
    return json.loads(Path(path).read_text())


def water_model(files: list[str]) -> str | None:
    for name in files:
        stem = name[:-4] if name.endswith(".xml") else name
        if stem.rsplit("/", 1)[-1].lower() in WATER_STEMS:
            return stem
    return None


def find_dcd(meta: dict, ckpt_roots: list[Path]) -> Path | None:
    """MDCrow's DCD: where the reporter opened it, else moved into ``records/``."""
    for reporter in meta.get("reporters") or []:
        if reporter.get("type") != "DCDReporter" or not reporter.get("file"):
            continue
        opened = Path(reporter["file"])
        if opened.is_file():
            return opened
        for root in ckpt_roots:
            for candidate in sorted(root.glob(f"**/records/{opened.name}")):
                if candidate.is_file():
                    return candidate
    return None


def production_steps(segments: list[dict]) -> int:
    if not segments:
        return 0
    starts = [i for i, s in enumerate(segments) if s.get("start_step") == 0]
    first = starts[-1] if starts else 0
    return sum(int(s.get("end_step", s["start_step"])) - int(s["start_step"])
               for s in segments[first:])


def eligibility(sim_dir: Path, ckpt_roots: list[Path]) -> tuple[bool, list[str], Path | None]:
    reasons = []
    meta_path = sim_dir / "meta.json"
    if not meta_path.is_file():
        return False, ["no meta.json"], None
    meta = _json(meta_path)
    for name in ("system.xml", "state_pre_min.xml", "state_post_min.xml", "pre_min.pdb",
                 "minimized.pdb", "state_log.csv"):
        if not (sim_dir / name).is_file():
            reasons.append(f"no {name}")
    dcd = find_dcd(meta, ckpt_roots)
    if dcd is None:
        reasons.append("no DCD reporter file")
    segments = meta.get("segments") or []
    if not segments:
        reasons.append("never stepped")
    elif not segments[-1].get("completed"):
        reasons.append("last run segment did not return")
    if production_steps(segments) <= 0:
        reasons.append("no production steps")
    return not reasons, reasons, dcd


def production_record(meta: dict) -> dict:
    integrator = meta.get("integrator") or {}
    system = meta.get("system") or {}
    barostat = system.get("barostat")
    step_ps = integrator.get("step_size_ps")
    steps = production_steps(meta.get("segments") or [])
    dcd_interval = next((r.get("interval_steps") for r in meta.get("reporters") or []
                         if r.get("type") == "DCDReporter"), None)
    temperature = integrator.get("temperature_kelvin")
    if barostat:
        ensemble, pressure = "NPT", barostat.get("pressure_bar")
    else:
        ensemble = "NVT" if temperature is not None else "NVE"
        pressure = None
    hydrogen = meta.get("max_hydrogen_mass_dalton")
    record = {
        "simulation_time_ns": (steps * step_ps / 1000.0) if step_ps else None,
        "temperature_kelvin": temperature,
        "pressure_bar": pressure,
        "timestep_fs": step_ps * 1000.0 if step_ps else None,
        "output_frequency_ps": dcd_interval * step_ps if dcd_interval and step_ps else None,
        "system_signature": {"ensemble": ensemble, "pressure_bar": pressure},
        "hmr": bool(hydrogen and hydrogen > 1.5),
        "production_steps": steps,
        "integrator": integrator.get("type"),
        "barostat": barostat,
        "nonbonded": system.get("nonbonded"),
        "platform": meta.get("platform"),
        "source": "mddatabench.mdcrow_baseline.recorder (read off the live OpenMM objects)",
    }
    # A value that was not found is left out, not written as null.
    return {key: value for key, value in record.items() if value is not None}


def amber_record(meta: dict) -> dict:
    forcefield = meta.get("forcefield") or {}
    files = list(forcefield.get("files") or [])
    parameters = {}
    water = water_model(files)
    if water is not None:
        parameters["water_model"] = water
    return {
        "parameters": parameters,
        "forcefield_provenance": {
            "openmm_xml": files,
            "template_generators": forcefield.get("template_generators") or [],
            "create_system_kwargs": forcefield.get("kwargs") or {},
        },
        "source": "mddatabench.mdcrow_baseline.recorder (ForceField arguments as called)",
    }


def _link(source: Path, destination: Path) -> None:
    os.symlink(os.path.relpath(source.resolve(), destination.parent.resolve()), destination)


def convert(attempt_dir: str) -> dict:
    """Write ``submission/`` and ``conversion.json`` for one attempt."""
    attempt = Path(attempt_dir).resolve()
    workspace = attempt / "workspace"
    record = attempt / "record"
    openmm_dir = record / "openmm"
    submission = attempt / "submission"
    if submission.exists():
        shutil.rmtree(submission)
    ckpt_roots = [workspace / "ckpt"]
    report = {"schema_version": 1, "attempt": str(attempt), "simulations": [],
              "chosen": None, "files": {}, "submission": None}
    sims = sorted((p for p in openmm_dir.glob("sim*") if p.is_dir()
                   and p.name[3:].isdigit()), key=lambda p: int(p.name[3:]))
    chosen = None
    for sim in sims:
        ok, reasons, dcd = eligibility(sim, ckpt_roots)
        report["simulations"].append({"sim": sim.name, "eligible": ok, "reasons": reasons,
                                      "dcd": str(dcd) if dcd else None})
        if ok:
            chosen = (sim, dcd)
    if chosen is None:
        report["reason"] = ("no simulation was recorded" if not sims else
                            "no simulation was minimised, wrote a DCD and finished its run")
        (attempt / "conversion.json").write_text(json.dumps(report, indent=2))
        return {"success": True, "submission": None, **report}

    sim, dcd = chosen
    meta = _json(sim / "meta.json")
    report["chosen"] = sim.name
    prepared = meta.get("input_structure")
    prepared = Path(prepared) if prepared else None
    if prepared is not None and not prepared.is_absolute():
        prepared = openmm_dir / prepared
    if prepared is not None and not prepared.is_file():
        # The recorder writes absolute paths as seen inside the sandbox, where
        # the attempt sits at the same path; fall back to the file name.
        prepared = openmm_dir / prepared.name
    submission.mkdir()
    sources = {name: sim / source for name, source in LINKED.items()}
    sources["trajectory.dcd"] = dcd
    if prepared is not None and prepared.is_file():
        sources["prepared.pdb"] = prepared
    else:
        report["missing"] = ["prepared.pdb: no Modeller input structure was recorded"]
    for name, source in sorted(sources.items()):
        _link(source, submission / name)
        report["files"][name] = str(source)
    (submission / "production.json").write_text(json.dumps(production_record(meta), indent=2))
    (submission / "amber_metadata.json").write_text(json.dumps(amber_record(meta), indent=2))
    report["files"]["production.json"] = f"written from {sim / 'meta.json'}"
    report["files"]["amber_metadata.json"] = f"written from {sim / 'meta.json'}"
    report["submission"] = str(submission)
    registry = next(iter(sorted(workspace.glob("ckpt/*/paths_registry.json"))), None)
    if registry is not None:
        report["mdcrow_registry"] = str(registry)
    (attempt / "conversion.json").write_text(json.dumps(report, indent=2))
    return {"success": True, **report}


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("--attempt-dir", required=True)
    args = parser.parse_args(argv)
    print(json.dumps(convert(args.attempt_dir), indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
