"""Verify how much simulated time a trajectory actually contains.

The recorded ``simulation_time_ns`` is the runner's own claim.  This measures
it instead, from the solvent.

The self-diffusion coefficient is intensive and cannot distinguish a long run
from a short one — measured on the same trajectory it comes out at
3.7e-5 cm^2/s whether you read 1 ns or 100 ps of it.  The *accumulated*
displacement is extensive and does distinguish them: continuously unwrapping
the frame-to-frame minimum-image displacement recovers the true elapsed time
to within a percent.

A submission with no solvent cannot be measured at all, which is the correct
verdict for an ensemble that was generated without dynamics.

The frame interval comes from the DCD header, not from ``traj.time``.  mdtraj's
DCD reader discards the header's timing fields and returns ``arange(n_frames)``,
so ``traj.time`` counts frames rather than picoseconds and the clock silently
scales by ``1 ps / true_interval``: measured 2026-08-21, one 1 ns run written
every 2 ps clocked 489 ps and failed, and the same run written every 1 ps
clocked 989 ps and passed.  The engine writes ``DELTA`` (integration step, in
AKMA units) and ``NSAVC`` (steps between saves) into the header, and their
product is the interval.  That is engine-written rather than agent-written, and
a truncated trajectory keeps it honest while losing frames — which is how the
truncation baselines are caught.
"""

from __future__ import annotations

from mddatabench import _threads  # noqa: F401  must precede numpy

import struct

import numpy as np

CHECK_ID = "elapsed_simulated_time@1"
MAX_TRACERS = 1000          # a diffusive clock needs tracers, not every water
MAX_LAGS = 40               # the fit is linear; forty points determine it
TRACER_SEED = 20260819
AKMA_PS = 0.04888821        # one AKMA time unit, in picoseconds


def dcd_frame_interval_ps(path) -> float | None:
    """Frame interval in ps from the DCD header. None when it cannot be read."""
    try:
        with open(path, "rb") as handle:
            head = handle.read(92)
        if len(head) < 92 or head[4:8] != b"CORD":
            return None
        for endian in ("<", ">"):
            if struct.unpack(endian + "i", head[:4])[0] != 84:
                continue
            nsavc = struct.unpack(endian + "9i", head[8:44])[2]
            charmm = struct.unpack(endian + "10i", head[48:88])[-1]
            delta = (struct.unpack(endian + "f", head[44:48])[0] if charmm
                     else struct.unpack(endian + "d", head[44:52])[0])
            interval = delta * AKMA_PS * nsavc
            return interval if interval > 0 else None
    except (OSError, struct.error):
        return None
    return None


def elapsed_time_ps(traj, selection: str = "water and name O",
                    max_tracers: int = MAX_TRACERS, max_lags: int = MAX_LAGS,
                    dt_ps: float | None = None) -> dict:
    """Estimate elapsed simulated time from accumulated solvent displacement.

    ``dt_ps`` is the frame interval, from ``dcd_frame_interval_ps``.  Without it
    the fallback to ``traj.time`` makes the result a frame count, not a time.
    """
    atoms = traj.topology.select(selection)
    if len(atoms) < 100:
        return {"measurable": False, "reason": f"only {len(atoms)} solvent atoms; "
                "a trajectory without bulk solvent carries no diffusive clock"}
    if traj.n_frames < 5:
        return {"measurable": False, "reason": f"only {traj.n_frames} frames"}
    if len(atoms) > max_tracers:
        rng = np.random.default_rng(TRACER_SEED)
        atoms = np.sort(rng.choice(atoms, max_tracers, replace=False))
    box = traj.unitcell_lengths[:, 0]
    step = np.diff(traj.xyz[:, atoms, :], axis=0)
    step -= box[1:, None, None] * np.round(step / box[1:, None, None])
    walk = np.cumsum(step, axis=0)
    dt = float(dt_ps) if dt_ps else float(traj.time[1] - traj.time[0])

    horizon = max(2, (traj.n_frames - 1) // 5)
    lags = np.unique(np.linspace(1, horizon, min(max_lags, horizon)).astype(int))
    msd = [float(np.mean(np.sum((walk[k:] - walk[:-k]) ** 2, axis=2))) for k in lags]
    slope = float(np.polyfit(lags * dt, msd, 1)[0])
    diffusion = slope / 6.0                                   # nm^2 / ps
    total = float(np.mean(np.sum(walk[-1] ** 2, axis=1)))
    return {"measurable": True,
            "elapsed_ps": total / (6.0 * diffusion) if diffusion > 0 else 0.0,
            "total_msd_nm2": total,
            "diffusion_1e5_cm2_s": diffusion * 1e3,
            "frame_interval_ps": dt,
            "frame_interval_source": "dcd_header" if dt_ps else "traj.time",
            "n_tracers": int(len(atoms))}
