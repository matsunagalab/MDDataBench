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

from mddatabench.scoring import _load_system  # noqa: E402


def serialise(system):
    return mm.XmlSerializer.serialize(system)


def write(tmp_path, name, text):
    path = tmp_path / name
    path.write_text(text)
    return path


def test_a_valid_system_loads(tmp_path):
    system = mm.System()
    system.addParticle(1.0)
    loaded, error = _load_system(write(tmp_path, "ok.xml", serialise(system)))
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
