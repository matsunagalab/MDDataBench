"""A broken submission must be reported, not crash the scorer.

Until 2026-08-21 the scorer deserialised the submitted ``system.xml`` at module
flow level with no guard, so a truncated file, an empty System, or a System
carrying no ``NonbondedForce`` each raised out of the run.  The condition that
was supposed to catch them -- particle count above zero -- could therefore only
be reached when it was already true.

Marked slow because it needs OpenMM, which the fast CI job does not install.
"""

from __future__ import annotations

import pytest

pytestmark = pytest.mark.slow
mm = pytest.importorskip("openmm")

from mddatabench.scoring import (  # noqa: E402
    GLOBAL_REPLICA_FLUCTUATION_FACTOR,
    _load_system,
    last_complete_window_slice,
    widened_calibration_band,
)


def serialise(system):
    return mm.XmlSerializer.serialize(system)


def write(tmp_path, name, text):
    path = tmp_path / name
    path.write_text(text)
    return path


def test_fluctuation_magnitude_has_more_room_below_than_above():
    assert widened_calibration_band(
        [1.0, 2.0], "total_fluctuation_angstrom", 4.0, 0.1
    ) == pytest.approx([
        0.5 / GLOBAL_REPLICA_FLUCTUATION_FACTOR,
        2.4 * GLOBAL_REPLICA_FLUCTUATION_FACTOR,
    ])


def test_last_complete_one_ns_block_is_trailing_and_deterministic():
    block, detail = last_complete_window_slice(253, 10.0, 1.0)

    assert block == slice(153, 253)
    assert "frames 154--253 of 253" in detail


def test_a_trajectory_shorter_than_one_block_has_no_analysis_window():
    block, detail = last_complete_window_slice(99, 10.0, 1.0)

    assert block is None
    assert "fewer than the 100 needed" in detail


def test_other_measured_bands_remain_symmetric():
    """Only RMSF magnitude widens asymmetrically; the rest move equally.

    The radius-of-gyration band also carries a flat tolerance on each side
    (``RADIUS_OF_GYRATION_TOLERANCE_ANGSTROM``), added because the band is
    measured within one reference trajectory and applied to an independent run.
    That tolerance must stay symmetric, which is what this guards.
    """
    from mddatabench.scoring import RADIUS_OF_GYRATION_TOLERANCE_ANGSTROM as tol
    low, high = widened_calibration_band(
        [1.0, 2.0], "radius_of_gyration_angstrom", 4.0, 0.1)
    assert [low, high] == pytest.approx([0.6 - tol, 2.4 + tol])
    assert (1.0 - low) == pytest.approx(high - 2.0)


def test_a_valid_system_loads(tmp_path):
    system = mm.System()
    system.addParticle(1.0)
    loaded, error = _load_system(write(tmp_path, "ok.xml", serialise(system)))
    assert error is None
    assert loaded.getNumParticles() == 1


def test_a_system_already_parsed_is_validated_without_re_reading(tmp_path):
    """The reuse path exists to skip a second parse of up to 84 MB.

    ``load_submission`` deserialises the System, and passing it here saves 2.42 s
    of a01-1ahw's 73.8 s. The branch has to validate the object it was handed and
    must not fall back to the file, so the file is written as junk: if the reuse
    path were skipped the parse would fail and this would report an error.
    """
    system = mm.System()
    for _ in range(3):
        system.addParticle(1.0)
    path = write(tmp_path, "unreadable.xml", "this is not xml at all")
    loaded, error = _load_system(path, system=system)
    assert error is None
    assert loaded is system
    assert loaded.getNumParticles() == 3


def test_a_system_that_was_not_parsed_still_falls_back_to_the_file(tmp_path):
    """A valid System behind an unreadable topology PDB is still graded.

    ``load_submission`` returns nothing when the topology PDB cannot be read, so
    the force-field axis would go ungraded if this branch did not re-read the
    file itself. That independence is the repo's first invariant.
    """
    system = mm.System()
    system.addParticle(1.0)
    loaded, error = _load_system(write(tmp_path, "ok.xml", serialise(system)), system=None)
    assert error is None
    assert loaded.getNumParticles() == 1


def test_a_truncated_file_is_reported(tmp_path):
    system = mm.System()
    for _ in range(4):
        system.addParticle(1.0)
    text = serialise(system)
    loaded, error = _load_system(write(tmp_path, "cut.xml", text[: len(text) // 2]))
    assert loaded is None
    assert "did not deserialise" in error


def test_a_system_with_no_particles_is_reported(tmp_path):
    loaded, error = _load_system(write(tmp_path, "empty.xml", serialise(mm.System())))
    assert loaded is None
    assert "no particles" in error


def test_a_non_system_object_is_reported(tmp_path):
    integrator = mm.VerletIntegrator(1.0)
    loaded, error = _load_system(write(tmp_path, "wrong.xml", serialise(integrator)))
    assert loaded is None
    assert "not a System" in error


def test_unreadable_input_is_reported_not_raised(tmp_path):
    loaded, error = _load_system(write(tmp_path, "junk.xml", "this is not xml at all"))
    assert loaded is None and error
