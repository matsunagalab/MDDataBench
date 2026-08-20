"""Essential-subspace agreement test for MDDataBench.

Implements one pinned analysis contract and one hypothesis test.

Contract ``pca_backbone_subspace@1``
    selection      backbone N, CA, C in residue order, N/CA/C within residue
    superposition  Kabsch fit onto a common reference structure, then 3
                   iterations of fitting onto the running mean structure
    covariance     3M x 3M covariance of the superposed, mean-centred coords
    subspace       eigenvectors of the D largest eigenvalues (default D = 10)
    units          Angstrom

Test ``subspace_beyond_structure@1``
    H0    the submission is no better than what the fold alone predicts, i.e.
          its agreement with the reference is drawn from the spread of
          elastic-network models of the same structure
    stat  RMSIP = sqrt( sum_ij (u_i . v_j)^2 / D ), the RMS inner product;
          equivalently the RMS of the canonical correlations between the two
          subspaces (cosines of the principal angles)
    null  Monte Carlo over random orthonormal D-frames.  E[RMSIP] = sqrt(D/3M)
          analytically; the Monte Carlo reproduces it and supplies the spread.
    reject H0 when the observed RMSIP exceeds every null draw.

An earlier version tested against independent uniformly random subspaces
instead.  That null is far too weak: an elastic-network ensemble that ran no
dynamics at all rejected it at z = 46, and so did a run truncated to a
hundredth of the required length.  The structure-only null subsumes it --
anything that fails against random noise fails against this too -- so only
this test is used as a gate.  ``test_unrelated`` is kept because the random
null is analytically known and is useful context to report alongside.

Rejecting H0 says the sampling contributed collective directions the fold did
not already imply.  It still says nothing about whether amplitudes converged;
RMSIP is invariant to the overall scale of the fluctuations, so a submission
uniformly expanded by 30% scores identically.  Something else has to
constrain the amplitude.
"""

from __future__ import annotations

from mddatabench import _threads  # noqa: F401  must precede numpy

import numpy as np

CONTRACT_ID = "pca_backbone_subspace@1"
TEST_ID = "subspace_beyond_structure@1"
LEGACY_TEST_ID = "subspace_unrelated@1"
DEFAULT_D = 10
DEFAULT_ANM_CUTOFFS = tuple(float(c) for c in np.arange(7.0, 20.1, 0.5))
DEFAULT_ALPHA = 1e-3
DEFAULT_NULL_DRAWS = 20000
NULL_SEED = 20260819


def kabsch(mobile: np.ndarray, target: np.ndarray) -> np.ndarray:
    """Return ``mobile`` centred and rotated onto centred ``target``."""
    p = mobile - mobile.mean(axis=0)
    q = target - target.mean(axis=0)
    v, _, wt = np.linalg.svd(p.T @ q)
    d = np.sign(np.linalg.det(v @ wt))
    return p @ (v @ np.diag([1.0, 1.0, d]) @ wt)


def superpose(traj: np.ndarray, reference: np.ndarray, iterations: int = 3) -> np.ndarray:
    """Fit every frame onto ``reference``, then onto the running mean."""
    target = reference - reference.mean(axis=0)
    fitted = np.stack([kabsch(frame, target) for frame in traj])
    for _ in range(iterations):
        target = fitted.mean(axis=0)
        fitted = np.stack([kabsch(frame, target) for frame in traj])
    return fitted


def essential_subspace(traj: np.ndarray, reference: np.ndarray, n_modes: int = DEFAULT_D):
    """Return (eigenvalues, D leading eigenvectors) under the pinned contract."""
    fitted = superpose(traj, reference)
    flat = (fitted - fitted.mean(axis=0)).reshape(len(fitted), -1)
    cov = (flat.T @ flat) / len(flat)
    values, vectors = np.linalg.eigh(cov)
    order = np.argsort(values)[::-1]
    return values[order], vectors[:, order[:n_modes]]


def canonical_correlations(u: np.ndarray, v: np.ndarray) -> np.ndarray:
    """Cosines of the principal angles between two orthonormal frames."""
    return np.linalg.svd(u.T @ v, compute_uv=False)


def rmsip(u: np.ndarray, v: np.ndarray) -> float:
    correlations = canonical_correlations(u, v)
    return float(np.sqrt((correlations ** 2).sum() / u.shape[1]))


def anm_subspace(coords: np.ndarray, cutoff: float, n_modes: int = DEFAULT_D) -> np.ndarray:
    """Lowest non-trivial modes of an anisotropic network model of ``coords``.

    This is what the fold alone predicts, with no dynamics of any kind.
    """
    n = len(coords)
    delta = coords[:, None, :] - coords[None, :, :]
    square = (delta ** 2).sum(-1)
    contact = (square > 0) & (square <= cutoff ** 2)
    blocks = np.einsum("ija,ijb->ijab", delta, delta)
    blocks /= np.where(square > 0, square, 1.0)[..., None, None]
    blocks *= contact[..., None, None]
    hessian = -blocks.transpose(0, 2, 1, 3).reshape(3 * n, 3 * n)
    diagonal = blocks.sum(axis=1)
    rows = (np.arange(n)[:, None, None] * 3 + np.arange(3)[None, :, None])
    columns = (np.arange(n)[:, None, None] * 3 + np.arange(3)[None, None, :])
    hessian[rows, columns] += diagonal
    values, vectors = np.linalg.eigh(hessian)
    return vectors[:, np.argsort(values)[6:6 + n_modes]]


def anm_floor(coords: np.ndarray, reference: np.ndarray,
              cutoffs=DEFAULT_ANM_CUTOFFS, n_modes: int = DEFAULT_D) -> dict:
    """Best subspace agreement reachable from the structure alone.

    A submission that never ran dynamics can still reach this, so a run that
    does not clear it has not shown that its sampling added anything the fold
    did not already imply.  The floor is the maximum over network cutoffs
    because the cutoff is the attacker's free parameter, not ours.
    """
    per_cutoff = {float(c): rmsip(anm_subspace(coords, c, n_modes), reference)
                  for c in cutoffs}
    best = max(per_cutoff, key=per_cutoff.get)
    return {"floor": per_cutoff[best], "best_cutoff": best, "per_cutoff": per_cutoff}


def null_distribution(dim: int, n_modes: int, draws: int = DEFAULT_NULL_DRAWS,
                      seed: int = NULL_SEED):
    """Monte Carlo null for RMSIP and for each ordered canonical correlation."""
    rng = np.random.default_rng(seed)
    stats = np.empty(draws)
    ordered = np.empty((draws, n_modes))
    for i in range(draws):
        a = np.linalg.qr(rng.standard_normal((dim, n_modes)))[0]
        b = np.linalg.qr(rng.standard_normal((dim, n_modes)))[0]
        correlations = canonical_correlations(a, b)
        ordered[i] = correlations
        stats[i] = np.sqrt((correlations ** 2).sum() / n_modes)
    return stats, ordered


def anm_null_distribution(coords: np.ndarray, reference: np.ndarray,
                          cutoffs=DEFAULT_ANM_CUTOFFS, n_modes: int = DEFAULT_D) -> np.ndarray:
    """RMSIP reachable from the structure alone, across network cutoffs.

    The cutoff is the attacker's free parameter, so the whole sweep is the
    null rather than any single choice of it.
    """
    return np.array([rmsip(anm_subspace(coords, c, n_modes), reference) for c in cutoffs])


def test_beyond_structure(own: np.ndarray, reference: np.ndarray, coords: np.ndarray,
                          cutoffs=DEFAULT_ANM_CUTOFFS, null: np.ndarray = None) -> dict:
    """Test H0 = the submission is no better than a structure-only model.

    ``null`` may be supplied to reuse a distribution already computed for the
    same reference; it depends only on the reference, never on the submission.
    """
    n_modes = own.shape[1]
    correlations = canonical_correlations(own, reference)
    observed = float(np.sqrt((correlations ** 2).sum() / n_modes))
    if null is None:
        null = anm_null_distribution(coords, reference, cutoffs, n_modes)
    exceed = int((null >= observed).sum())
    random_null, _ = null_distribution(own.shape[0], n_modes, draws=2000)
    return {
        "test_id": TEST_ID,
        "contract_id": CONTRACT_ID,
        "rmsip": observed,
        "canonical_correlations": [float(c) for c in correlations],
        "null_mean": float(null.mean()),
        "null_sd": float(null.std()),
        "null_max": float(null.max()),
        "null_cutoffs": [float(c) for c in cutoffs],
        "z_score": float((observed - null.mean()) / null.std()),
        "p_value_upper_bound": float((exceed + 1) / (len(null) + 1)),
        "h0_rejected": bool(observed > null.max()),
        "context_random_null_mean": float(random_null.mean()),
        "context_random_null_z": float((observed - random_null.mean()) / random_null.std()),
    }


def test_unrelated(u: np.ndarray, v: np.ndarray, alpha: float = DEFAULT_ALPHA,
                   draws: int = DEFAULT_NULL_DRAWS) -> dict:
    """Test H0 = the two subspaces are unrelated.  Reject -> the run is valid."""
    dim, n_modes = u.shape
    correlations = canonical_correlations(u, v)
    observed = float(np.sqrt((correlations ** 2).sum() / n_modes))
    stats, ordered = null_distribution(dim, n_modes, draws)
    threshold = float(np.quantile(stats, 1.0 - alpha))
    # No null draw reaches the observed value for a related pair, so the
    # p-value is reported as an upper bound set by the Monte Carlo resolution.
    exceed = int((stats >= observed).sum())
    p_value = (exceed + 1) / (draws + 1)
    per_mode_cut = np.quantile(ordered, 0.99, axis=0)
    return {
        "test_id": TEST_ID,
        "contract_id": CONTRACT_ID,
        "n_modes": n_modes,
        "dimension": dim,
        "rmsip": observed,
        "canonical_correlations": [float(c) for c in correlations],
        "null_mean": float(stats.mean()),
        "null_sd": float(stats.std()),
        "null_analytic_mean": float(np.sqrt(n_modes / dim)),
        "reject_threshold": threshold,
        "alpha": alpha,
        "z_score": float((observed - stats.mean()) / stats.std()),
        "p_value_upper_bound": float(p_value),
        "modes_above_null_99": int((correlations > per_mode_cut).sum()),
        "h0_rejected": bool(observed > threshold),
    }
