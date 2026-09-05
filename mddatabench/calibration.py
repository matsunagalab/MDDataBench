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
import time
import urllib.request

import numpy as np

from mddatabench import dynamics as dy
from mddatabench.reference import NODES, replica_id

# Frames an estimator wants inside one window, and the fewest it will accept.
# Below about the floor a per-atom RMSF is dominated by its own sampling noise:
# the band widens until it admits everything and the check stops deciding.
# The target is what the window is subsampled down to when the reference is
# written more finely; the floor is what the task cast was selected on, and
# DynaRepo sits exactly there -- 100 ps frames, so a 2.5 ns window holds 25.
# Whether 25 is enough is not asserted here: the held-out rejection rate is
# recorded per task and says so.
FRAMES_PER_WINDOW = 100
MINIMUM_FRAMES = 25

# Windows wanted in total, across every replica.  The band is a range, and a
# range over few windows underestimates the population it is standing for.
TARGET_WINDOWS = 100

# Longest ``atoms=`` selector to put in a URL.  Servers and proxies commonly cut
# the request line off at 8 KB; the rest of the URL is about 120 characters.
# Measured: 16pk_A's 1245 contract atoms need 6020 characters, so the limit has
# to sit above that, and a larger contract will exceed any limit -- which is
# what the whole-frame fallback below is for.
MAX_SELECTOR_CHARS = 7000

# Attempts per window request.
RETRIES = 4


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
    ordered = np.asarray(indices, dtype=int)
    if ordered.min() < 0:
        raise SystemExit(f"atom index {int(ordered.min())} is negative")
    ordered = np.unique(ordered)          # duplicates would desync the payload
    breaks = np.flatnonzero(np.diff(ordered) != 1)
    starts = np.concatenate(([0], breaks + 1))
    stops = np.concatenate((breaks, [len(ordered) - 1]))
    selector = ",".join(f"{ordered[a] + 1}-{ordered[b] + 1}" if a != b else f"{ordered[a] + 1}"
                        for a, b in zip(starts, stops))
    # Collapsing runs only helps when the selection is mostly contiguous. A
    # scattered one degenerates to a term per atom, and the request then fails
    # as an opaque HTTP error deep inside the loop rather than here.
    return selector


def window_stride(count, wanted=FRAMES_PER_WINDOW):
    """Take every nth frame of a window, so its length sets the cost, not its
    sampling.

    A 1 ns window of a reference written every 1 ps is a thousand frames where a
    hundred is enough to estimate an RMSF -- 18 MB against 1.8 MB, per window,
    a hundred times over. The estimator sees the same nanosecond either way.
    """
    return max(1, count // max(wanted, 1))


def window_frames(base, target, indices, start, count, n_atoms=None, stride=1):
    """One window of the reference trajectory, as (frames, atoms, 3) in Angstrom.

    MDDB serves raw little-endian float32 xyz with no header, so the shape has
    to be imposed here; a wrong atom count would reshape silently into garbage,
    which is why it is checked.

    Collapsing the selection into ranges only helps when the contract atoms are
    mostly contiguous.  16pk_A's 1245 of them already need 6020 characters, and
    a larger or more scattered contract exceeds any request-line limit, so past
    ``MAX_SELECTOR_CHARS`` the whole frame is fetched and sliced here instead.
    That costs bytes and always works; failing would leave the task
    uncalibratable.
    """
    selector = atom_selector(indices)
    whole = len(selector) > MAX_SELECTOR_CHARS
    if whole and not n_atoms:
        raise SystemExit(
            f"{target}: the atom selector needs {len(selector)} characters and the "
            "whole-frame fallback needs the system's atom count")
    # ``frames=a:b:c`` is 1-based and inclusive at both ends -- measured:
    # ``1:11:1`` returns 11 frames, ``10001:10002:1`` on a 10001-frame replica
    # is a 502, and ``9902:10002:1`` returns a truncated body rather than an
    # error. So the stop is start + count - 1, and the last usable start is
    # frames - count + 1.
    url = f"{base}/{target}/trajectory?frames={start}:{start + count - 1}:{stride}"
    if not whole:
        url += f"&atoms={selector}"
    # A calibration is a hundred requests of a few megabytes each. Letting one
    # dropped connection out of here aborts the whole measurement -- which it
    # did, on an IncompleteRead 818520 bytes into a 1.5 MB window.
    raw = None
    for attempt in range(RETRIES):
        try:
            with urllib.request.urlopen(url, timeout=600) as response:
                raw = response.read()
            break
        except Exception as exc:                                    # noqa: BLE001
            if attempt == RETRIES - 1:
                raise SystemExit(
                    f"{target}: window at {start} could not be fetched after "
                    f"{RETRIES} attempts: {type(exc).__name__}: {exc}") from exc
            time.sleep(2 ** attempt)
    values = np.frombuffer(raw, dtype="<f4")
    width = n_atoms if whole else len(indices)
    per_frame = width * 3
    if per_frame == 0 or values.size % per_frame:
        raise SystemExit(
            f"{target}: window at {start} returned {values.size} floats, which is "
            f"not a multiple of {per_frame} for {width} atoms")
    xyz = values.reshape(-1, width, 3).astype(np.float64)
    if whole:
        xyz = xyz[:, np.asarray(indices, dtype=int), :]
    # The modulo check above validates the shape and nothing else. A payload of
    # NaNs reshapes just as cleanly, and a NaN reaches the band as a NaN rather
    # than as a None -- ``min``/``max`` propagate it and every comparison against
    # it is False, so the band would admit every submission.
    if not np.isfinite(xyz).all():
        raise SystemExit(f"{target}: window at {start} contains non-finite coordinates")
    return xyz


def replica_frames(base, target):
    """Frames in one replica.

    ``totalFrames`` is the same project-wide number at every replica address --
    measured on ATLAS 16pk_A, ``A02K9``, ``.1``, ``.2`` and ``.3`` all report
    30003 for three replicas of 10001 -- so it has to be divided.  ``mdFrames``
    is the per-replica count and is preferred when present.  The last resort is
    an analysis series, which is decimated: the same project's ``rmsds`` is 3334
    long with ``step`` 3, so the length alone underestimates by threefold.
    """
    project = _get(f"{base}/{target}")
    metadata = project.get("metadata") or {}
    if metadata.get("mdFrames"):
        return int(metadata["mdFrames"])
    total = project.get("totalFrames")
    if total:
        return int(total) // max(int(project.get("mdcount") or 1), 1)
    series = _get(f"{base}/{target}/analyses/rmsds")
    step = int(series.get("step") or 1)
    for entry in (series.get("data") or []):
        if entry.get("values"):
            return len(entry["values"]) * step
    raise SystemExit(f"{target}: cannot determine how many frames it has")


def window_starts(frames, count, wanted):
    """Window starts spread over the whole replica, not clustered at its head.

    Taking the first ``wanted`` of a head-to-tail enumeration put every
    calibration window in the first third of the trajectory, which leaves out
    exactly where slow drift and late relaxation live -- the same too-narrow
    band the pooling was introduced to fix, arriving from the sampling side.
    """
    last = frames - count + 1
    if last < 1:
        return []
    if wanted <= 1:
        return [1]
    return sorted({int(round(x)) for x in np.linspace(1, last, min(wanted, last))})


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
        missing = sum(1 for row in rows
                      if row.get(key) is None or not np.isfinite(row[key]))
        if missing:
            raise SystemExit(
                f"{missing} of {len(rows)} calibration windows have no finite {key}; "
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
    stride = window_stride(count, frames_per_window)
    if count < MINIMUM_FRAMES:
        raise SystemExit(
            f"{accession}: a {window_ns:g} ns window holds {count} frames at "
            f"{step_ns * 1000:g} ps; {MINIMUM_FRAMES} are the fewest an RMSF can be "
            "estimated from")

    indices = np.asarray(json.loads(
        (bundle / "pca_atom_indices.json").read_text())["atom_indices"], dtype=int)
    full_profile = np.asarray(json.loads(
        (bundle / "reference_fluctuation.json").read_text())["y"]["rmsf"]["data"],
        dtype=float)
    n_atoms = len(full_profile)          # one entry per atom of the whole system
    profile = full_profile[indices] * 10.0

    replicas = int(project.get("mdcount") or 1)
    per_replica, frames_per = {}, {}
    for replica in range(1, replicas + 1):
        target = replica_id(accession, replica)
        frames = replica_frames(base, target)
        frames_per[str(replica)] = frames
        wanted = max(1, -(-target_windows // replicas))
        for start in window_starts(frames, count, wanted):
            xyz = window_frames(base, target, indices, start, count,
                                n_atoms=n_atoms, stride=stride)
            if xyz.shape[0] < MINIMUM_FRAMES:
                continue
            per_replica.setdefault(replica, []).append(window_statistics(xyz, profile))
        per_replica.setdefault(replica, [])

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
    # every window of it.  Every fold is already in memory, so leave-one-out over
    # all of them costs nothing and one draw would be one draw.
    folds = []
    for held in sorted(per_replica):
        if not per_replica[held]:
            continue
        kept = [row for r, rows in per_replica.items() if r != held for row in rows]
        if len(kept) < 10:
            continue
        kb, ks = _bands(kept)
        folds.append({
            "replica": held,
            "windows": len(per_replica[held]),
            "calibrated_on_replicas": sorted(r for r in per_replica if r != held),
            "rejected_fraction": _rejected(per_replica[held], kb, ks, slack_window_sd),
            "rejected_fraction_without_slack": _rejected(per_replica[held], kb, ks, 0.0),
        })
    # What the held-out folds would reject at a range of slacks, so the value
    # can be chosen from the cast rather than from three tasks.
    sweep = {}
    for slack in (0.0, 1.0, 2.0, 3.0, 4.0, 5.0, 6.0, 8.0, 10.0):
        rates = []
        for held in sorted(per_replica):
            if not per_replica[held]:
                continue
            kept = [row for r, rows in per_replica.items() if r != held for row in rows]
            if len(kept) < 10:
                continue
            kb, ks = _bands(kept)
            rates.append(_rejected(per_replica[held], kb, ks, slack))
        if rates:
            sweep[f"{slack:g}"] = max(rates)
    held_out = None
    if folds:
        held_out = {
            "folds": folds,
            "rejected_fraction": max(f["rejected_fraction"] for f in folds),
            "rejected_fraction_without_slack":
                max(f["rejected_fraction_without_slack"] for f in folds),
            # With two replicas each fold calibrates on a single one, which is
            # the within-replica band this module exists to widen. The number
            # then describes the old fault, not the band that ships.
            "slack_sweep": sweep,
            "note": ("each fold calibrates on one replica only, so this measures the "
                     "within-replica band rather than the pooled one"
                     if replicas == 2 else
                     f"leave-one-out over {len(folds)} replica(s)"),
        }

    out = {
        # The windows themselves, so the band can be re-derived and the slack
        # swept without fetching a coordinate again. Thirty rows of three
        # numbers is nothing next to what measuring them cost.
        "window_statistics": {str(replica): rows for replica, rows in per_replica.items()},
        "windows": len(pooled),
        "window_ns": window_ns,
        "frames_per_window": len(range(0, count, stride)),
        "window_frame_stride": stride,
        "replicas_used": sorted(per_replica),
        "windows_per_replica": {str(k): len(v) for k, v in per_replica.items()},
        "frames_per_replica": frames_per,
        "window_definition": (
            f"potentially overlapping {window_ns:g} ns windows "
            f"with starts spread across each replica, "
            f"{len(range(0, count, stride))} frames at {step_ns * stride * 1000:g} ps, "
            f"contract atoms only, pooled across "
            f"{len(per_replica)} replica(s)"),
        "window_fetch": ("GET {api}/{accession}[.replica]/trajectory"
                         "?frames=<start>:<start+frames-1>:1"
                         "&atoms=<contract ranges, 1-based>; both ends inclusive"),
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
        out["held_out"] = held_out
    return out
