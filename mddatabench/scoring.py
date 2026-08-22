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

from mddatabench import composition as cp
from mddatabench import energetics as en
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


def _read_nodes(job_dir: pathlib.Path) -> dict:
    """Every node of a job, keyed by node id, as (directory, node.json)."""
    nodes = {}
    for node in sorted((job_dir / "nodes").iterdir()):
        meta = node / "node.json"
        if meta.exists():
            nodes[node.name] = (node, json.loads(meta.read_text()))
    return nodes


def _production_lineage(nodes: dict) -> list:
    """Node ids the latest completed production node descends from, it first."""
    completed_prod = sorted(name for name, (_, data) in nodes.items()
                            if data.get("node_type") == "prod"
                            and data.get("status") == "completed")
    if not completed_prod:
        return []
    order, queue, seen = [], [completed_prod[-1]], set()
    while queue:
        name = queue.pop(0)
        if name in seen or name not in nodes:
            continue
        seen.add(name)
        order.append(name)
        queue.extend(nodes[name][1].get("parent_node_ids") or [])
    return order


def find_node(job_dir: pathlib.Path, node_type: str) -> pathlib.Path:
    """The node of a type that the scored trajectory actually descends from.

    Taking the highest-numbered completed node of each type grades whatever was
    built last rather than what was simulated, and a DAG that allows retries
    routinely has both.  Measured on the three PLpro runs: d03-6wrh carries two
    completed topo nodes with min built from topo_002, and d04-4ow0 carries two
    completed prep nodes with only prep_004 on the line that reached prod.  The
    old rule happened to agree there; nothing made it agree.  Walk
    ``parent_node_ids`` back from the production node instead, and fall back to
    the latest completed node only when no lineage is recorded.
    """
    nodes = _read_nodes(job_dir)
    for name in _production_lineage(nodes):
        if nodes[name][1].get("node_type") == node_type:
            return nodes[name][0]
    best = None
    for name, (node, data) in nodes.items():
        if data.get("node_type") == node_type and data.get("status") == "completed":
            best = node
    if best is None:
        raise SystemExit(f"no completed {node_type} node under {job_dir}")
    return best


def _load_system(path: pathlib.Path):
    """Deserialise a submitted OpenMM System. Returns (system, error_message)."""
    try:
        system = mm.XmlSerializer.deserialize(path.read_text())
    except Exception as exc:                                        # noqa: BLE001
        return None, f"{path.name} did not deserialise: {type(exc).__name__}: {exc}"
    if not isinstance(system, mm.System):
        return None, f"{path.name} deserialised to {type(system).__name__}, not a System"
    if system.getNumParticles() <= 0:
        return None, f"{path.name} deserialised to a System with no particles"
    return system, None


def _minimized_state(job_dir: pathlib.Path):
    """Serialised state of the latest completed min node, or None."""
    try:
        node = find_node(job_dir, "min")
    except SystemExit:
        return None
    artifacts = node / "artifacts"
    return next(iter(sorted(artifacts.glob("minimized*.xml"))
                     or sorted(artifacts.glob("*.xml"))), None)


def score(job_dir: pathlib.Path, bundle: pathlib.Path, task: dict) -> dict:
    prep, topo, prod = (find_node(job_dir, t) for t in ("prep", "topo", "prod"))
    amber = json.loads((topo / "artifacts" / "amber_metadata.json").read_text())
    prod_meta = json.loads((prod / "node.json").read_text()).get("metadata", {})
    signature = prod_meta.get("system_signature", {})
    expect = task["reference"]["reference_system"]
    results = []

    spec = {c["check_id"]: c for c in task["scoring"]["deterministic_checks"]}

    def check(check_id, passed, detail):
        entry = spec.get(check_id, {})
        results.append({"check_id": check_id, "category": entry.get("category", "prep"),
                        "weight": float(entry.get("weight", 1.0)),
                        "passed": bool(passed), "detail": detail})

    # --- composition, per monomer ---------------------------------------------
    # Split both sides into covalently connected chains and match them by
    # canonical sequence. Everything below runs inside a matched pair, so a
    # multimer is N monomers rather than a special case, and a failure is
    # attributable to a chain and a residue instead of to a total.
    prepared = next((prep / "artifacts" / "merge").glob("*.pdb"))
    topology_pdb = topo / "artifacts" / "system.topology.pdb"
    reference_monomers = cp.split_monomers(cp.read_residues(bundle / "reference.pdb"))
    submitted_monomers = cp.split_monomers(cp.read_residues(prepared))

    pairs, mismatches = cp.match_monomers(reference_monomers, submitted_monomers)
    check("monomer_count_matches_reference", not mismatches,
          f"{len(reference_monomers)} reference monomer(s), {len(submitted_monomers)} submitted"
          + ("; " + "; ".join(mismatches) if mismatches else "; all sequences pair up"))

    findings = {"sequence": [], "atom_counts": [], "elements": []}
    for reference_monomer, submitted_monomer in pairs:
        for key, value in cp.compare_monomer(reference_monomer, submitted_monomer).items():
            findings[key].extend(value)

    residue_total = sum(len(m) for m in reference_monomers)
    check("sequence_matches_reference", not mismatches and not findings["sequence"],
          f"{sum(len(m) for m in submitted_monomers)} residues (expect {residue_total}) "
          f"in {len(submitted_monomers)} monomer(s)"
          + ("; not compared: no monomer pairing" if mismatches else
             f"; sequence differs at {findings['sequence'][:4]}" if findings["sequence"]
             else "; identical after canonicalising protonation"))

    # Per-residue atom counts. Tautomer-blind by construction (HID and HIE have
    # the same formula) and sensitive to every ionisation and bonding variant,
    # which is what the old total-atom tolerance of +/-2 was silently letting
    # through: one HIP costs exactly one hydrogen.
    check("residue_atom_counts_match_reference", not mismatches and not findings["atom_counts"],
          f"{residue_total} residues compared per monomer"
          + ("; not compared: no monomer pairing" if mismatches else
             f"; {len(findings['atom_counts'])} differ: {findings['atom_counts'][:4]}"
             if findings["atom_counts"] else "; every residue matches, tautomers tolerated"))

    reference_elements = cp.element_totals(reference_monomers)
    submitted_elements = cp.element_totals(submitted_monomers)
    check("element_composition_matches_reference",
          reference_elements == submitted_elements and not findings["elements"],
          f"heavy atoms by element {submitted_elements} vs reference {reference_elements}"
          + (f"; per-residue differences {findings['elements'][:3]}"
             if findings["elements"] else ""))

    submitted_atoms = cp.atom_totals(submitted_monomers)
    check("protein_atom_count_matches_reference", submitted_atoms == expect["PROTATS"],
          f"total {submitted_atoms}/{expect['PROTATS']} atoms "
          f"(exact: an ionisation error is one hydrogen)")

    # --- disulfides, always, zero included ------------------------------------
    spec_ss = next(c for c in task["scoring"]["deterministic_checks"]
                   if c["check_id"] == "disulfide_bonds_match_reference")
    expected_ss, cyx = cp.reference_disulfides(
        reference_monomers, cutoff=spec_ss["maximum_sg_distance_angstrom"])
    observed_ss, unusable = cp.submitted_disulfides(topology_pdb, submitted_monomers)
    if unusable:
        check("disulfide_bonds_match_reference", False, unusable)
    else:
        check("disulfide_bonds_match_reference", expected_ss == observed_ss,
              f"reference has {cyx} CYX -> {len(expected_ss)} pair(s) "
              f"{cp.describe_pairs(expected_ss)}; submitted topology CONECT gives "
              f"{len(observed_ss)} {cp.describe_pairs(observed_ss)}"
              + ("" if expected_ss == observed_ss else "; sets differ"))

    # Reading the System is a precondition, not an achievement: a file that will
    # not deserialise leaves the scorer unable to look at the force field at all.
    # It used to raise straight out of the scorer, so a broken submission crashed
    # the run instead of being recorded; everything below is reported either way.
    system, load_error = _load_system(topo / "artifacts" / "system.system.xml")
    check("topology_loads_and_is_parameterized", load_error is None,
          load_error or f"{system.getNumParticles()} particles, System deserialised")

    nonbonded = None if system is None else next(
        (f for f in system.getForces() if isinstance(f, mm.NonbondedForce)), None)
    if nonbonded is None:
        reason = load_error or "the System carries no NonbondedForce: no force field was applied"
        check("forcefield_applied_to_every_atom", False, reason)
        check("system_is_neutral", False, reason)
    else:
        charge = sum(nonbonded.getParticleParameters(i)[0]
                     .value_in_unit(mm.unit.elementary_charge)
                     for i in range(nonbonded.getNumParticles()))
        check("forcefield_applied_to_every_atom",
              nonbonded.getNumParticles() == system.getNumParticles(),
              f"NonbondedForce covers {nonbonded.getNumParticles()}/{system.getNumParticles()}")
        spec_charge = next(c for c in task["scoring"]["deterministic_checks"]
                           if c["check_id"] == "system_is_neutral")
        check("system_is_neutral", abs(charge - spec_charge["expected_net_charge"]) < 1e-4,
              f"net charge {charge:+.2e} e")

    # --- energetics, recomputed from system.xml at the submitted states -------
    spec_energy = next(c for c in task["scoring"]["deterministic_checks"]
                       if c["check_id"] == "potential_energy_is_physical")
    built = {"ok": False, "reason": load_error or ""}
    relaxed = {"ok": False}
    minimized = _minimized_state(job_dir)
    if system is None:
        check("potential_energy_is_physical", False, load_error)
        check("minimization_reduced_the_energy", False, load_error)
    else:
        built = en.single_point(system, (topo / "artifacts" / "system.state.xml").read_text())
        passed, detail = en.is_physical(
            built, ceiling=spec_energy["maximum_abs_energy_per_particle_kj_mol"])
        check("potential_energy_is_physical", passed, detail)

        if minimized is None:
            check("minimization_reduced_the_energy", False,
                  "no completed min node: the submission carries no minimised state to check")
        else:
            relaxed = en.single_point(system, minimized.read_text())
            if not (built["ok"] and relaxed["ok"]):
                check("minimization_reduced_the_energy", False,
                      relaxed.get("reason") or built.get("reason"))
            else:
                check("minimization_reduced_the_energy",
                      relaxed["energy_is_finite"]
                      and relaxed["energy_kj_mol"] < built["energy_kj_mol"],
                      f"{built['energy_kj_mol']:.0f} -> {relaxed['energy_kj_mol']:.0f} kJ/mol, "
                      f"max force {built['max_force_kj_mol_nm']:.0f} -> "
                      f"{relaxed['max_force_kj_mol_nm']:.0f} kJ/mol/nm")

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

    # One entry per atom of reference.pdb, which is the whole deposited system and
    # not just its protein: MDDB's PROTATS excludes structural metals, so a task
    # with a zinc reshapes 4897 atoms into 4896 and dies. Take the count from the
    # file the frames actually accompany.
    frames = np.fromfile(bundle / "reference_frames.f32", dtype="<f4")
    frames = frames.reshape(-1, len(reference_atoms), 3).astype(np.float64)[:, indices, :]
    _, reference_subspace = st.essential_subspace(frames, reference_xyz)

    traj = md.load(str(traj_path), top=str(topology_pdb))

    claimed = float(prod_meta.get("simulation_time_ns", 0.0)) * 1000.0
    interval = ex.dcd_frame_interval_ps(traj_path)
    clock = ex.elapsed_time_ps(traj, dt_ps=interval)
    spec_time = next(c for c in task["scoring"]["deterministic_checks"]
                     if c["check_id"] == "elapsed_simulated_time_is_physical")
    if interval is None:
        check("elapsed_simulated_time_is_physical", False,
              f"no frame interval in the DCD header of {traj_path.name}; "
              "the clock would count frames, not picoseconds")
    elif not clock["measurable"]:
        check("elapsed_simulated_time_is_physical", False,
              f"not measurable: {clock['reason']}")
    else:
        ratio = clock["elapsed_ps"] / claimed if claimed else 0.0
        check("elapsed_simulated_time_is_physical",
              ratio >= spec_time["minimum_measured_fraction_of_claim"],
              f"solvent clock says {clock['elapsed_ps']:.0f} ps against a claimed "
              f"{claimed:.0f} ps (ratio {ratio:.2f}), "
              f"D={clock['diffusion_1e5_cm2_s']:.2f}e-5 cm2/s, "
              f"frame interval {interval:.3f} ps from the DCD header")
    check("contract_atoms_resolvable", not missing,
          f"{len(own_indices)}/{len(keys)} contract atoms matched by (residue, atom name)"
          + (f"; missing {missing[:4]}" if missing else ""))

    # Two subspaces can only be compared when the same atoms span them.  A
    # submission missing a contract atom used to reach `kabsch` with a 933x3
    # frame against a 936x3 target and die on the matmul; the check that was
    # meant to prevent that is a precondition, and a precondition that only
    # reports is not a guard.  Missing atoms are the submission's own doing --
    # D01 built 311 residues where the reference has 312 -- so the check fails
    # rather than being skipped.
    if missing:
        test = None
        check("subspace_beyond_structure_only_model", False,
              f"not evaluable: {len(missing)} of {len(keys)} reference contract "
              "atoms are absent from the submitted topology, so no common set of "
              "atoms spans both subspaces")
    else:
        own = traj.xyz[:, own_indices, :] * 10.0
        _, own_subspace = st.essential_subspace(own, reference_xyz)
        test = st.test_beyond_structure(own_subspace, reference_subspace, reference_xyz)
        check("subspace_beyond_structure_only_model", test["h0_rejected"],
              f"RMSIP={test['rmsip']:.3f} vs structure-only null "
              f"{test['null_mean']:.3f}+/-{test['null_sd']:.3f} (max {test['null_max']:.3f}), "
              f"z={test['z_score']:.2f}, p<={test['p_value_upper_bound']:.2f}")

    # Radius of gyration is recorded and not scored. It is a property of the
    # prepared structure rather than of the simulation: measured 2026-08-21 it
    # is 1.1616 / 1.1031 / 0.8549 nm as built against 1.1784 / 1.1224 / 0.8223
    # averaged over production, and the within-trajectory SD is 0.007-0.012 nm
    # against bands that were 0.2-0.4 nm wide.
    rg = md.compute_rg(traj.atom_slice(traj.topology.select("protein")))

    by_category = {}
    for row in results:
        bucket = by_category.setdefault(row["category"], {"passed": 0, "total": 0,
                                                          "weight": 0.0, "earned": 0.0})
        bucket["total"] += 1
        bucket["passed"] += int(row["passed"])
        bucket["weight"] += row["weight"]
        bucket["earned"] += row["weight"] * int(row["passed"])

    # One score per category, each normalised on its own. A zero weight excludes
    # a check from every score, which is how `precondition` stays reported and
    # ungraded: it asks whether the reference's contract atoms land on the
    # submitted topology, and that measures the scorer, not the agent.
    scores = {name: (bucket["earned"] / bucket["weight"] if bucket["weight"] else None)
              for name, bucket in by_category.items()}
    scored = [r for r in results if r["weight"]]
    return {"task_id": task["task_id"], "checks": results, "by_category": by_category,
            "scores": scores,
            "passed": sum(1 for r in scored if r["passed"]), "total": len(scored),
            "diagnostics": {"rmsip": test["rmsip"] if test else None,
                            "z_score": test["z_score"] if test else None,
                            "canonical_correlations":
                                (test["canonical_correlations"] if test else None),
                            "rg_mean_nm": float(rg.mean()), "n_frames": int(traj.n_frames),
                            "built_energy_per_atom_kj_mol":
                                built.get("energy_per_particle_kj_mol"),
                            "minimized_energy_per_atom_kj_mol":
                                (relaxed.get("energy_per_particle_kj_mol")
                                 if minimized is not None else None),
                            "minimized_max_force_kj_mol_nm":
                                (relaxed.get("max_force_kj_mol_nm")
                                 if minimized is not None else None)}}


