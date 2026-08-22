"""Which reference topology a bundle carries, and how it is addressed.

Not marked slow: these exercise path and node bookkeeping only, and import
neither parmed nor openmm.  They exist because both facts were wrong until
2026-08-23 and each failed silently rather than loudly.

MDDB is eight federated nodes.  ``mddatabench`` fetched from one of them,
``mmb.mddbr.eu``, which turns out to be a subset of the registered mmb node
(4554 projects of 9062), and read only ``reference.prmtop``.  Nodes deposit
different formats -- Amber prmtop on mmb, cin and rpbs, GROMACS tpr on bsc, oxf
and inr, CHARMM psf on part of inr -- so a prmtop-only reader leaves every
ATLAS, membrane and DynaRepo task unscorable on the prep side.
"""

from __future__ import annotations

import pytest

from mddatabench import reference as rf
from mddatabench import topology as tp


def test_find_reference_topology_accepts_every_node_format(tmp_path):
    for suffix in tp.REFERENCE_TOPOLOGIES:
        bundle = tmp_path / suffix.lstrip(".")
        bundle.mkdir()
        (bundle / f"reference{suffix}").write_bytes(b"")
        assert tp.find_reference_topology(bundle).suffix == suffix


def test_a_bundle_without_a_topology_is_refused_not_skipped(tmp_path):
    """Scoring without the reference topology would report agreement that was
    never checked, so this raises rather than returning None."""
    (tmp_path / "reference.pdb").write_text("END\n")
    with pytest.raises(SystemExit):
        tp.find_reference_topology(tmp_path)


def test_an_unknown_topology_format_is_refused(tmp_path):
    path = tmp_path / "reference.xyz"
    path.write_text("")
    with pytest.raises(SystemExit):
        tp.read_topology(path)


# --- node and replica addressing --------------------------------------------

def test_every_registered_node_has_an_api():
    """The registry the global API serves, as of 2026-08-23."""
    assert set(rf.NODES) >= {"mmb", "oxf", "cin", "bsc", "inr", "jsc", "rpbs", "ufl"}
    assert all(u.startswith("https://") and u.endswith("/projects")
               for u in rf.NODES.values())


def test_the_default_node_is_the_registered_one_not_the_subset():
    """mmb.mddbr.eu serves 4554 of the mmb node's 9062 projects; the nanobody
    and membrane collections are only in the difference."""
    assert rf.API == rf.NODES["mmb"] == "https://irb-dev.mddbr.eu/api/rest/v1/projects"


@pytest.mark.parametrize("replica, expected", [
    (None, "A02K9"), (1, "A02K9"), (2, "A02K9.2"), (3, "A02K9.3"),
])
def test_replica_is_addressed_by_accession_suffix(replica, expected):
    assert rf.replica_id("A02K9", replica) == expected


def test_an_unknown_node_is_refused(tmp_path):
    with pytest.raises(SystemExit):
        rf.fetch_reference("A0001", str(tmp_path), node="nowhere")


# --- the bond list is what every bonded prep expectation is read from --------
# Reviewed 2026-08-23: load_reference checked atom count and atom-name order
# against the PDB but never the bonds, so a reader that dropped them would
# shrink the reference's expected disulfide set in silence and a submission
# missing a disulfide would score as agreement.

def test_a_polymer_topology_with_no_bonds_is_refused(tmp_path, monkeypatch):
    import types

    from mddatabench import topology as tp

    class Residue:
        name = "ALA"

    class Atom:
        def __init__(self, name):
            self.name = name

    empty = types.SimpleNamespace(atoms=[Atom("N"), Atom("CA")],
                                  residues=[Residue()], bonds=[],
                                  coordinates=None)
    monkeypatch.setattr(tp, "read_topology", lambda path: empty)
    monkeypatch.setattr("parmed.load_file",
                        lambda path: types.SimpleNamespace(
                            atoms=[Atom("N"), Atom("CA")], coordinates=[[0, 0, 0]] * 2))
    with pytest.raises(SystemExit) as raised:
        tp.load_reference(tmp_path / "reference.tpr", tmp_path / "reference.pdb")
    assert "bond" in str(raised.value)


def test_no_frames_means_no_frame_selector(monkeypatch, tmp_path):
    """n_frames defaults to zero because nothing reads the frames any more.
    The selector was still being computed, and computing it divided by zero."""
    project = {"metadata": {"SYSTATS": 100, "LICENSE": "cc"}, "files": ["topology.prmtop"],
               "totalFrames": 1000, "mdcount": 1}
    monkeypatch.setattr(rf, "get_json", lambda url, **kw:
                        {"data": {"atoms": [], "eigenvalues": []}} if "analyses/pca" in url
                        else project)
    monkeypatch.setattr(rf, "download", lambda url, destination: (
        destination.write_text("{}"), destination)[1])
    provenance = rf.fetch_reference("A0001", str(tmp_path), node="mmb")
    assert provenance["n_frames"] == 0
    assert provenance["frame_selector"] is None
