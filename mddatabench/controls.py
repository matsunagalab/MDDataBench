"""Adversarial baselines for the md-side checks.

A benchmark whose floor baselines pass is not measuring anything.  These are
the submissions that must fail, and the reason each must fail:

    isotropic_noise     no dynamics; jitter around the deposited structure
    duplicated_minimum  no dynamics; one structure repeated
    anm_ensemble        no dynamics; sampled along elastic-network modes
    truncated_10ps      real MD, but a hundredth of the required length
    truncated_100ps     real MD, but a tenth of the required length

Run this whenever the md-side thresholds change.  Measured 2026-08-19: with
the random-subspace null alone, anm_ensemble and both truncations passed.
"""

from __future__ import annotations

from mddatabench import _threads  # noqa: F401  must precede numpy

import json
import pathlib

import mdtraj as md
import numpy as np

from mddatabench import execution as ex
from mddatabench import subspace as st
from mddatabench.scoring import find_node


def load_reference(bundle: pathlib.Path, n_atoms: int):
    indices = json.loads((bundle / "pca_atom_indices.json").read_text())["atom_indices"]
    rows = [line for line in open(bundle / "reference.pdb")
            if line.startswith(("ATOM", "HETATM"))]
    coords = np.array([[float(rows[i][30:38]), float(rows[i][38:46]), float(rows[i][46:54])]
                       for i in indices])
    frames = np.fromfile(bundle / "reference_frames.f32", dtype="<f4")
    frames = frames.reshape(-1, n_atoms, 3).astype(np.float64)[:, indices, :]
    _, subspace = st.essential_subspace(frames, coords)
    return indices, rows, coords, subspace


def run_negative_controls(job_dir: str, bundle: str, task_file: str) -> dict:
    """Score the baselines that must fail, plus the real run that must pass."""
    job_dir, bundle = pathlib.Path(job_dir), pathlib.Path(bundle)
    task = json.loads(pathlib.Path(task_file).read_text())
    n_atoms = task["reference"]["reference_system"]["PROTATS"]
    indices, rows, coords, reference = load_reference(bundle, n_atoms)
    null = st.anm_null_distribution(coords, reference)
    fraction = next(c for c in task["scoring"]["deterministic_checks"]
                    if c["check_id"] == "elapsed_simulated_time_is_physical"
                    )["minimum_measured_fraction_of_claim"]

    # Same node-selection rule as the scorer: the latest COMPLETED node. Globbing
    # instead picked up an abandoned run left in `running`, and the two tools then
    # silently graded different trajectories (0.818 against 0.828).
    topology = find_node(job_dir, "topo") / "artifacts" / "system.topology.pdb"
    traj_path = next((find_node(job_dir, "prod") / "artifacts").glob("*.dcd"))
    traj = md.load(str(traj_path), top=str(topology))
    # Frame interval from the header, as the scorer does. Slicing a loaded
    # trajectory keeps `traj.time` as a frame count, so the truncations would
    # otherwise be clocked in the wrong unit and could pass.
    interval = ex.dcd_frame_interval_ps(traj_path)
    lookup = {}
    n = 0
    for line in open(topology):
        # index by atom ordinal, not by file line: the topology carries headers
        if line.startswith(("ATOM", "HETATM")):
            lookup.setdefault((line[22:27].strip(), line[12:16].strip()), n)
            n += 1
    own = np.array([lookup[(rows[i][22:27].strip(), rows[i][12:16].strip())] for i in indices])
    rng = np.random.default_rng(11)

    def judge(name, must_pass, xyz, sub_traj, claimed_ns=1.0):
        _, subspace = st.essential_subspace(xyz, coords)
        test = st.test_beyond_structure(subspace, reference, coords, null=null)
        if sub_traj is None:
            timed = False
            clock = {"measurable": False, "reason": "no solvent"}
        else:
            clock = ex.elapsed_time_ps(sub_traj, dt_ps=interval)
            timed = (clock["measurable"]
                     and clock["elapsed_ps"] / (claimed_ns * 1000.0) >= fraction)
        passed = bool(test["h0_rejected"] and timed)
        return {"baseline": name, "must_pass": must_pass, "passed": passed,
                "correct": passed == must_pass,
                "rmsip": test["rmsip"], "z_score": test["z_score"],
                "h0_rejected": test["h0_rejected"], "clock_ok": timed}

    real = traj.xyz[:, own, :] * 10.0
    results = [
        judge("real_full_run", True, real, traj),
        judge("truncated_100ps", False, real[:100], traj[:100]),
        judge("truncated_10ps", False, real[:10], traj[:10]),
        judge("anm_ensemble", False, anm_ensemble(coords, rng), None),
        judge("isotropic_noise", False,
              coords[None] + rng.normal(0, 0.5, size=(500,) + coords.shape), None),
        judge("duplicated_minimum", False,
              np.repeat(coords[None], 500, axis=0)
              + rng.normal(0, 1e-4, size=(500,) + coords.shape), None),
    ]
    return {"task_id": task["task_id"],
            "structure_only_null": {"mean": float(null.mean()), "sd": float(null.std()),
                                    "max": float(null.max()), "n_cutoffs": int(len(null))},
            "minimum_clock_fraction": fraction,
            "results": results,
            "all_correct": all(r["correct"] for r in results)}


def anm_ensemble(coords, rng, n_frames: int = 500):
    """Sample along elastic-network modes: the strongest no-dynamics attack."""
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

