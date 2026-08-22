"""What a one-nanosecond run can honestly be asked to reproduce.

The md side used to compare the submission's essential subspace against the
reference's, with a structure-only elastic-network null.  Measured 2026-08-22
on the negative controls, that test decided nothing: the elastic network scored
RMSIP 0.749 against the real run's 0.704, so a model with no dynamics at all
beat the simulation, and the control it was supposed to reject was rejected by
the solvent clock instead.

What replaced it is bounded by three deliberate blindnesses, each of which
removes a family of observables:

  * The force field is free.  Requiring the reference's force field would empty
    the eligible pool, and running under a different one is a thing we want to
    do.  So rotamer and salt-bridge occupancies are out: they are the most
    systematically force-field-dependent quantities available.
  * The protonation of ambiguous residues is free, and already exempt on the
    prep side.  So nothing may key on it.
  * The thermostat is free.  Friction sets relaxation times, so every
    time-correlation statistic is out -- lag-dependent MSD separated real runs
    (2.9-4.5) from shuffled frames (0.97-1.08) cleanly, and is still not usable,
    because it would fail a correct run for its integrator.

What survives is equilibrium properties, which a thermostat does not change.
"""

from __future__ import annotations

from mddatabench import _threads  # noqa: F401  must precede numpy

import csv

import numpy as np

from mddatabench import subspace as st


def energy_series(path):
    """Columns of an OpenMM StateDataReporter log, by their header names."""
    with open(path) as handle:
        rows = list(csv.DictReader(handle))
    if not rows:
        return {}
    lookup = {key.strip('"#'): key for key in rows[0]}
    out = {}
    for name, key in lookup.items():
        try:
            out[name] = np.array([float(row[key]) for row in rows])
        except (TypeError, ValueError):
            continue
    return out


def fitted(xyz, rounds=3):
    """Frames superposed on their own mean structure.

    Not on the first frame: fitting to frame zero puts the whole of a run's
    drift into every later frame's deviation, and a one-nanosecond run started
    from a crystal structure drifts monotonically.  Measured, the change moves
    D01's maximum RMSD from 2.011 to 1.374 A against a reference window band of
    [0.860, 1.230] -- an estimator choice, not a threshold.
    """
    reference = xyz.mean(axis=0)
    for _ in range(rounds):
        superposed = np.stack([st.kabsch(frame, reference) for frame in xyz])
        reference = superposed.mean(axis=0)
    return superposed


def atom_fluctuations(xyz, detrend=True):
    """Per-atom RMSF about the mean structure, in the units of ``xyz``.

    A linear trend in time is removed from each atom first.  The quantity these
    checks want is the equilibrium fluctuation, and a one-nanosecond run started
    from a crystal structure carries a drift that the reference's windows -- cut
    from the middle of a microsecond -- do not.  That drift lands on different
    atoms than the fluctuation does, so it moves their ranks: measured on D03,
    the rank correlation against the reference profile is 0.803 undetrended,
    below all 100 reference windows, and 0.870 detrended, inside a band of
    [0.840, 0.922].  Each half of the same run scores 0.844 and 0.828, which is
    what a drift-driven artefact looks like.

    Applied to both sides, so the comparison stays symmetric.
    """
    superposed = fitted(xyz)
    residual = superposed - superposed.mean(axis=0)
    if detrend and len(superposed) > 2:
        time = np.arange(len(superposed), dtype=float)
        time -= time.mean()
        norm = np.sqrt((time ** 2).sum())
        if norm > 0:
            unit = time / norm
            slope = np.einsum("t,tad->ad", unit, residual)
            residual = residual - unit[:, None, None] * slope[None]
    return np.sqrt((residual ** 2).sum(axis=2).mean(axis=0))


def total_fluctuation(xyz):
    """One number for how much the solute moved at all."""
    return float(np.sqrt((atom_fluctuations(xyz) ** 2).mean()))


def radius_of_gyration(xyz):
    """Per-frame radius of gyration, needing no superposition at all.

    Which is why the high side of the judgement rests here: a fit propagates a
    run's drift into every atom's deviation, and Rg has no fit.
    """
    centred = xyz - xyz.mean(axis=1, keepdims=True)
    return np.sqrt((centred ** 2).sum(axis=2).mean(axis=1))


def profile_agreement(submitted, reference):
    """Spearman correlation of two per-atom fluctuation profiles.

    Rank-based on purpose: it asks which atoms move more than which, and says
    nothing about how much.  That is what makes it survive a different force
    field and a different thermostat -- and what makes it blind to an
    over-restrained run, measured at rho 0.795 with a tenth of the motion.  The
    magnitude floor is the other half of that pair.
    """
    from scipy.stats import spearmanr

    if len(submitted) != len(reference) or len(submitted) < 3:
        return None
    result = spearmanr(np.asarray(submitted), np.asarray(reference))
    value = getattr(result, "statistic", None)
    return None if value is None or not np.isfinite(value) else float(value)


def window_statistics(series, window):
    """Non-overlapping window means of a per-frame series."""
    values = np.asarray(series, dtype=float)
    count = len(values) // window
    if count < 2:
        return np.array([])
    return np.array([values[i * window:(i + 1) * window].mean() for i in range(count)])
