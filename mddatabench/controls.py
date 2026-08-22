"""Adversarial baselines for the md-side checks.

A benchmark whose floor baselines pass is not measuring anything.  These are
the submissions that must fail, and the reason each must fail:

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

Run this whenever an md-side threshold or a band changes.
"""

from __future__ import annotations

from mddatabench import _threads  # noqa: F401  must precede numpy

import json
import pathlib

import mdtraj as md
import numpy as np

from mddatabench import dynamics as dy
from mddatabench import execution as ex
from mddatabench.scoring import find_node


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
    return indices, rows, coords, profile


def _bands(task):
    """The three bands the md checks use, already widened by the measured slack."""
    calibration = task["reference"].get("md_calibration") or {}
    slack = float(calibration.get("slack_window_sd", 0.0))
    spread = calibration.get("observed_window_sd") or {}

    def widened(key):
        band = calibration.get(key)
        if not band:
            return None
        margin = slack * float(spread.get(key, 0.0))
        return [band[0] - margin, band[1] + margin]

    return {key: widened(key) for key in
            ("rank_correlation", "total_fluctuation_angstrom",
             "radius_of_gyration_angstrom")}, calibration


def run_negative_controls(job_dir: str, bundle: str, task_file: str) -> dict:
    """Score the baselines that must fail, plus the real run that must pass."""
    job_dir, bundle = pathlib.Path(job_dir), pathlib.Path(bundle)
    task = json.loads(pathlib.Path(task_file).read_text())
    indices, rows, coords, profile = load_reference(bundle)
    bands, calibration = _bands(task)
    fraction = next(c for c in task["scoring"]["deterministic_checks"]
                    if c["check_id"] == "elapsed_simulated_time_is_physical"
                    )["minimum_measured_fraction_of_claim"]

    # Same node-selection rule as the scorer, which walks parent_node_ids back
    # from the production node. Globbing instead picked up an abandoned run left
    # in `running`, and the two tools then silently graded different
    # trajectories (0.818 against 0.828).
    topology = find_node(job_dir, "topo") / "artifacts" / "system.topology.pdb"
    traj_path = next((find_node(job_dir, "prod") / "artifacts").glob("*.dcd"))
    traj = md.load(str(traj_path), top=str(topology))
    # Frame interval from the header, as the scorer does. Slicing a loaded
    # trajectory keeps `traj.time` as a frame count, so the truncations would
    # otherwise be clocked in the wrong unit and could pass.
    interval = ex.dcd_frame_interval_ps(traj_path)
    lookup, n = {}, 0
    for line in open(topology):
        # index by atom ordinal, not by file line: the topology carries headers
        if line.startswith(("ATOM", "HETATM")):
            lookup.setdefault((line[22:27].strip(), line[12:16].strip()), n)
            n += 1
    own = np.array([lookup[(rows[i][22:27].strip(), rows[i][12:16].strip())] for i in indices])
    rng = np.random.default_rng(11)

    def judge(name, must_pass, xyz, sub_traj, claimed_ns=1.0):
        """Every md gate that can be evaluated without an energy log or a box."""
        gates = {}
        agreement = float(dy.profile_agreement(dy.atom_fluctuations(xyz), profile))
        floor = bands["rank_correlation"]
        gates["fluctuation_profile"] = bool(floor and agreement >= floor[0])
        total = float(dy.total_fluctuation(xyz))
        band = bands["total_fluctuation_angstrom"]
        gates["fluctuation_magnitude"] = bool(band and band[0] <= total <= band[1])
        rgyr = float(dy.radius_of_gyration(xyz).mean())
        band = bands["radius_of_gyration_angstrom"]
        gates["radius_of_gyration"] = bool(band and band[0] <= rgyr <= band[1])
        if sub_traj is None:
            gates["solvent_clock"] = False
            clock = {"measurable": False, "reason": "synthetic ensemble: no solvent"}
        else:
            clock = ex.elapsed_time_ps(sub_traj, dt_ps=interval)
            gates["solvent_clock"] = bool(
                clock["measurable"]
                and clock["elapsed_ps"] / (claimed_ns * 1000.0) >= fraction)
        passed = all(gates.values())
        return {"baseline": name, "must_pass": must_pass, "passed": passed,
                "correct": passed == must_pass,
                "gates": gates,
                "caught_by": sorted(k for k, ok in gates.items() if not ok),
                "rank_correlation": agreement,
                "total_fluctuation_angstrom": total,
                "radius_of_gyration_angstrom": rgyr}

    real = traj.xyz[:, own, :] * 10.0
    mean_structure = dy.fitted(real).mean(axis=0)
    results = [
        judge("real_full_run", True, real, traj),
        judge("truncated_100ps", False, real[:100], traj[:100]),
        judge("truncated_10ps", False, real[:10], traj[:10]),
        # Real trajectory, motion removed: the fluctuation magnitude has to catch it.
        judge("frozen_first_frame", False,
              np.repeat(real[:1], len(real), axis=0)
              + rng.normal(0, 1e-4, size=real.shape), None),
        # Real trajectory, motion inflated fivefold about the mean structure.
        judge("scaled_motion_x5", False,
              mean_structure[None] + (dy.fitted(real) - mean_structure) * 5.0, None),
        # Real per-atom amplitudes, permuted: only the rank correlation sees this.
        judge("shuffled_atoms", False,
              dy.fitted(real)[:, rng.permutation(len(own)), :], None),
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
            "results": results,
            "all_correct": all(r["correct"] for r in results),
            # A gate no baseline exercises has never been tested by this suite.
            "gates_never_decisive": sorted(
                {"fluctuation_profile", "fluctuation_magnitude", "radius_of_gyration",
                 "solvent_clock"}
                - {g for r in results if not r["must_pass"] for g in r["caught_by"]})}


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
