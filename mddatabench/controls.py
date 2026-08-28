"""Adversarial baselines for the md-side checks.

A benchmark whose floor baselines pass is not measuring anything.  These are
the submissions that must fail, and the reason each must fail:

    compressed_structure  real motion on a structure scaled to 85 per cent
    isotropic_noise     no dynamics; jitter around the deposited structure
    duplicated_minimum  no dynamics; one structure repeated
    anm_ensemble        no dynamics; sampled along elastic-network modes
    frozen_first_frame  real MD, but every frame replaced by the first
    shuffled_atoms      real MD, with the per-atom motion permuted
    scaled_motion_x5    real MD, with every deviation multiplied by five
    truncated_10ps      real MD, but a hundredth of the required length
    truncated_100ps     real MD, but a tenth of the required length

Rewritten 2026-08-23.  It used to judge on the subspace test, which was
retired on 2026-08-22 after the measurement that killed it: an ANM ensemble
with no dynamics at all reached RMSIP 0.749 against a real run's 0.704, so the
test the controls were built around was ranking a fake above the truth.  The md
side now decides on equilibrium quantities banded against the reference's own
windows, and these baselines are judged on those instead.

Three baselines are new, and each targets one of the replacements
specifically -- ``shuffled_atoms`` the rank correlation, ``frozen_first_frame``
and ``scaled_motion_x5`` the fluctuation magnitude -- because a gate nothing
attacks is a gate nobody has tested.

**Those three keep the real trajectory.**  Reviewed the same day: handing a
synthetic ensemble no trajectory forces the clock gate false, and since a
verdict is the conjunction of every gate, all three would have scored correct
with the gates they exist to test deleted.  Only a baseline that passes the
clock puts weight on the structure gates.  Attacking the solute while leaving
the solvent alone is also the realistic attack -- a run that happened, then was
post-processed.

``gates_never_decisive`` counts a gate as tested only when some baseline's
verdict rests on it *alone*.  Counting every gate that merely fired reported a
suite as exercised while nothing depended on any of it.

Run this whenever an md-side threshold or a band changes.
"""

from __future__ import annotations

from mddatabench import _threads  # noqa: F401  must precede numpy

import json
import pathlib

import mdtraj as md
import numpy as np

from mddatabench import composition as cp
from mddatabench import dynamics as dy
from mddatabench import execution as ex
from mddatabench import scoring as sc
from mddatabench import topology as tp
from mddatabench.scoring import find_node


GATES = frozenset({"fluctuation_profile", "fluctuation_magnitude",
                   "radius_of_gyration", "solvent_clock"})


def load_reference(bundle: pathlib.Path):
    """Contract atoms, the deposited coordinates and the reference RMSF profile."""
    indices = json.loads((bundle / "pca_atom_indices.json").read_text())["atom_indices"]
    rows = [line for line in open(bundle / "reference.pdb")
            if line.startswith(("ATOM", "HETATM"))]
    coords = np.array([[float(rows[i][30:38]), float(rows[i][38:46]), float(rows[i][46:54])]
                       for i in indices])
    profile = np.asarray(json.loads(
        (bundle / "reference_fluctuation.json").read_text())["y"]["rmsf"]["data"],
        dtype=float)[indices] * 10.0
    return indices, coords, profile


def _bands(task):
    """The three bands the md checks use, already widened by the measured slack."""
    calibration = task["reference"].get("md_calibration") or {}
    # The slack became per check on 2026-08-23; reading it as one float raised
    # here, which meant the suite that guards every md threshold could not run
    # against the cast whose thresholds had just changed.
    slack = calibration.get("slack_window_sd")
    spread = calibration.get("observed_window_sd") or {}

    def slack_for(key):
        if isinstance(slack, dict):
            if key not in slack:
                raise SystemExit(
                    f"{task['task_id']}: no slack recorded for {key}; scoring it "
                    "against an unwidened band would reject correct submissions")
            return float(slack[key])
        return float(slack or 0.0)

    def widened(key):
        band = calibration.get(key)
        return sc.widened_calibration_band(
            band, key, slack_for(key), spread.get(key, 0.0))

    return {key: widened(key) for key in
            ("rank_correlation", "total_fluctuation_angstrom",
             "radius_of_gyration_angstrom")}, calibration


def run_negative_controls(job_dir: str, bundle: str, task_file: str) -> dict:
    """Score the baselines that must fail, plus the real run that must pass."""
    job_dir, bundle = pathlib.Path(job_dir), pathlib.Path(bundle)
    task = json.loads(pathlib.Path(task_file).read_text())
    indices, coords, profile = load_reference(bundle)
    bands, calibration = _bands(task)
    fraction = next(c for c in task["scoring"]["deterministic_checks"]
                    if c["check_id"] == "elapsed_simulated_time_is_physical"
                    )["minimum_measured_fraction_of_claim"]

    # Same node-selection rule as the scorer, which walks parent_node_ids back
    # from the production node. Globbing instead picked up an abandoned run left
    # in `running`, and the two tools then silently graded different
    # trajectories (0.818 against 0.828).
    topology = find_node(job_dir, "topo") / "artifacts" / "system.topology.pdb"
    prod_node = find_node(job_dir, "prod")
    traj_path = next((prod_node / "artifacts").glob("*.dcd"))
    traj = md.load(str(traj_path), top=str(topology))
    # Frame interval from the header, as the scorer does. Slicing a loaded
    # trajectory keeps `traj.time` as a frame count, so the truncations would
    # otherwise be clocked in the wrong unit and could pass.
    interval = ex.dcd_frame_interval_ps(traj_path)
    # Placed exactly as the scorer places them, through the monomer pairing.
    # This used to run its own (residue number, atom name) lookup against the
    # topology node while the scorer used the minimised structure, and the two
    # then disagreed about the same submission: 819 of 819 for the scorer,
    # "228 absent" and unrunnable here.
    minimized = find_node(job_dir, "min") / "artifacts" / "minimized_structure.pdb"
    reference_atoms = sc.pdb_atoms(bundle / "reference.pdb")
    reference_residues = cp.read_residues(bundle / "reference.pdb")
    submitted_residues = cp.read_residues(minimized)
    reference_topology = tp.load_reference(
        tp.find_reference_topology(bundle), bundle / "reference.pdb")
    submitted_topology, submitted_bonds, topology_error, _ = tp.load_submission(
        find_node(job_dir, "topo") / "artifacts" / "system.system.xml", topology)
    if topology_error:
        return {"task_id": task["task_id"], "unrunnable": topology_error}
    reference_monomers, _ = cp.split_monomers_by_backbone_links(
        reference_residues, reference_topology.residues,
        tp.backbone_links(reference_topology), tp.POLYMER_RESIDUES)
    submitted_monomers, _ = cp.split_monomers_by_backbone_links(
        submitted_residues, submitted_topology.residues,
        tp.backbone_links(submitted_topology, submitted_bonds), tp.POLYMER_RESIDUES)
    pairs, mismatches = cp.match_monomers(reference_monomers, submitted_monomers)
    if mismatches:
        pairs = cp.positional_pairs_if_identical(reference_monomers, submitted_monomers)
    own, missing = cp.contract_correspondence(
        indices, reference_atoms, sc.pdb_atoms(minimized), pairs)
    if missing:
        # The scorer downgrades this to three failed checks and carries on; a
        # KeyError here would lose the whole report instead.
        return {"task_id": task["task_id"],
                "unrunnable": f"{len(missing)} of {len(indices)} reference contract atoms "
                              f"could not be placed in the submission; {missing[:2]}"}
    own = np.array(own, dtype=int)
    rng = np.random.default_rng(11)

    # The scorer thins the trajectory to the windows' own 10 ps before measuring,
    # so measuring every frame here would let a run near a band edge come out
    # differently in the two tools.
    stride = max(1, int(round(10.0 / (interval or 10.0))))

    # The clock is a ratio against what the run claimed, and the scorer takes
    # that claim from the production node rather than assuming one nanosecond.
    claimed = float(json.loads((prod_node / "node.json").read_text())
                    .get("metadata", {}).get("simulation_time_ns") or 1.0)

    def judge(name, must_pass, xyz, sub_traj, claimed_ns=None):
        """Every md gate that can be evaluated without an energy log or a box."""
        gates = {}
        agreement = dy.profile_agreement(dy.atom_fluctuations(xyz), profile)
        floor = bands["rank_correlation"]
        gates["fluctuation_profile"] = bool(
            floor and agreement is not None and agreement >= floor[0])
        total = float(dy.total_fluctuation(xyz))
        band = bands["total_fluctuation_angstrom"]
        gates["fluctuation_magnitude"] = bool(band and band[0] <= total <= band[1])
        rgyr = float(dy.radius_of_gyration(xyz).mean())
        band = bands["radius_of_gyration_angstrom"]
        gates["radius_of_gyration"] = bool(band and band[0] <= rgyr <= band[1])
        if sub_traj is None:
            gates["solvent_clock"] = False
            clock = {"measurable": False, "reason": "synthetic ensemble: no solvent"}
        elif interval is None:
            # elapsed_time_ps would fall back to traj.time, which after slicing
            # is a frame count rather than picoseconds. The scorer fails the
            # check outright in this case; so does this.
            gates["solvent_clock"] = False
            clock = {"measurable": False, "reason": "no frame interval in the header"}
        else:
            clock = ex.elapsed_time_ps(sub_traj, dt_ps=interval)
            gates["solvent_clock"] = bool(
                clock["measurable"]
                and clock["elapsed_ps"] / ((claimed_ns or claimed) * 1000.0) >= fraction)
        passed = all(gates.values())
        failed = sorted(k for k, ok in gates.items() if not ok)
        return {"baseline": name, "must_pass": must_pass, "passed": passed,
                "correct": passed == must_pass,
                "gates": gates,
                "caught_by": failed,
                # A gate only decides a verdict when it is the one that failed.
                # Counting every gate that merely fired reports a suite as
                # exercised when nothing depended on it.
                "decided_by": failed[0] if len(failed) == 1 else None,
                "rank_correlation": agreement,
                "total_fluctuation_angstrom": total,
                "radius_of_gyration_angstrom": rgyr,
                "elapsed_ps": clock.get("elapsed_ps")}

    real = traj.xyz[::stride][:, own, :] * 10.0
    fitted_real = dy.fitted(real)
    mean_structure = fitted_real.mean(axis=0)
    frames_ps = max(1, int(round(100.0 / (interval or 10.0))))     # ~100 ps
    tenth_ps = max(1, int(round(10.0 / (interval or 10.0))))       # ~10 ps
    results = [
        judge("real_full_run", True, real, traj),
        judge("truncated_100ps", False, traj.xyz[:frames_ps][::stride][:, own, :] * 10.0,
              traj[:frames_ps]),
        judge("truncated_10ps", False, traj.xyz[:tenth_ps][::stride][:, own, :] * 10.0,
              traj[:tenth_ps]),
        # The three below keep the real solvent, so the clock passes and the
        # verdict rests on the structure gates. Handing them no trajectory would
        # fail them on the clock alone, and the gates they exist to test would
        # decide nothing -- they would score correct even if deleted.
        judge("frozen_first_frame", False,
              np.repeat(real[:1], len(real), axis=0)
              + rng.normal(0, 1e-4, size=real.shape), traj),
        judge("scaled_motion_x5", False,
              mean_structure[None] + (fitted_real - mean_structure) * 5.0, traj),
        judge("shuffled_atoms", False,
              fitted_real[:, rng.permutation(len(own)), :], traj),
        # The structure compressed, its motion untouched: the only gate that
        # sees a system the wrong size is the radius of gyration, and until this
        # baseline existed nothing exercised it.
        judge("compressed_structure", False,
              mean_structure[None] * 0.85
              + (fitted_real - mean_structure), traj),
        # These three have no solvent at all, which is itself the right verdict.
        judge("anm_ensemble", False, anm_ensemble(coords, rng), None),
        judge("isotropic_noise", False,
              coords[None] + rng.normal(0, 0.5, size=(500,) + coords.shape), None),
        judge("duplicated_minimum", False,
              np.repeat(coords[None], 500, axis=0)
              + rng.normal(0, 1e-4, size=(500,) + coords.shape), None),
    ]
    return {"task_id": task["task_id"],
            "bands": bands,
            "calibration_windows": calibration.get("windows"),
            "slack_window_sd": calibration.get("slack_window_sd"),
            "minimum_clock_fraction": fraction,
            "frame_interval_ps": interval,
            "claimed_ns": claimed,
            "results": results,
            "all_correct": all(r["correct"] for r in results),
            # A gate is only tested when some baseline's verdict rests on it
            # alone. Reporting the gates that merely fired would call a suite
            # exercised while nothing depended on any of them.
            "gates_never_decisive": sorted(
                GATES - {r["decided_by"] for r in results
                         if not r["must_pass"] and r["decided_by"]})}


def anm_ensemble(coords, rng, n_frames: int = 500):
    """Sample along elastic-network modes: the strongest no-dynamics attack.

    Kept from the subspace era because it is the baseline that broke that test:
    measured 2026-08-22, its RMSIP against the reference was 0.749 where a real
    1 ns run reached 0.704.
    """
    n = len(coords)
    hessian = np.zeros((3 * n, 3 * n))
    for i in range(n):
        delta = coords - coords[i]
        distance = np.linalg.norm(delta, axis=1)
        for j in np.where((distance > 0) & (distance <= 10.0))[0]:
            block = np.outer(delta[j], delta[j]) / distance[j] ** 2
            hessian[3 * i:3 * i + 3, 3 * j:3 * j + 3] -= block
            hessian[3 * i:3 * i + 3, 3 * i:3 * i + 3] += block
    values, vectors = np.linalg.eigh(hessian)
    order = np.argsort(values)[6:]
    amplitude = 1.0 / np.sqrt(np.maximum(values[order], 1e-6))
    amplitude *= 1.5 / amplitude[0]
    coefficients = rng.normal(0, 1, size=(n_frames, len(order))) * amplitude
    return (coords.reshape(1, -1) + coefficients @ vectors[:, order].T).reshape(n_frames, -1, 3)
