"""How the md bands are measured, and the two faults that measurement had.

Not marked slow: the pieces tested here are arithmetic and URL construction,
which is where both defects lived.  The network path is exercised by
``calibrate_benchmark_task`` against a real project, not here.

Both faults produced a band that was too narrow, and a too-narrow band rejects
correct submissions:

1. Windows were taken from one trajectory.  A submission is an independent run,
   so the spread that matters is between runs, not inside one.  Measured on
   ATLAS 16pk_A, the radius of gyration's pooled standard deviation is 1.74x the
   within-replica one.
2. The false-rejection rate was estimated by block cross-validation inside that
   same trajectory, which answers a different question.  Held out properly --
   calibrate on replicas 1 and 2, score every window of replica 3 -- 30 per cent
   of that replica's windows fall outside the unwidened band, and none outside
   the band widened by the measured two window standard deviations.
"""

from __future__ import annotations

import numpy as np
import pytest

from mddatabench import calibration as cb


# --- the atom selector MDDB's trajectory endpoint takes ----------------------
# Contract atoms are a few thousand indices; sending them one by one overruns
# the URL, so runs are collapsed into ranges.

@pytest.mark.parametrize("indices, expected", [
    ([0], "1"),
    ([0, 1, 2], "1-3"),
    ([0, 1, 2, 9, 10], "1-3,10-11"),
    ([5, 3, 4], "4-6"),                      # unsorted input still collapses
    ([0, 2, 4], "1,3,5"),                    # no run to collapse
])
def test_atom_selector_collapses_runs_and_is_one_based(indices, expected):
    assert cb.atom_selector(indices) == expected


def test_an_empty_selection_is_empty_not_a_whole_trajectory():
    """A selector of "" would ask MDDB for every atom; returning it deliberately
    rather than by accident is the point."""
    assert cb.atom_selector([]) == ""


# --- the bands themselves ----------------------------------------------------

def rows(values):
    return [{k: v for k in cb.KEYS} for v in values]


def test_the_band_is_the_range_and_the_spread_is_the_sample_sd():
    band, spread = cb._bands(rows([1.0, 2.0, 3.0]))
    for key in cb.KEYS:
        assert band[key] == [1.0, 3.0]
        assert spread[key] == pytest.approx(1.0)


def test_one_window_has_no_spread_rather_than_a_nan():
    _, spread = cb._bands(rows([2.0]))
    assert all(spread[key] == 0.0 for key in cb.KEYS)


def test_slack_is_what_takes_the_held_out_rejection_rate_to_zero():
    """The measured case in miniature: windows outside the calibration range are
    rejected without slack and admitted with it."""
    band, spread = cb._bands(rows([1.0, 2.0, 3.0]))
    outside = rows([3.5])
    assert cb._rejected(outside, band, spread, 0.0) == 1.0
    assert cb._rejected(outside, band, spread, 2.0) == 0.0


def test_the_rank_correlation_is_judged_on_one_side_only():
    """Agreeing better than any calibration window is not a complaint, so a
    high outlier must not be rejected while a low one is."""
    band, spread = cb._bands(rows([0.80, 0.85, 0.90]))
    high = [{"rank_correlation": 0.99, "total_fluctuation_angstrom": 0.85,
             "radius_of_gyration_angstrom": 0.85}]
    low = [{"rank_correlation": 0.10, "total_fluctuation_angstrom": 0.85,
            "radius_of_gyration_angstrom": 0.85}]
    assert cb._rejected(high, band, spread, 0.0) == 0.0
    assert cb._rejected(low, band, spread, 0.0) == 1.0


def test_no_windows_gives_no_rate_rather_than_zero():
    band, spread = cb._bands(rows([1.0, 2.0]))
    assert cb._rejected([], band, spread, 2.0) is None


# --- window statistics -------------------------------------------------------

def test_window_statistics_reports_all_three_banded_quantities():
    rng = np.random.default_rng(0)
    xyz = rng.normal(0, 1, size=(30, 12, 3)) + np.arange(12)[None, :, None]
    stats = cb.window_statistics(xyz, np.linspace(0.5, 2.0, 12))
    assert set(stats) == set(cb.KEYS)
    assert all(np.isfinite(v) for v in stats.values())


def test_a_window_with_no_rankable_profile_is_refused_not_turned_into_nan():
    """A constant reference profile has no ranks, so Spearman is undefined. A
    NaN band would admit every submission, so the calibration stops instead."""
    rng = np.random.default_rng(0)
    xyz = rng.normal(0, 1, size=(30, 12, 3))
    stats = cb.window_statistics(xyz, np.ones(12))
    assert stats["rank_correlation"] is None
    with pytest.raises(SystemExit):
        cb._bands([stats, stats])


# --- review findings, 2026-08-23 ---------------------------------------------
# Each of these was a real defect the reviewer pointed at, and each one made the
# band wrong in the direction the module exists to correct.

def test_duplicate_indices_cannot_desync_the_payload():
    """A repeated index would ask for the atom twice while len(indices) counts
    it once, and the reshape would then be against the wrong atom count."""
    assert cb.atom_selector([0, 0, 1]) == "1-2"


def test_a_negative_index_is_refused_rather_than_sent():
    with pytest.raises(SystemExit):
        cb.atom_selector([-1, 2, 3])


def test_a_scattered_selection_outgrows_any_request_line():
    """Collapsing runs only helps a contiguous selection. 16pk_A's 1245 contract
    atoms already need 6020 characters, which is why window_frames falls back to
    fetching the whole frame and slicing rather than failing."""
    scattered = list(range(0, 40000, 2))
    assert len(cb.atom_selector(scattered)) > cb.MAX_SELECTOR_CHARS


def test_the_fallback_needs_the_atom_count_and_says_so(monkeypatch):
    scattered = list(range(0, 40000, 2))
    with pytest.raises(SystemExit) as raised:
        cb.window_frames("http://x", "A0001", scattered, 1, 10)
    assert "atom count" in str(raised.value)


def test_a_nan_statistic_is_refused_because_a_nan_band_admits_everything():
    """min/max propagate a NaN and every comparison against it is False, so the
    band would pass every submission. _bands guarded None but not NaN."""
    good = {k: 1.0 for k in cb.KEYS}
    bad = dict(good, radius_of_gyration_angstrom=float("nan"))
    with pytest.raises(SystemExit):
        cb._bands([good, bad])


def test_window_starts_span_the_replica_rather_than_its_head():
    """Taking the first N of a head-to-tail enumeration put every calibration
    window in the first third of the trajectory, leaving out where slow drift
    and late relaxation live."""
    starts = cb.window_starts(frames=10001, count=100, wanted=10)
    assert starts[0] == 1
    assert starts[-1] == 10001 - 100 + 1
    assert len(starts) == 10


def test_window_starts_never_runs_past_the_end():
    for frames in (100, 101, 150, 1000):
        for start in cb.window_starts(frames, count=100, wanted=5):
            assert start + 100 - 1 <= frames


def test_a_replica_too_short_for_one_window_yields_no_starts():
    assert cb.window_starts(frames=50, count=100, wanted=5) == []
