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
from mddatabench import dynamics as dy
from mddatabench import topology as tp
from mddatabench import energetics as en
from mddatabench import execution as ex


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
    def _order(name):
        """prod_9 before prod_10: node ids are not zero-padded forever."""
        digits = "".join(character for character in name if character.isdigit())
        return (int(digits) if digits else 0, name)

    completed_prod = sorted((name for name, (_, data) in nodes.items()
                             if data.get("node_type") == "prod"
                             and data.get("status") == "completed"), key=_order)
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


def _prepared_structure(prep: pathlib.Path) -> pathlib.Path:
    """The prepared structure a prep node declares, whatever produced it.

    Reading it out of `artifacts/merge/` assumed `prepare_complex` wrote it, and
    a prep node need not be that tool: a mutation node is also `node_type=prep`
    and registers its output as `merged_pdb` pointing at `artifacts/mutated.pdb`.
    Globbing the merge directory raised StopIteration on the first submission
    that reverted a crystallographic mutation.  The node says where its
    structure is; ask it.
    """
    declared = json.loads((prep / "node.json").read_text()).get("artifacts") or {}
    relative = declared.get("merged_pdb")
    if relative:
        candidate = prep / relative
        if candidate.is_file():
            return candidate
        # A node that names a structure it does not have is not a node to guess
        # for. Falling back here would score whatever else is in the directory
        # while the report says the declared artifact was used -- a mutation
        # node whose output went missing would be scored on its unmutated
        # parent, which is worse than stopping.
        raise SystemExit(
            f"{prep.name} declares merged_pdb={relative} and the file is not "
            "there; the node's artifacts are inconsistent")
    for pattern in ("artifacts/merge/*.pdb", "artifacts/*.pdb"):
        found = sorted(prep.glob(pattern))
        if len(found) > 1:
            raise SystemExit(
                f"{prep.name} declares no merged_pdb and holds {len(found)} "
                f"candidates ({', '.join(path.name for path in found)}); "
                "which one was prepared cannot be guessed")
        if found:
            return found[0]
    raise SystemExit(f"no prepared structure under {prep}")


def _check_topology_chemistry(check, submitted, submitted_bonds, reference,
                              spec_valid):
    """Faults that are wrong on their own terms, then the disulfide comparison.

    The two are separate on purpose and one fault can cost both.  A bond between
    two ligands of one metal is wrong whatever the reference contains, and a
    disulfide set that differs from the reference is wrong whether or not a metal
    is nearby; they coincide on D01 and do not in general.
    """
    duplicated = tp.duplicate_atom_names(submitted)
    valence = tp.valence_problems(submitted)
    bridged = tp.metal_bridging_bonds(
        submitted, cutoff=spec_valid["metal_ligand_angstrom"])
    faults = []
    if duplicated:
        faults.append(f"{len(duplicated)} residue(s) with a repeated atom name: "
                      f"{duplicated[:3]}")
    if valence:
        faults.append(f"{len(valence)} atom(s) over their valence: {valence[:3]}")
    if bridged:
        faults.append(f"{len(bridged)} covalent bond(s) between ligands of one metal: "
                      f"{bridged}")
    check("topology_is_chemically_valid", not faults,
          "; ".join(faults) if faults else
          f"no repeated atom names, no valence violations, and no covalent bond "
          f"between two ligands of the same metal across {len(submitted.atoms)} atoms")

    expected, reference_count, reference_dropped = tp.sulfur_bond_positions(reference)
    observed, submitted_count, submitted_dropped = tp.sulfur_bond_positions(
        submitted, submitted_bonds)
    detail = (f"reference topology has {len(expected)} S-S bond(s) "
              f"{tp.describe_position_pairs(expected)}; the submitted System has "
              f"{len(observed)} {tp.describe_position_pairs(observed)}")
    if expected != observed:
        detail += "; sets differ"
        # Positions are re-derived on each side, so they only line up while the
        # two contain the same polymer residues. Say which it is rather than
        # blaming the bonds for a residue-count difference.
        if reference_count != submitted_count:
            detail += (f" -- but the polymer residue counts differ "
                       f"({submitted_count} vs {reference_count}), so the "
                       "positions are not aligned and the comparison is unsafe")
    for label, dropped in (("reference", reference_dropped),
                           ("submission", submitted_dropped)):
        if dropped:
            detail += (f"; {len(dropped)} {label} S-S bond(s) touch a residue "
                       f"outside the polymer and were not compared: {dropped[:3]}")
    check("disulfide_bonds_match_reference", expected == observed, detail)


# What the scorer needs the submission's DAG to have produced.  A run that
# errored out before these exist is not a low-scoring submission, it is one that
# cannot be measured at all.
REQUIRED_STAGES = ("prep", "topo", "prod")


def _report(task, results, diagnostics=None):
    """Per-category scores from a list of check results."""
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
            "diagnostics": diagnostics or {}}


def _unrunnable(task, reason):
    """Every graded check failed, because the submission produced nothing to grade.

    A pipeline that errors out used to raise straight out of the scorer, which
    reports no score at all rather than a zero -- the same fault
    ``topology_loads_and_is_parameterized`` had until 2026-08-21.  A prep stage
    that failed leaves no structure to compare and no system to simulate, so
    both axes are zero and say why, instead of the run being absent from the
    results.
    """
    results = [{"check_id": c["check_id"], "category": c.get("category", "prep"),
                "weight": float(c.get("weight", 1.0)), "passed": False,
                "detail": reason}
               for c in task["scoring"]["deterministic_checks"]]
    report = _report(task, results, {"unrunnable": reason})
    report["unrunnable"] = reason
    return report


def _resolve_stages(job_dir):
    """The prep, topo and prod nodes, or the reason there is no scoring to do."""
    if not (job_dir / "nodes").is_dir():
        return None, f"no nodes directory under {job_dir}"
    nodes = {}
    for stage in REQUIRED_STAGES:
        try:
            nodes[stage] = find_node(job_dir, stage)
        except SystemExit as exc:
            return None, str(exc)
        except OSError as exc:
            return None, f"the {stage} node could not be read: {exc}"
    required = {"topo": ("system.topology.pdb", "system.system.xml",
                         "amber_metadata.json")}
    for stage, names in required.items():
        for name in names:
            if not (nodes[stage] / "artifacts" / name).exists():
                return None, f"the {stage} node produced no {name}"
    if not list((nodes["prod"] / "artifacts").glob("*.dcd")):
        return None, "the prod node produced no trajectory"
    return nodes, None


def score(job_dir: pathlib.Path, bundle: pathlib.Path, task: dict) -> dict:
    nodes, unrunnable = _resolve_stages(job_dir)
    if unrunnable:
        return _unrunnable(task, unrunnable)
    prep, topo, prod = (nodes[t] for t in REQUIRED_STAGES)
    amber = json.loads((topo / "artifacts" / "amber_metadata.json").read_text())
    prod_meta = json.loads((prod / "node.json").read_text()).get("metadata", {})
    signature = prod_meta.get("system_signature", {})
    # ``reference["reference_system"]`` is provenance only: every composition
    # expectation is recomputed from the fetched bundle at scoring time, so
    # nothing here reads the curated copy.
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
    prepared = _prepared_structure(prep)
    topology_pdb = topo / "artifacts" / "system.topology.pdb"
    reference_monomers = cp.split_monomers(cp.read_residues(bundle / "reference.pdb"))
    submitted_monomers = cp.split_monomers(cp.read_residues(prepared))

    # Both topologies, read rather than inferred. The reference ships its own
    # topology.prmtop and the submission ships the System that exerts force.
    reference_topology = tp.load_reference(tp.find_reference_topology(bundle),
                                           bundle / "reference.pdb")
    submitted_topology, submitted_bonds, topology_error = tp.load_submission(
        topo / "artifacts" / "system.system.xml", topology_pdb)

    pairs, mismatches = cp.match_monomers(reference_monomers, submitted_monomers)
    check("monomer_count_matches_reference", not mismatches,
          f"{len(reference_monomers)} reference monomer(s), {len(submitted_monomers)} submitted"
          + ("; " + "; ".join(mismatches) if mismatches else "; all sequences pair up"))

    # Positions whose protonation is a metal-site modelling decision. Taken from
    # the built structures, which still carry the deposit's coordinates, and
    # unioned across the two sides: the reference has already lost ligands by the
    # time its structure file is written, and a set derived from the trajectory
    # would exempt residues that were never ligands -- 6WRH's zinc reaches
    # GLN191:OE1 at 1.75 A once its thiolates leave.
    submitted_metals = cp.read_metals(prepared)
    reference_metals = cp.read_metals(bundle / "reference.pdb")
    submitted_ligands = cp.metal_ligand_positions(submitted_monomers, submitted_metals)
    reference_ligands = cp.metal_ligand_positions(reference_monomers, reference_metals)
    # A catalytic cysteine-histidine pair is exempted for the same reason the
    # metal ligands are: there is no settled target. The literature disagrees
    # with itself about whether such a pair is a thiolate-imidazolium ion pair
    # or neutral, and the disagreement is between experiments on the same
    # enzyme, so a benchmark that scores one answer scores a coin flip.
    submitted_dyads = cp.catalytic_dyad_positions(submitted_monomers, submitted_metals)
    reference_dyads = cp.catalytic_dyad_positions(reference_monomers, reference_metals)

    findings = {"sequence": [], "atom_counts": [], "elements": []}
    exempt_total = 0
    for reference_monomer, submitted_monomer in pairs:
        exempt = (submitted_ligands.get(id(submitted_monomer), set())
                  | reference_ligands.get(id(reference_monomer), set())
                  | submitted_dyads.get(id(submitted_monomer), set())
                  | reference_dyads.get(id(reference_monomer), set()))
        exempt_total += len(exempt)
        comparison = cp.compare_monomer(reference_monomer, submitted_monomer,
                                        exempt=exempt)
        for key, value in comparison.items():
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
          + (f", {exempt_total} exempt as metal ligands or a catalytic dyad"
             if exempt_total else "")
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

    # --- chemistry that is wrong on its own terms ------------------------------
    spec_valid = spec["topology_is_chemically_valid"]
    if topology_error:
        check("topology_is_chemically_valid", False, topology_error)
        check("disulfide_bonds_match_reference", False, topology_error)
    else:
        _check_topology_chemistry(check, submitted_topology, submitted_bonds,
                                  reference_topology, spec_valid)

    # --- the force field, from the System itself ------------------------------
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
    traj = md.load(str(traj_path), top=str(topo / "artifacts" / "system.topology.pdb"))

    # --- the clock: reference-independent evidence that time passed -----------
    claimed = float(prod_meta.get("simulation_time_ns", 0.0)) * 1000.0
    interval = ex.dcd_frame_interval_ps(traj_path)
    clock = ex.elapsed_time_ps(traj, dt_ps=interval)
    spec_time = spec["elapsed_simulated_time_is_physical"]
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

    # --- what a nanosecond can honestly be asked to reproduce -----------------
    reference_atoms = pdb_atoms(bundle / "reference.pdb")
    indices = json.loads((bundle / "pca_atom_indices.json").read_text())["atom_indices"]
    keys = [(reference_atoms[i][1], reference_atoms[i][2]) for i in indices]

    topology_pdb = topo / "artifacts" / "system.topology.pdb"
    lookup = {}
    for n, row in enumerate(pdb_atoms(topology_pdb)):
        lookup.setdefault((row[1], row[2]), n)
    missing = [k for k in keys if k not in lookup]
    own_indices = np.array([lookup[k] for k in keys if k in lookup])
    check("contract_atoms_resolvable", not missing,
          f"{len(own_indices)}/{len(keys)} contract atoms matched by (residue, atom name)"
          + (f"; missing {missing[:4]}" if missing else ""))

    # Thinned to the reference windows' 10 ps so both sides carry the same number
    # of samples; measured, the statistics move by less than 0.02 across strides
    # of 1, 10 and 20 ps, but matching them costs nothing.
    stride = max(1, int(round(10.0 / (interval or 10.0))))
    own_xyz = traj.xyz[::stride][:, own_indices, :] * 10.0

    calibration = task["reference"].get("md_calibration") or {}
    reference_profile = np.array(json.loads(
        (bundle / "reference_fluctuation.json").read_text())["y"]["rmsf"]["data"]) * 10.0

    # A range over a hundred windows is not the range of the population, and the
    # difference is measurable: held-out reference windows fall outside the range
    # of the rest 7 to 16 per cent of the time. Widening it by twice the window
    # spread takes that to zero on all three tasks, and the negative controls are
    # separated by so much more than that -- they still all fail at three times
    # the spread -- that the room costs nothing.
    slack = float(calibration.get("slack_window_sd", 0.0))
    spread = calibration.get("observed_window_sd") or {}

    def widened(band, key):
        if not band:
            return None
        margin = slack * float(spread.get(key, 0.0))
        return [band[0] - margin, band[1] + margin]

    def banded(check_id, value, band, key, unit=""):
        """Inside the range the reference's own windows span, plus the slack."""
        band = widened(band, key)
        if value is None or not band:
            check(check_id, False, "not measurable: no value or no calibrated band")
            return
        low, high = band
        check(check_id, low <= value <= high,
              f"{value:.4f}{unit} against the reference's own 1 ns windows "
              f"[{low:.4f}, {high:.4f}]{unit} "
              f"(n={calibration.get('windows')}, widened by {slack} window SD)")

    if missing:
        for check_id in ("fluctuation_profile_matches_reference",
                         "fluctuation_magnitude_is_physical",
                         "radius_of_gyration_matches_reference"):
            check(check_id, False,
                  f"not evaluable: {len(missing)} of {len(keys)} reference contract "
                  "atoms are absent from the submitted topology")
        agreement = None
    else:
        agreement = dy.profile_agreement(dy.atom_fluctuations(own_xyz),
                                         reference_profile[indices])
        # One-sided: agreement above the floor is agreement, and a profile that
        # matched better than any reference window would be no complaint.
        floor = (widened(calibration.get("rank_correlation"),
                         "rank_correlation") or [None])[0]
        check("fluctuation_profile_matches_reference",
              agreement is not None and floor is not None and agreement >= floor,
              f"rank correlation {agreement:.4f} against a floor of {floor:.4f} taken "
              f"from the reference's own 1 ns windows "
              f"(n={calibration.get('windows')}, widened by {slack} window SD)"
              if agreement is not None and floor is not None else
              "not measurable: the profiles could not be compared")
        banded("fluctuation_magnitude_is_physical", dy.total_fluctuation(own_xyz),
               calibration.get("total_fluctuation_angstrom"),
               "total_fluctuation_angstrom", " A")
        banded("radius_of_gyration_matches_reference",
               float(dy.radius_of_gyration(own_xyz).mean()),
               calibration.get("radius_of_gyration_angstrom"),
               "radius_of_gyration_angstrom", " A")

    # --- what the run reported about itself, measured rather than declared ----
    log = dy.energy_series(next(iter((prod / "artifacts").glob("energy.dat")), None)) \
        if any((prod / "artifacts").glob("energy.dat")) else {}
    spec_temperature = spec["measured_temperature_matches_reference"]
    wanted = float(task["reference"]["reference_conditions"]["TEMP"])
    measured = log.get("Temperature (K)")
    if measured is None or not len(measured):
        check("measured_temperature_matches_reference", False,
              "no state log to read a temperature from")
    else:
        mean = float(measured.mean())
        check("measured_temperature_matches_reference",
              abs(mean - wanted) <= spec_temperature["tolerance_kelvin"],
              f"mean {mean:.3f} K against {wanted:.0f} K asked for, tolerance "
              f"{spec_temperature['tolerance_kelvin']:.0f} K "
              f"(spread {measured.std():.3f} K, not graded)")

    spec_box = spec["solvent_box_is_physical"]
    density = log.get("Density (g/mL)")
    volume = log.get("Box Volume (nm^3)")
    low, high = spec_box["density_range_g_per_ml"]
    if density is None or volume is None or not len(density):
        check("solvent_box_is_physical", False,
              "no state log to read a density or a box volume from")
    else:
        mean = float(density.mean())
        moved = float(volume.std()) > 0.0
        check("solvent_box_is_physical", low <= mean <= high and moved,
              f"mean density {mean:.4f} g/mL in [{low}, {high}], box volume "
              f"{volume.mean():.1f} nm3 with spread {volume.std():.3f} "
              f"({'a barostat moved it' if moved else 'it never moved'})")

    # --- metal sites: reported, never scored ----------------------------------
    spec_metal = spec["metal_site_coordination_retained"]
    shells = ({} if topology_error else
              tp.coordination_shell(submitted_topology,
                                    cutoff=spec_metal["metal_ligand_angstrom"]))
    metal_report = [] if not topology_error else [topology_error]
    for metal_atom, (label, donors) in sorted(shells.items()):
        if not donors:
            metal_report.append(f"{label}: no side-chain donor within "
                                f"{spec_metal['metal_ligand_angstrom']} A as built")
            continue
        indices = np.array([[metal_atom, atom] for atom, _, _ in donors])
        distances = md.compute_distances(traj, indices) * 10.0
        occupancy = (distances <= spec_metal["metal_ligand_angstrom"]).mean(axis=0)
        retained = int((occupancy >= spec_metal["occupancy_fraction"]).sum())
        detail = ", ".join(
            f"{name} {built} A built -> {column.mean():.2f}+/-{column.std():.2f} A, "
            f"{share * 100:.0f}% bound"
            for (_, name, built), column, share
            in zip(donors, distances.T, occupancy))
        metal_report.append(f"{label}: {retained}/{len(donors)} retained; {detail}")
    check("metal_site_coordination_retained", True,
          " | ".join(metal_report) if metal_report
          else "no metal ion in the submitted topology")

    return _report(task, results, {
        "fluctuation_rank_correlation": agreement,
        "n_frames": int(traj.n_frames),
        "built_energy_per_atom_kj_mol": built.get("energy_per_particle_kj_mol"),
        "minimized_energy_per_atom_kj_mol":
            (relaxed.get("energy_per_particle_kj_mol") if minimized is not None else None),
        "minimized_max_force_kj_mol_nm":
            (relaxed.get("max_force_kj_mol_nm") if minimized is not None else None)})


