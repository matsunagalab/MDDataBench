"""Score one MDDataBench submission against its task contract.

Everything is recomputed from the submitted artifacts.  Values the agent
reports are never used.  The artifact paths this reads are recorded in the
task contract under ``scorer_field_map``; they were established by solving
the tasks with MDClaw, because guessing them produced false failures:

- the water model lives at ``parameters.water_model`` in the topo node's
  ``amber_metadata.json``, not at its top level
- the barostat is added at run time, so the topo node's ``system.xml`` has
  none; the ensemble must be read from the prod node's metadata
- the contract atoms must be matched by (residue number, atom name); the
  submitted topology contains solvent, so raw atom indices do not line up
"""

from __future__ import annotations

from mddatabench import _threads  # noqa: F401  must precede numpy

import json
import pathlib

import mdtraj as md
import numpy as np
import openmm as mm

from mddatabench import execution as ex
from mddatabench import subspace as st


def pdb_atoms(path):
    rows = []
    for line in open(path):
        if line.startswith(("ATOM", "HETATM")):
            rows.append((line[21], line[22:27].strip(), line[12:16].strip(),
                         (float(line[30:38]), float(line[38:46]), float(line[46:54])),
                         (line[76:78].strip() or line[12:16].strip()[0]).upper(),
                         line[17:20].strip()))
    return rows


def find_node(job_dir: pathlib.Path, node_type: str) -> pathlib.Path:
    """Latest completed node of a type."""
    best = None
    for node in sorted((job_dir / "nodes").iterdir()):
        meta = node / "node.json"
        if not meta.exists():
            continue
        data = json.loads(meta.read_text())
        if data.get("node_type") == node_type and data.get("status") == "completed":
            best = node
    if best is None:
        raise SystemExit(f"no completed {node_type} node under {job_dir}")
    return best


def score(job_dir: pathlib.Path, bundle: pathlib.Path, task: dict) -> dict:
    prep, topo, prod = (find_node(job_dir, t) for t in ("prep", "topo", "prod"))
    amber = json.loads((topo / "artifacts" / "amber_metadata.json").read_text())
    prod_meta = json.loads((prod / "node.json").read_text()).get("metadata", {})
    signature = prod_meta.get("system_signature", {})
    expect = task["reference"]["reference_system"]
    results = []

    categories = {c["check_id"]: c.get("category", "prep")
                  for c in task["scoring"]["deterministic_checks"]}

    def check(check_id, passed, detail):
        results.append({"check_id": check_id, "category": categories.get(check_id, "prep"),
                        "passed": bool(passed), "detail": detail})

    prepared = next((prep / "artifacts" / "merge").glob("*.pdb"))
    atoms = pdb_atoms(prepared)
    heavy = sum(1 for a in atoms if a[4] != "H")
    residues = {(a[0], a[1]) for a in atoms}
    chains = {a[0] for a in atoms}

    check("sequence_matches_reference",
          len(residues) == expect["PROTRES"] and len(chains) == 1,
          f"{len(residues)} residues (expect {expect['PROTRES']}), {len(chains)} chain")
    check("protein_heavy_atom_count_matches_reference",
          heavy == expect["heavy_atoms"] and len(atoms) == expect["PROTATS"],
          f"heavy {heavy}/{expect['heavy_atoms']}, total {len(atoms)}/{expect['PROTATS']}")

    completion = next((c for c in task["scoring"]["deterministic_checks"]
                       if c["check_id"] == "truncated_sidechains_completed"), None)
    if completion is not None:
        per_residue = {}
        for a in atoms:
            if a[4] != "H":
                per_residue[f"{a[0]}:{a[1]}"] = per_residue.get(f"{a[0]}:{a[1]}", 0) + 1
        want = completion["expected_heavy_atoms_per_residue"]
        short = {k: per_residue.get(k, 0) for k in completion["expected_complete_residues"]
                 if per_residue.get(k, 0) != want}
        check("truncated_sidechains_completed", not short,
              f"{len(completion['expected_complete_residues'])} truncated side chains, "
              f"each expected {want} heavy atoms"
              + (f"; still short: {short}" if short else "; all complete"))

    system = mm.XmlSerializer.deserialize((topo / "artifacts" / "system.system.xml").read_text())
    nonbonded = next(f for f in system.getForces() if isinstance(f, mm.NonbondedForce))
    charge = sum(nonbonded.getParticleParameters(i)[0]
                 .value_in_unit(mm.unit.elementary_charge)
                 for i in range(nonbonded.getNumParticles()))
    check("topology_loads_and_is_parameterized", system.getNumParticles() > 0,
          f"{system.getNumParticles()} particles, System deserialised")
    check("forcefield_applied_to_every_atom",
          nonbonded.getNumParticles() == system.getNumParticles(),
          f"NonbondedForce covers {nonbonded.getNumParticles()}/{system.getNumParticles()}")
    check("system_is_neutral", abs(charge) < 1e-4, f"net charge {charge:+.2e} e")

    water = str(amber["parameters"].get("water_model") or "").lower()
    xmls = " ".join(amber["forcefield_provenance"].get("openmm_xml") or []).lower()
    wanted = task["reference"]["reference_conditions"]["WAT"].lower()
    check("water_model_matches_reference", wanted in water and wanted in xmls,
          f"parameters.water_model={water!r}, forcefield xml carries {wanted}: {wanted in xmls}")

    temperature = float(prod_meta.get("temperature_kelvin", 0.0))
    check("thermodynamic_conditions_match_reference",
          abs(temperature - float(task["reference"]["reference_conditions"]["TEMP"])) <= 1.0
          and signature.get("ensemble") == task["reference"]["reference_conditions"]["ENSEMBLE"],
          f"T={temperature} K, ensemble={signature.get('ensemble')}, P={prod_meta.get('pressure_bar')} bar")
    check("production_ran_for_one_nanosecond",
          float(prod_meta.get("simulation_time_ns", 0.0)) >= 1.0,
          f"{prod_meta.get('simulation_time_ns')} ns at {prod_meta.get('timestep_fs')} fs "
          f"(HMR={prod_meta.get('hmr')})")

    traj_path = next((prod / "artifacts").glob("*.dcd"))

    # --- essential subspace, both sides recomputed under the pinned contract ---
    reference_atoms = pdb_atoms(bundle / "reference.pdb")
    indices = json.loads((bundle / "pca_atom_indices.json").read_text())["atom_indices"]
    keys = [(reference_atoms[i][1], reference_atoms[i][2]) for i in indices]
    reference_xyz = np.array([reference_atoms[i][3] for i in indices])

    topology_pdb = topo / "artifacts" / "system.topology.pdb"
    lookup = {}
    for n, row in enumerate(pdb_atoms(topology_pdb)):
        lookup.setdefault((row[1], row[2]), n)
    missing = [k for k in keys if k not in lookup]
    own_indices = np.array([lookup[k] for k in keys if k in lookup])

    frames = np.fromfile(bundle / "reference_frames.f32", dtype="<f4")
    frames = frames.reshape(-1, expect["PROTATS"], 3).astype(np.float64)[:, indices, :]
    _, reference_subspace = st.essential_subspace(frames, reference_xyz)

    traj = md.load(str(traj_path), top=str(topology_pdb))

    claimed = float(prod_meta.get("simulation_time_ns", 0.0)) * 1000.0
    clock = ex.elapsed_time_ps(traj)
    spec_time = next(c for c in task["scoring"]["deterministic_checks"]
                     if c["check_id"] == "elapsed_simulated_time_is_physical")
    if not clock["measurable"]:
        check("elapsed_simulated_time_is_physical", False,
              f"not measurable: {clock['reason']}")
    else:
        ratio = clock["elapsed_ps"] / claimed if claimed else 0.0
        check("elapsed_simulated_time_is_physical",
              ratio >= spec_time["minimum_measured_fraction_of_claim"],
              f"solvent clock says {clock['elapsed_ps']:.0f} ps against a claimed "
              f"{claimed:.0f} ps (ratio {ratio:.2f}), "
              f"D={clock['diffusion_1e5_cm2_s']:.2f}e-5 cm2/s")
    check("contract_atoms_resolvable", not missing,
          f"{len(own_indices)}/{len(keys)} contract atoms matched by (residue, atom name)"
          + (f"; missing {missing[:4]}" if missing else ""))

    own = traj.xyz[:, own_indices, :] * 10.0
    _, own_subspace = st.essential_subspace(own, reference_xyz)
    test = st.test_beyond_structure(own_subspace, reference_subspace, reference_xyz)
    check("subspace_beyond_structure_only_model", test["h0_rejected"],
          f"RMSIP={test['rmsip']:.3f} vs structure-only null "
          f"{test['null_mean']:.3f}+/-{test['null_sd']:.3f} (max {test['null_max']:.3f}), "
          f"z={test['z_score']:.2f}, p<={test['p_value_upper_bound']:.2f}")

    rg = md.compute_rg(traj.atom_slice(traj.topology.select("protein")))
    band = next(c for c in task["scoring"]["deterministic_checks"]
                if c["check_id"] == "radius_of_gyration_is_physical")
    check("radius_of_gyration_is_physical",
          band["minimum"] <= rg.mean() <= band["maximum"],
          f"Rg={rg.mean():.4f} nm (band {band['minimum']}-{band['maximum']})")

    by_category = {}
    for row in results:
        bucket = by_category.setdefault(row["category"], {"passed": 0, "total": 0})
        bucket["total"] += 1
        bucket["passed"] += int(row["passed"])
    return {"task_id": task["task_id"], "checks": results, "by_category": by_category,
            "passed": sum(1 for r in results if r["passed"]), "total": len(results),
            "diagnostics": {"rmsip": test["rmsip"], "z_score": test["z_score"],
                            "canonical_correlations": test["canonical_correlations"],
                            "rg_mean_nm": float(rg.mean()), "n_frames": int(traj.n_frames)}}


