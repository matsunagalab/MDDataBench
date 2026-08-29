"""Score one MDDataBench submission against its task contract.

Everything is recomputed from the submitted artifacts.  Values the agent
reports are never used.  The artifact paths this reads are recorded in the
task contract under ``scorer_field_map``; they were established by solving
the tasks with MDClaw, because guessing them produced false failures:

- the water model lives at ``parameters.water_model`` in the topo node's
  ``amber_metadata.json``, not at its top level
- the barostat is added at run time, so the topo node's ``system.xml`` has
  none; the ensemble must be read from the prod node's metadata
- contract atoms are placed through an exact residue correspondence; residue
  numbers, chain IDs and raw atom indices do not line up between the two sides
"""

from __future__ import annotations

from mddatabench import _threads  # noqa: F401  must precede numpy

import hashlib
import itertools
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


# A too-small RMSF magnitude can still reveal a frozen or over-restrained run,
# but it is less harmful than excessive motion and varies noticeably between
# independent short trajectories.  Give only that lower edge one extra SD of
# room when the task uses the standard four-SD calibration slack.
FLUCTUATION_LOWER_SLACK_MULTIPLIER = 1.25

# One task-agnostic between-replica allowance, measured from every finite
# multi-replica manifest in the 100-task cast (39 projects, 116 replicas).
# See docs/memo.md for the frozen manifest list, formula and command.
GLOBAL_REPLICA_FLUCTUATION_FACTOR = 1.0936030954161982


#: Hard ceiling on the fluctuation-shape floor, whatever the calibration says.
#:
#: The band is measured from windows of one continuous reference trajectory, so
#: it captures within-trajectory spread and is then applied to an independently
#: run submission, whose spread is larger. Measured 2026-08-25 with
#: ``run_benchmark_negative_controls``, the positive control - the submission
#: that must pass - failed on three tasks at the calibrated floor:
#:
#:     047_nucleic_1c7u  0.5202 against floor 0.8355   (needs 15.2 window SD)
#:     049_nucleic_1iv6  0.8613 against floor 0.8731   (needs  4.6)
#:     091_soluble_1ag4  0.6869 against floor 0.6964   (needs  4.2)
#:
#: Nothing is lost by capping. Across those runs the corruptions only this gate
#: can catch - shuffled atoms, a frozen frame, isotropic noise, a duplicated
#: minimum - never scored above 0.0429, while every legitimate run scored at
#: least 0.5202. The gate was never the one catching over-restraint, expansion
#: or truncation: an elastic-network ensemble scores 0.77-0.83 here and is
#: caught by the RMSF magnitude gate (0.16-0.26 against bands starting at
#: 0.29), and a 100 ps truncation is caught by the solvent clock.
RANK_CORRELATION_FLOOR_CAP = 0.30

#: Absolute tolerance added to each side of the radius-of-gyration band.
#:
#: Same cause as the floor cap above: the band comes from windows of one
#: continuous reference trajectory and is applied to an independent run.
#: Measured 2026-08-25, two positive controls sat just outside the upper bound
#: while every check that matters was comfortably inside:
#:
#:     047_nucleic_1c7u  21.2004 against a ceiling of 21.1945  (+0.0059 A)
#:     049_nucleic_1iv6  15.4450 against a ceiling of 15.4329  (+0.0121 A)
#:
#: 0.25 A covers those by twenty to forty times over and still leaves the gate
#: decisive. The baseline this gate exists to catch, a compressed structure,
#: sat 1.6 to 2.7 A *below* the band on the same four tasks - two orders of
#: magnitude further out than a legitimate run overshoots, and on the opposite
#: side. Expansion and over-restraint are caught by the RMSF magnitude gate,
#: not by this one.
RADIUS_OF_GYRATION_TOLERANCE_ANGSTROM = 0.25


def widened_calibration_band(band, key, slack, spread):
    """Widen a measured window band, asymmetrically for RMSF magnitude."""
    if not band:
        return None
    margin = float(slack) * float(spread)
    lower_multiplier = (FLUCTUATION_LOWER_SLACK_MULTIPLIER
                        if key == "total_fluctuation_angstrom" else 1.0)
    lower = band[0] - lower_multiplier * margin
    upper = band[1] + margin
    if key == "rank_correlation":
        lower = min(lower, RANK_CORRELATION_FLOOR_CAP)
    if key == "radius_of_gyration_angstrom":
        lower -= RADIUS_OF_GYRATION_TOLERANCE_ANGSTROM
        upper += RADIUS_OF_GYRATION_TOLERANCE_ANGSTROM
    if key == "total_fluctuation_angstrom":
        lower /= GLOBAL_REPLICA_FLUCTUATION_FACTOR
        upper *= GLOBAL_REPLICA_FLUCTUATION_FACTOR
    return [lower, upper]


def last_complete_window_slice(n_frames, interval_ps, window_ns):
    """The trailing complete calibration-length block of a submission.

    Reference calibration counts frames with ``round(window / interval)``;
    using the same rule gives both estimators the same number of samples. The
    full trajectory remains available to the independent duration check.
    """
    if interval_ps is None or not np.isfinite(interval_ps) or interval_ps <= 0:
        return None, "the DCD frame interval is unavailable"
    if window_ns is None or not np.isfinite(window_ns) or window_ns <= 0:
        return None, "md_calibration.window_ns is unavailable"
    frames = int(round(float(window_ns) * 1000.0 / float(interval_ps)))
    if frames < 2:
        return None, (f"a {float(window_ns):g} ns block at {float(interval_ps):g} ps "
                      "per frame contains fewer than two frames")
    if int(n_frames) < frames:
        return None, (f"trajectory has {int(n_frames)} frames, fewer than the {frames} "
                      f"needed for one complete {float(window_ns):g} ns block")
    start = int(n_frames) - frames
    return slice(start, int(n_frames)), (
        f"last complete {float(window_ns):g} ns block "
        f"(frames {start + 1}--{int(n_frames)} of {int(n_frames)})")


def pdb_atoms(path):
    """(chain, residue number, atom name) per atom record, in file order.

    Only what ``contract_correspondence`` addresses an atom by.  The coordinate,
    element and residue name this used to carry as well were read by nothing and
    cost 0.30 s per call on 1AHW's 381954 rows.
    """
    return [(line[21], line[22:27].strip(), line[12:16].strip())
            for line in open(path) if line.startswith(("ATOM", "HETATM"))]


def _describe_backbone_link(link):
    """One retained topology link in a compact, human-readable form."""
    labels = []
    for name, number, chain, atom in zip(
            link["residue_names"], link["residue_numbers"],
            link["chains"], link["atom_names"]):
        labels.append(f"{name}{number}{('/' + chain) if chain else ''}:{atom}")
    return f"{link['kind']} {labels[0]}--{labels[1]}"


def _sha256(path):
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


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


def _load_system(path: pathlib.Path, system=None):
    """Validate a submitted OpenMM System. Returns (system, error_message).

    ``system`` is the object ``tp.load_submission`` deserialised from this same
    file; validating that instead of re-reading saves the second parse of up to
    84 MB -- 2.42 s of a01-1ahw's 73.8 s, 7.2 s over the five solved jobs.  The
    file is still parsed here when ``load_submission`` returned nothing, so a
    valid System behind an unreadable topology PDB is graded either way and the
    force-field axis stays independent of the topology axis.
    """
    if system is None:
        try:
            system = mm.XmlSerializer.deserialize(path.read_text())
        except Exception as exc:                                    # noqa: BLE001
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


def _polymer_monomers(monomers):
    """Polymer components, in the order used by topology endpoint labels."""
    return [monomer for monomer in monomers if monomer and all(
        residue.name.strip().upper() in tp.POLYMER_RESIDUES for residue in monomer)]


def _candidate_monomer_correspondences(reference_monomers, submitted_monomers):
    """Enumerate sequence-preserving copy pairings, deterministically."""
    reference_groups, submitted_groups = {}, {}
    for index, monomer in enumerate(reference_monomers):
        reference_groups.setdefault(cp.canonical_sequence(monomer), []).append(index)
    for index, monomer in enumerate(submitted_monomers):
        submitted_groups.setdefault(cp.canonical_sequence(monomer), []).append(index)
    if (set(reference_groups) != set(submitted_groups)
            or any(len(reference_groups[key]) != len(submitted_groups[key])
                   for key in reference_groups)):
        return

    groups = sorted(reference_groups, key=repr)
    options = [
        [dict(zip(reference_groups[key], permutation))
         for permutation in itertools.permutations(submitted_groups[key])]
        for key in groups
    ]
    for choices in itertools.product(*options):
        correspondence = {}
        for choice in choices:
            correspondence.update(choice)
        yield correspondence


def _best_disulfide_correspondence(expected, observed, reference_monomers,
                                    submitted_monomers):
    """Compare a complete S-S set under every interchangeable-copy pairing."""
    best = None
    for correspondence in _candidate_monomer_correspondences(
            reference_monomers, submitted_monomers):
        translated = {
            frozenset((correspondence[monomer], position)
                      for monomer, position in edge)
            for edge in expected
        }
        missing, unexpected = translated - observed, observed - translated
        tie_break = tuple(correspondence[index]
                          for index in range(len(reference_monomers)))
        candidate = (len(missing) + len(unexpected), tie_break,
                     translated, missing, unexpected)
        if best is None or candidate[:2] < best[:2]:
            best = candidate
    return best


def _check_topology_chemistry(check, submitted, submitted_bonds, reference,
                              spec_valid, reference_monomers,
                              submitted_monomers):
    """Faults that are wrong on their own terms, then the disulfide comparison.

    The two are separate on purpose and one fault can cost both.  A bond between
    two ligands of one metal is wrong whatever the reference contains, and a
    disulfide set that differs from the reference is wrong whether or not a metal
    is nearby; they coincide on D01 and do not in general.
    """
    duplicated = tp.duplicate_atom_names(submitted)
    # Every bond question about a submission is asked of the System, never of
    # the topology PDB's CONECT: a PDB serial is five columns and OpenMM's
    # writer wraps them at 493215, so a large system's CONECT records address
    # the wrong atoms.  The disulfide comparison below already reads
    # submitted_bonds; these two used to read structure.bonds and so judged the
    # chemistry from the one basis this module documents as metadata.
    valence = tp.valence_problems(submitted, submitted_bonds)
    bridged = tp.metal_bridging_bonds(
        submitted, cutoff=spec_valid["metal_ligand_angstrom"],
        bonds=submitted_bonds)
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

    expected, reference_sizes, reference_dropped = \
        tp.sulfur_bond_monomer_positions(reference)
    observed, submitted_sizes, submitted_dropped = \
        tp.sulfur_bond_monomer_positions(submitted, submitted_bonds)
    reference_polymer = _polymer_monomers(reference_monomers)
    submitted_polymer = _polymer_monomers(submitted_monomers)
    aligned = (reference_sizes == [len(monomer) for monomer in reference_polymer]
               and submitted_sizes == [len(monomer) for monomer in submitted_polymer])
    best = (_best_disulfide_correspondence(
        expected, observed, reference_polymer, submitted_polymer) if aligned else None)
    matches = best is not None and not best[3] and not best[4]
    detail = (f"reference topology has {len(expected)} S-S bond(s) "
              f"{tp.describe_monomer_position_pairs(expected)}; the submitted System has "
              f"{len(observed)} {tp.describe_monomer_position_pairs(observed)}")
    if not aligned:
        detail += ("; sets are not comparable because topology component sizes "
                   f"{reference_sizes} / {submitted_sizes} do not match the "
                   "coordinate component partition")
    elif best is None:
        detail += "; sets are not comparable because no complete monomer correspondence exists"
    elif not matches:
        detail += "; sets differ after the closest whole-set monomer pairing"
        if best[3]:
            detail += f"; missing {tp.describe_monomer_position_pairs(best[3])}"
        if best[4]:
            detail += f"; unexpected {tp.describe_monomer_position_pairs(best[4])}"
    for label, dropped in (("reference", reference_dropped),
                           ("submission", submitted_dropped)):
        if dropped:
            detail += (f"; {len(dropped)} {label} S-S bond(s) touch a residue "
                       f"outside the polymer and were not compared: {dropped[:3]}")
    check("disulfide_bonds_match_reference", matches, detail)


# What the scorer needs the submission's DAG to have produced.  A run that
# errored out before these exist is not a low-scoring submission, it is one that
# cannot be measured at all.
REQUIRED_STAGES = ("prep", "topo", "min", "prod")


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
                         "amber_metadata.json"),
                "min": ("minimized_structure.pdb",)}
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
    prep, topo, minimized, prod = (nodes[t] for t in REQUIRED_STAGES)
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
    # Read to fail early and by name when a prep node declares no structure at
    # all; nothing is compared against it any more, because every comparison
    # wants the system as it was built rather than as it was handed in.
    _prepared_structure(prep)
    topology_pdb = topo / "artifacts" / "system.topology.pdb"
    # The minimised structure supplies coordinates and residue labels, but not
    # connectivity.  Close fragment ends can sit at a peptide-bond distance
    # without a force term, and a declared link can begin 9.63 A apart (5ZK8)
    # before minimisation.  Split the reference by its deposited topology and
    # the submission by the force-bearing bonds in its System instead.
    minimized_structure = minimized / "artifacts" / "minimized_structure.pdb"
    reference_residues = cp.read_residues(bundle / "reference.pdb")
    submitted_residues = cp.read_residues(minimized_structure)

    # Both topologies, read rather than inferred. The reference ships its own
    # topology.prmtop and the submission ships the System that exerts force.
    reference_topology = tp.load_reference(tp.find_reference_topology(bundle),
                                           bundle / "reference.pdb")
    submitted_topology, submitted_bonds, topology_error, submitted_system = \
        tp.load_submission(topo / "artifacts" / "system.system.xml", topology_pdb)
    reference_backbone_links = tp.backbone_links(reference_topology)
    try:
        reference_monomers, reference_mapped_links = \
            cp.split_monomers_by_backbone_links(
                reference_residues, reference_topology.residues,
                reference_backbone_links, tp.POLYMER_RESIDUES)
    except ValueError as exc:
        raise SystemExit(f"reference topology cannot be mapped to reference.pdb: {exc}") \
            from exc

    submitted_backbone_links = []
    submitted_mapped_links = {}
    partition_error = topology_error
    if topology_error:
        submitted_monomers = [[residue] for residue in submitted_residues]
    else:
        submitted_backbone_links = tp.backbone_links(
            submitted_topology, submitted_bonds)
        try:
            submitted_monomers, submitted_mapped_links = \
                cp.split_monomers_by_backbone_links(
                    submitted_residues, submitted_topology.residues,
                    submitted_backbone_links, tp.POLYMER_RESIDUES)
        except ValueError as exc:
            partition_error = f"submitted topology cannot be mapped to the minimum: {exc}"
            submitted_monomers = [[residue] for residue in submitted_residues]

    # --- the bilayer, if there is one -----------------------------------------
    # The species is graded and the count is not, beyond "there is a membrane at
    # all": which lipid to use is a decision the deposit does not record and the
    # prompt therefore states, while how many of it there are follows from the
    # box the agent chose.  Both sides are decomposed into Lipid21 components
    # first, because a CHARMM reference writes one DPP residue per lipid and a
    # correct Amber submission writes PC + PA + PA for the same chemistry.
    stated = (task["reference"].get("bilayer") or {}).get("lipid")
    stated = stated if isinstance(stated, str) else None
    # Read from the topology rather than from the prepared structure: the bilayer
    # is added at the solvation step, so a membrane system's prepared structure
    # holds the receptor alone and reads as "no lipid" however good the membrane
    # it was later embedded in.  The topology is the system that actually ran.
    reference_lipids = cp.lipid_species(bundle / "reference.pdb")
    submitted_lipids = cp.lipid_species(topology_pdb)
    minimum = float(spec.get("membrane_matches_reference", {})
                    .get("minimum_fraction_of_reference_lipids", 0.5))
    wanted, reference_count = cp.lipid_chemistry(reference_lipids, stated)
    built, submitted_count = cp.lipid_chemistry(submitted_lipids, stated)

    def _tally(counts):
        return ", ".join(f"{n} x{c}" for n, c in sorted(counts.items())) or "no lipid"

    if not reference_lipids:
        check("membrane_matches_reference", not submitted_lipids,
              "the reference carries no bilayer; the submission carries "
              + (_tally(submitted_lipids) if submitted_lipids else "none either"))
    else:
        enough = submitted_count >= minimum * reference_count
        check("membrane_matches_reference", wanted == built and enough,
              f"reference {_tally(reference_lipids)}"
              + (f" ({stated})" if stated else "")
              + f" against submitted {_tally(submitted_lipids)}"
              + ("" if wanted == built
                 else f"; chemistry differs: {sorted(wanted)} vs {sorted(built)}")
              + ("" if enough else f"; {submitted_count} lipids is fewer than "
                                   f"{minimum:g} of the reference's {reference_count}"))

    pairs, mismatches = cp.match_monomers(reference_monomers, submitted_monomers)
    comparison_pairs = pairs
    correspondence_kind = "component pairing"
    if mismatches and not partition_error:
        positional = cp.positional_pairs_if_identical(
            reference_monomers, submitted_monomers)
        if positional:
            comparison_pairs = positional
            correspondence_kind = "identical full sequence in file order"

    complete_links, missing_links, unexpected_links = cp.compare_backbone_links(
        reference_residues, submitted_residues, comparison_pairs,
        reference_mapped_links, submitted_mapped_links)
    connectivity_ok = (not partition_error and complete_links
                       and not missing_links and not unexpected_links)
    component_detail = (
        f"backbone component sizes reference "
        f"{[len(monomer) for monomer in reference_monomers]}, submitted "
        f"{[len(monomer) for monomer in submitted_monomers]}")
    if partition_error:
        component_detail += f"; not comparable: {partition_error}"
    elif not complete_links:
        component_detail += "; declared links not comparable: no complete residue correspondence"
        if mismatches:
            component_detail += "; " + "; ".join(mismatches)
    else:
        if unexpected_links:
            component_detail += "; unexpected link(s): " + ", ".join(
                _describe_backbone_link(link) for link in unexpected_links[:4])
        if missing_links:
            component_detail += "; missing link(s): " + ", ".join(
                _describe_backbone_link(link) for link in missing_links[:4])
        if not missing_links and not unexpected_links:
            component_detail += "; declared backbone links agree"
    check("monomer_count_matches_reference", connectivity_ok, component_detail)

    # Positions whose protonation is a metal-site modelling decision. Taken from
    # the built structures, which still carry the deposit's coordinates, and
    # unioned across the two sides: the reference has already lost ligands by the
    # time its structure file is written, and a set derived from the trajectory
    # would exempt residues that were never ligands -- 6WRH's zinc reaches
    # GLN191:OE1 at 1.75 A once its thiolates leave.
    # From the same structure the monomers were split on. Reading the metals
    # from the prepared file while the monomers come from the minimised one
    # compares coordinates from two different frames: minimisation moves the
    # whole system, so every ligand distance is measured against a metal that is
    # no longer where the residue thinks it is, and the site stops being found.
    # Measured on 6W9C, that drops all three zinc thiolates out of the exemption
    # and reports them as composition differences.
    submitted_metals = cp.read_metals(minimized_structure)
    reference_metals = cp.read_metals(bundle / "reference.pdb")
    comparison_reference_monomers = [pair[0] for pair in comparison_pairs]
    comparison_submitted_monomers = [pair[1] for pair in comparison_pairs]
    submitted_ligands = cp.metal_ligand_positions(
        comparison_submitted_monomers, submitted_metals)
    reference_ligands = cp.metal_ligand_positions(
        comparison_reference_monomers, reference_metals)
    # A catalytic cysteine-histidine pair is exempted for the same reason the
    # metal ligands are: there is no settled target. The literature disagrees
    # with itself about whether such a pair is a thiolate-imidazolium ion pair
    # or neutral, and the disagreement is between experiments on the same
    # enzyme, so a benchmark that scores one answer scores a coin flip.
    # Reference side only: measured 2026-08-24, the submission-side call changed
    # no exemption on any solved job, and its 3.5 A test flips with the frame
    # (6W9C's pair is 3.30 A minimised, 3.68 A on the topology) while the
    # reference finds the same pair at 2.98-3.11 A, the range 3.5 A was set on.
    reference_dyads = cp.catalytic_dyad_positions(
        comparison_reference_monomers, reference_metals)

    findings = {"sequence": [], "atom_counts": [], "elements": []}
    exempt_total = 0
    for reference_monomer, submitted_monomer in comparison_pairs:
        exempt = (submitted_ligands.get(id(submitted_monomer), set())
                  | reference_ligands.get(id(reference_monomer), set())
                  | reference_dyads.get(id(reference_monomer), set()))
        exempt_total += len(exempt)
        comparison = cp.compare_monomer(reference_monomer, submitted_monomer,
                                        exempt=exempt)
        for key, value in comparison.items():
            findings[key].extend(value)

    residue_total = sum(len(m) for m in reference_monomers)
    complete_residue_correspondence = (
        sum(len(reference) for reference, _ in comparison_pairs) == residue_total
        and sum(len(submitted) for _, submitted in comparison_pairs)
        == sum(len(monomer) for monomer in submitted_monomers))
    check("sequence_matches_reference",
          complete_residue_correspondence and not findings["sequence"],
          f"{sum(len(m) for m in submitted_monomers)} residues (expect {residue_total}) "
          f"in {len(submitted_monomers)} backbone component(s)"
          + ("; not compared: no exact residue correspondence"
             if not complete_residue_correspondence else
             f"; sequence differs at {findings['sequence'][:4]}" if findings["sequence"]
             else f"; identical after canonicalising protonation ({correspondence_kind})"))

    # Per-residue atom counts. Tautomer-blind by construction (HID and HIE have
    # the same formula) and sensitive to every ionisation and bonding variant,
    # which is what the old total-atom tolerance of +/-2 was silently letting
    # through: one HIP costs exactly one hydrogen.
    check("residue_atom_counts_match_reference",
          complete_residue_correspondence and not findings["atom_counts"],
          f"{residue_total} residues compared per monomer"
          + (f", {exempt_total} exempt as metal ligands or a catalytic dyad"
             if exempt_total else "")
          + ("; not compared: no exact residue correspondence"
             if not complete_residue_correspondence else
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
        _check_topology_chemistry(
            check, submitted_topology, submitted_bonds, reference_topology,
            spec_valid, reference_monomers, submitted_monomers)

    # --- the force field, from the System itself ------------------------------
    # Reading the System is a precondition, not an achievement: a file that will
    # not deserialise leaves the scorer unable to look at the force field at all.
    # It used to raise straight out of the scorer, so a broken submission crashed
    # the run instead of being recorded; everything below is reported either way.
    system, load_error = _load_system(topo / "artifacts" / "system.system.xml",
                                      submitted_system)
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

    parameters = amber.get("parameters") if isinstance(amber, dict) else None
    provenance = (
        amber.get("forcefield_provenance") if isinstance(amber, dict) else None
    )
    water_value = parameters.get("water_model") if isinstance(parameters, dict) else None
    xml_values = provenance.get("openmm_xml") if isinstance(provenance, dict) else None
    water = water_value.lower() if isinstance(water_value, str) else ""
    xmls = (
        " ".join(xml_values).lower()
        if isinstance(xml_values, list)
        and all(isinstance(value, str) for value in xml_values)
        else ""
    )
    metadata_errors = []
    if not isinstance(water_value, str) or not water_value.strip():
        metadata_errors.append("parameters.water_model is missing or not a string")
    if (
        not isinstance(xml_values, list)
        or not xml_values
        or not all(isinstance(value, str) for value in xml_values)
    ):
        metadata_errors.append(
            "forcefield_provenance.openmm_xml is missing or not a non-empty string list"
        )
    wanted = task["reference"]["reference_conditions"]["WAT"].lower()
    check(
        "water_model_matches_reference",
        not metadata_errors and wanted in water and wanted in xmls,
        (
            "amber_metadata.json cannot establish the water model: "
            + "; ".join(metadata_errors)
            if metadata_errors
            else f"parameters.water_model={water!r}, forcefield xml carries "
                 f"{wanted}: {wanted in xmls}"
        ),
    )

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
    # Placed through the monomer pairing, not through residue numbers. The two
    # sides share no numbering -- an antibody numbers each of its three chains
    # from 1, and a submission keeps the deposit's while the reference renumbers
    # -- so a (residue number, atom name) lookup either misses or, worse, hits
    # the wrong residue and says nothing: on 1AHW it reported 1908 of 1908
    # matched with 1266 of them up to 88.8 A from the atom they name.
    own_list, missing = cp.contract_correspondence(
        indices, reference_atoms, pdb_atoms(minimized_structure), comparison_pairs)
    # dtype, because an empty list is float64 and indexing traj.xyz with it
    # raises instead of leaving the `if missing:` branch below to report it.
    own_indices = np.array(own_list, dtype=int)
    check("contract_atoms_resolvable", not missing,
          f"{len(own_list)}/{len(indices)} contract atoms placed through "
          f"{correspondence_kind}" + (f"; {missing[:3]}" if missing else ""))

    # Thinned to the reference windows' 10 ps so both sides carry the same number
    # of samples; measured, the statistics move by less than 0.02 across strides
    # of 1, 10 and 20 ps, but matching them costs nothing.
    calibration = task["reference"].get("md_calibration") or {}
    window_ns = float(calibration.get("window_ns") or 1.0)
    analysis_slice, analysis_window_detail = last_complete_window_slice(
        traj.n_frames, interval, window_ns)
    stride = max(1, int(round(10.0 / (interval or 10.0))))
    own_xyz = (None if analysis_slice is None else
               traj.xyz[analysis_slice][::stride][:, own_indices, :] * 10.0)

    full_reference_profile = np.asarray(json.loads(
        (bundle / "reference_fluctuation.json").read_text())["y"]["rmsf"]["data"],
        dtype=float)
    # The MDDB analysis is full-system and uses null for atoms it did not
    # analyse (mostly solvent and lipid in eight membrane references).  The
    # calibrated measurement is over the PCA contract atoms, all of which are
    # defined in those eight bundles, so select that set before doing arithmetic.
    reference_profile = full_reference_profile[indices] * 10.0
    reference_profile_defined = np.isfinite(reference_profile)
    full_reference_profile_defined = int(np.isfinite(full_reference_profile).sum())
    reference_profile_detail = (
        f"{int(reference_profile_defined.sum())}/{len(reference_profile)} reference "
        f"contract atoms have defined RMSF; "
        f"{full_reference_profile_defined}/"
        f"{len(full_reference_profile)} full-system entries are defined"
    )
    reference_profile_suffix = (
        f"; {reference_profile_detail}"
        if full_reference_profile_defined != len(full_reference_profile)
        else ""
    )

    # A range over a hundred windows is not the range of the population, and the
    # difference is measurable: held-out reference windows fall outside the range
    # of the rest 7 to 16 per cent of the time. Widening it by twice the window
    # spread takes that to zero on all three tasks, and the negative controls are
    # separated by so much more than that -- they still all fail at three times
    # the spread -- that the room costs nothing.
    # The slack is per check, because what each one needs and what each one can
    # afford differ. Measured 2026-08-23 by leave-one-replica-out over the 39
    # references that have replicas: the rank correlation needs 2 window SD at
    # the median and the radius of gyration 2, while what an adversarial
    # baseline leaves as room varies over two orders of magnitude between tasks.
    recorded_slack = calibration.get("slack_window_sd")
    spread = calibration.get("observed_window_sd") or {}

    def slack_for(key):
        """The slack this check was calibrated with.

        Missing is not zero.  Falling back to zero gives an unwidened band, and
        an unwidened band rejects a correct submission 7 to 16 per cent of the
        time by this suite's own measurement, so a partial record has to stop
        the run rather than quietly harden it.
        """
        if isinstance(recorded_slack, dict):
            if key not in recorded_slack:
                raise SystemExit(
                    f"{task['task_id']}: md_calibration records no slack for {key}")
            return float(recorded_slack[key])
        return float(recorded_slack or 0.0)

    def widened(band, key):
        return widened_calibration_band(
            band, key, slack_for(key), spread.get(key, 0.0))

    def banded(check_id, value, band, key, unit=""):
        """Inside the range the reference's own windows span, plus the slack."""
        band = widened(band, key)
        if value is None or not band:
            check(check_id, False, "not measurable: no value or no calibrated band")
            return
        low, high = band
        lower_slack = slack_for(key) * (
            FLUCTUATION_LOWER_SLACK_MULTIPLIER
            if key == "total_fluctuation_angstrom" else 1.0)
        slack_detail = (f"{lower_slack:g} lower / {slack_for(key):g} upper"
                        if lower_slack != slack_for(key)
                        else f"{slack_for(key):g}")
        check(check_id, low <= value <= high,
              f"{value:.4f}{unit} against the reference's own {window_ns:g} ns windows "
              f"[{low:.4f}, {high:.4f}]{unit} "
              f"(n={calibration.get('windows')}, widened by {slack_detail} window SD"
              + (f" and global replica factor "
                 f"{GLOBAL_REPLICA_FLUCTUATION_FACTOR:.6f}"
                 if key == "total_fluctuation_angstrom" else "")
              + f"); submission uses {analysis_window_detail}")

    if missing:
        for check_id in ("fluctuation_profile_matches_reference",
                         "fluctuation_magnitude_is_physical",
                         "radius_of_gyration_matches_reference"):
            check(check_id, False,
                  f"not evaluable: {len(missing)} of {len(indices)} reference contract "
                  f"atoms could not be placed in the submission; {missing[:2]}")
        agreement = None
    elif own_xyz is None:
        agreement = None
        for check_id in ("fluctuation_profile_matches_reference",
                         "fluctuation_magnitude_is_physical",
                         "radius_of_gyration_matches_reference"):
            check(check_id, False, f"not measurable: {analysis_window_detail}")
    elif not reference_profile_defined.all():
        agreement = None
        check(
            "fluctuation_profile_matches_reference",
            False,
            "not measurable without changing the calibrated atom set: "
            + reference_profile_detail,
        )
    else:
        agreement = dy.profile_agreement(dy.atom_fluctuations(own_xyz),
                                         reference_profile)
        # One-sided: agreement above the floor is agreement, and a profile that
        # matched better than any reference window would be no complaint.
        floor = (widened(calibration.get("rank_correlation"),
                         "rank_correlation") or [None])[0]
        check("fluctuation_profile_matches_reference",
              agreement is not None and floor is not None and agreement >= floor,
              f"rank correlation {agreement:.4f} against a floor of {floor:.4f} taken "
              f"from the reference's own {window_ns:g} ns windows "
              f"(n={calibration.get('windows')}, widened by "
              f"{slack_for('rank_correlation')} window SD)"
              f"{reference_profile_suffix}; submission uses {analysis_window_detail}"
              if agreement is not None and floor is not None else
              "not measurable: the profiles could not be compared")

    if not missing and own_xyz is not None:
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
        "submitted_backbone_connectivity": ({
            "schema_version": 1,
            "source": "submitted_openmm_system_force_bearing_bonds",
            "topology_pdb_sha256": _sha256(topology_pdb),
            "topology_atoms": len(submitted_topology.atoms),
            "topology_residues": len(submitted_topology.residues),
            "links": submitted_backbone_links,
        } if not topology_error else None),
        "fluctuation_rank_correlation": agreement,
        "n_frames": int(traj.n_frames),
        "built_energy_per_atom_kj_mol": built.get("energy_per_particle_kj_mol"),
        "minimized_energy_per_atom_kj_mol":
            (relaxed.get("energy_per_particle_kj_mol") if minimized is not None else None),
        "minimized_max_force_kj_mol_nm":
            (relaxed.get("max_force_kj_mol_nm") if minimized is not None else None)})
