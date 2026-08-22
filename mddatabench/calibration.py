"""Measure the band each md check is scored against, from the reference itself.

Three of the md checks compare a submission's window statistics against the
range the reference's own windows span.  That range has to be measured, not
chosen, and this module is what measures it.

Two things about the measurement were wrong until 2026-08-23.

**It read one trajectory.**  A submission is an independent run: same system,
same conditions, different velocities.  Windows taken inside a single reference
trajectory share that trajectory's particular history, so their spread is
narrower than the spread between independent runs.  Measured on 20 ATLAS
systems, pooling windows across the three replicas gives a standard deviation
1.21x the within-replica one at the median and 1.82x at the worst.  A band built
from one trajectory is therefore about a fifth too narrow, which shows up as
correct submissions being rejected.  Where a project has replicas -- 53 per cent
of eligible projects do, and MDDB addresses them as ``ACCESSION.N`` -- the
windows are pooled across all of them.

**Its false-rejection rate was estimated inside the same trajectory.**  Block
cross-validation over one run's windows answers "would another window of this
run pass", not "would another run pass".  With replicas the honest test is
available: calibrate on all but one replica, then score every window of the
held-out replica.  That rate is recorded in the contract next to the band.

The window length is per task.  Most references are sampled at 10 ps and use
1 ns windows; DynaRepo's are sampled at 100 ps and need 2.5 ns for the same
number of frames per window.  What is fixed is the number of frames the
estimator sees, not the nanoseconds.
"""

from __future__ import annotations

from mddatabench import _threads  # noqa: F401  must precede numpy

import json
import urllib.request

import numpy as np

from mddatabench import dynamics as dy
from mddatabench.reference import NODES, replica_id

# Frames an estimator needs inside one window.  Below about this many, a
# per-atom RMSF is dominated by its own sampling noise: the band widens until it
# admits everything and the check stops deciding anything.
FRAMES_PER_WINDOW = 100

# Windows wanted in total, across every replica.  The band is a range, and a
# range over few windows underestimates the population it is standing for.
TARGET_WINDOWS = 100


def _get(url, timeout=180):
    with urllib.request.urlopen(url, timeout=timeout) as response:
        return json.load(response)


def atom_selector(indices):
    """MDDB's ``atoms=`` selector for a set of 0-based atom indices.

    The endpoint takes 1-based inclusive ranges, comma separated.  Collapsing
    runs matters: the contract atom list of a 300-residue protein is a few
    thousand indices and the URL has a length limit.
    """
    if len(indices) == 0:
        return ""
    ordered = np.sort(np.asarray(indices, dtype=int))
    breaks = np.flatnonzero(np.diff(ordered) != 1)
    starts = np.concatenate(([0], breaks + 1))
    stops = np.concatenate((breaks, [len(ordered) - 1]))
    return ",".join(f"{ordered[a] + 1}-{ordered[b] + 1}" if a != b else f"{ordered[a] + 1}"
                    for a, b in zip(starts, stops))


def window_frames(base, target, indices, start, count):
    """One window of the reference trajectory, as (frames, atoms, 3) in Angstrom.

    MDDB serves raw little-endian float32 xyz with no header, so the shape has
    to be imposed here; a wrong atom count would reshape silently into garbage,
    which is why it is checked.
    """
    url = (f"{base}/{target}/trajectory?frames={start}:{start + count}:1"
           f"&atoms={atom_selector(indices)}")
    with urllib.request.urlopen(url, timeout=600) as response:
        raw = response.read()
    values = np.frombuffer(raw, dtype="<f4")
    per_frame = len(indices) * 3
    if per_frame == 0 or values.size % per_frame:
        raise SystemExit(
            f"{target}: window at {start} returned {values.size} floats, which is "
            f"not a multiple of {per_frame} for {len(indices)} atoms")
    return values.reshape(-1, len(indices), 3).astype(np.float64)


def window_statistics(xyz, reference_profile):
    """The three quantities the md checks band, for one window.

    ``profile_agreement`` answers None when a profile has no variance to rank --
    a frozen window, or a reference profile that is constant.  Returning None
    here rather than casting it keeps the failure visible: ``_bands`` refuses a
    calibration set containing one instead of turning it into a NaN band that
    admits everything.
    """
    agreement = dy.profile_agreement(dy.atom_fluctuations(xyz), reference_profile)
    return {
        "rank_correlation": None if agreement is None else float(agreement),
        "total_fluctuation_angstrom": float(dy.total_fluctuation(xyz)),
        "radius_of_gyration_angstrom": float(dy.radius_of_gyration(xyz).mean()),
    }


KEYS = ("rank_correlation", "total_fluctuation_angstrom", "radius_of_gyration_angstrom")


def _bands(rows):
    """Range and spread of each statistic over a set of windows."""
    band, spread = {}, {}
    for key in KEYS:
        missing = sum(1 for row in rows if row.get(key) is None)
        if missing:
            raise SystemExit(
                f"{missing} of {len(rows)} calibration windows have no {key}; "
                "a band built from the rest would stand for a different set")
        values = np.array([row[key] for row in rows], dtype=float)
        band[key] = [float(values.min()), float(values.max())]
        spread[key] = float(values.std(ddof=1)) if values.size > 1 else 0.0
    return band, spread


def _rejected(rows, band, spread, slack):
    """Fraction of these windows that the band, widened by the slack, refuses.

    One-sided for the rank correlation, matching the check: a profile that
    agrees better than any calibration window is not a complaint.
    """
    if not rows:
        return None
    out = 0
    for row in rows:
        for key in KEYS:
            low, high = band[key]
            margin = slack * spread[key]
            if key == "rank_correlation":
                if row[key] < low - margin:
                    out += 1
                    break
            elif not (low - margin <= row[key] <= high + margin):
                out += 1
                break
    return out / len(rows)


def calibrate(accession, bundle, node="mmb", window_ns=None, slack_window_sd=2.0,
              target_windows=TARGET_WINDOWS, frames_per_window=FRAMES_PER_WINDOW):
    """Measure the md bands for one project, pooling windows across its replicas.

    ``bundle`` supplies the contract atom indices and the reference fluctuation
    profile, both already fetched by ``fetch_reference``.  Returns the
    ``md_calibration`` block a task contract carries.
    """
    from pathlib import Path
    bundle = Path(bundle)
    base = NODES[node]
    project = _get(f"{base}/{accession}")
    metadata = project.get("metadata") or {}
    step_ns = float(metadata.get("FRAMESTEP") or 0)
    if not step_ns:
        raise SystemExit(f"{accession}: no FRAMESTEP, so a window has no length")
    if window_ns is None:
        window_ns = frames_per_window * step_ns
    count = int(round(window_ns / step_ns))
    if count < frames_per_window:
        raise SystemExit(
            f"{accession}: a {window_ns} ns window holds {count} frames at "
            f"{step_ns * 1000:g} ps; {frames_per_window} are needed")

    indices = np.asarray(json.loads(
        (bundle / "pca_atom_indices.json").read_text())["atom_indices"], dtype=int)
    profile = np.asarray(json.loads(
        (bundle / "reference_fluctuation.json").read_text())["y"]["rmsf"]["data"],
        dtype=float)[indices] * 10.0

    replicas = int(project.get("mdcount") or 1)
    per_replica, frames_each = {}, None
    for replica in range(1, replicas + 1):
        target = replica_id(accession, replica)
        total = _get(f"{base}/{target}")
        frames = total.get("totalFrames")
        frames = (int(frames) // replicas) if frames else None
        if frames is None:
            series = _get(f"{base}/{target}/analyses/rmsds").get("data") or []
            frames = next((len(e["values"]) for e in series if e.get("values")), 0)
        frames_each = frames
        wanted = max(1, -(-target_windows // replicas))
        starts = list(range(1, max(2, frames - count), count))[:wanted]
        rows = []
        for start in starts:
            xyz = window_frames(base, target, indices, start, count)
            if xyz.shape[0] < frames_per_window:
                continue
            rows.append(window_statistics(xyz, profile))
        per_replica[replica] = rows

    pooled = [row for rows in per_replica.values() for row in rows]
    if len(pooled) < 10:
        raise SystemExit(f"{accession}: only {len(pooled)} windows; the band would "
                         "stand for nothing")
    band, spread = _bands(pooled)

    # What a single trajectory would have claimed, kept so the correction this
    # module exists for is visible in the contract rather than only in the memo.
    within = {}
    if replicas > 1:
        first = per_replica.get(1) or []
        if len(first) > 1:
            _, within = _bands(first)

    # The honest false-rejection test: calibrate without one replica, then score
    # every window of it.
    held_out = None
    if replicas > 1 and all(per_replica.get(r) for r in per_replica):
        last = max(per_replica)
        kept = [row for r, rows in per_replica.items() if r != last for row in rows]
        if len(kept) >= 10:
            kb, ks = _bands(kept)
            held_out = {
                "replica": last,
                "windows": len(per_replica[last]),
                "rejected_fraction": _rejected(per_replica[last], kb, ks, slack_window_sd),
                "rejected_fraction_without_slack": _rejected(per_replica[last], kb, ks, 0.0),
            }

    out = {
        "windows": len(pooled),
        "window_ns": window_ns,
        "frames_per_window": count,
        "replicas_used": sorted(per_replica),
        "windows_per_replica": {str(k): len(v) for k, v in per_replica.items()},
        "frames_per_replica": frames_each,
        "window_definition": (
            f"non-overlapping {window_ns:g} ns windows, {count} frames at "
            f"{step_ns * 1000:g} ps, contract atoms only, pooled across "
            f"{len(per_replica)} replica(s)"),
        "window_fetch": ("GET {api}/{accession}[.replica]/trajectory"
                         "?frames=<start>:<start+frames>:1&atoms=<contract ranges, 1-based>"),
        "estimator": ("frames superposed on their own mean structure, a linear trend "
                      "in time removed per atom, then per-atom RMSF; the same "
                      "estimator is applied to the submission"),
        "observed_window_sd": spread,
        "slack_window_sd": slack_window_sd,
        **band,
    }
    if within:
        out["within_replica_window_sd"] = within
        out["pooled_over_within_sd_ratio"] = {
            key: (spread[key] / within[key]) if within.get(key) else None for key in KEYS}
    if held_out:
        out["held_out_replica"] = held_out
    return out
