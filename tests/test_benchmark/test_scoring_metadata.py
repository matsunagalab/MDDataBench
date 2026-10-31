"""Portable metadata faults cost their own check, not the whole score."""

from __future__ import annotations

import json
from types import SimpleNamespace

import numpy as np
import openmm as mm

from mddatabench import scoring as sc
from mddatabench._md_checks import MD_CHECKS
from mddatabench._prep_checks import PREP_CHECKS
from mddatabench.portable import PORTABLE_FILES, score_portable


class _Monomer:
    def __len__(self):
        return 1


class _Trajectory:
    xyz = np.zeros((2, 1, 3), dtype=float)
    n_frames = 2


def _task():
    return {
        "task_id": "portable-metadata",
        "scoring": {
            "deterministic_checks": [
                *(dict(check) for check in PREP_CHECKS),
                *(dict(check) for check in MD_CHECKS),
            ],
        },
        "reference": {
            "reference_conditions": {
                "WAT": "tip3p",
                "TEMP": 300.0,
                "ENSEMBLE": "NPT",
            },
            "md_calibration": {
                "windows": 10,
                "window_ns": 0.02,
                "slack_window_sd": {
                    "rank_correlation": 0.0,
                    "total_fluctuation_angstrom": 0.0,
                    "radius_of_gyration_angstrom": 0.0,
                },
                "observed_window_sd": {},
                "rank_correlation": [0.0, 1.0],
                "total_fluctuation_angstrom": [0.0, 2.0],
                "radius_of_gyration_angstrom": [0.0, 2.0],
            },
        },
    }


def _submission(root, amber_metadata):
    root.mkdir()
    for name in PORTABLE_FILES:
        path = root / name
        if name == "amber_metadata.json":
            path.write_text(json.dumps(amber_metadata))
        elif name == "production.json":
            path.write_text(json.dumps({
                "simulation_time_ns": 1.0,
                "temperature_kelvin": 300.0,
                "pressure_bar": 1.0,
                "timestep_fs": 2.0,
                "output_frequency_ps": 10.0,
                "system_signature": {"ensemble": "NPT", "pressure_bar": 1.0},
            }))
        else:
            path.write_text("END\n")
    return root


def _bundle(root, *, reference_profile=None, atom_indices=None):
    reference_profile = reference_profile or [0.1]
    atom_indices = atom_indices or [0]
    root.mkdir()
    (root / "reference.pdb").write_text("END\n")
    (root / "reference.prmtop").write_text("")
    (root / "pca_atom_indices.json").write_text(json.dumps({
        "atom_indices": atom_indices,
    }))
    (root / "reference_fluctuation.json").write_text(json.dumps({
        "y": {"rmsf": {"data": reference_profile}},
    }))
    return root


def _water_system(model_parameters, molecules=2, extra_site=False):
    """A System of water only, and the residues a parmed Structure would list."""
    q_o, q_h, sigma, epsilon = model_parameters
    system = mm.System()
    nonbonded = mm.NonbondedForce()
    residues = []
    for number in range(1, molecules + 1):
        atoms = []
        for atomic_number, charge, lj in ((8, q_o, (sigma, epsilon)),
                                          (1, q_h, (1.0, 0.0)), (1, q_h, (1.0, 0.0))):
            index = system.addParticle(16.0 if atomic_number == 8 else 1.008)
            nonbonded.addParticle(charge, *lj)
            atoms.append(SimpleNamespace(idx=index, atomic_number=atomic_number))
        if extra_site:
            index = system.addParticle(0.0)
            nonbonded.addParticle(-0.5, 1.0, 0.0)
            atoms.append(SimpleNamespace(idx=index, atomic_number=0))
        residues.append(SimpleNamespace(name="HOH", number=number, atoms=atoms))
    system.addForce(nonbonded)
    return system, SimpleNamespace(atoms=[a for r in residues for a in r.atoms],
                                   residues=residues)


def _make_every_other_check_pass(monkeypatch, *, connectivity_mismatch=False,
                                 submitted_system=None):
    reference, submitted = _Monomer(), _Monomer()
    system = mm.System()
    system.addParticle(1.0)
    nonbonded = mm.NonbondedForce()
    nonbonded.addParticle(0.0, 1.0, 0.0)
    system.addForce(nonbonded)
    submitted_topology = SimpleNamespace(atoms=[], residues=[])
    if submitted_system is not None:
        system, submitted_topology = submitted_system

    monkeypatch.setattr(sc.cp, "read_residues", lambda _path: [])
    monomers = iter((([reference], {}), ([submitted], {})))
    monkeypatch.setattr(
        sc.cp, "split_monomers_by_backbone_links",
        lambda *_args: next(monomers),
    )
    monkeypatch.setattr(
        sc.cp, "match_monomers", lambda _reference, _submitted: (
            ([], ["component partition differs"])
            if connectivity_mismatch else ([(reference, submitted)], [])
        ),
    )
    monkeypatch.setattr(
        sc.cp, "positional_pairs_if_identical",
        lambda *_args: [(reference, submitted)] if connectivity_mismatch else [],
    )
    monkeypatch.setattr(sc.cp, "compare_monomer", lambda *_args, **_kwargs: {
        "sequence": [], "atom_counts": [], "elements": [],
    })
    monkeypatch.setattr(sc.cp, "element_totals", lambda _monomers: {})
    monkeypatch.setattr(
        sc.cp, "compare_backbone_links", lambda *_args: (
            (True, [], [{
                "kind": "peptide",
                "residue_names": ["ALA", "GLY"],
                "residue_numbers": [1, 2],
                "chains": ["A", "A"],
                "atom_names": ["C", "N"],
            }]) if connectivity_mismatch else (True, [], [])
        )
    )
    monkeypatch.setattr(sc.cp, "read_metals", lambda _path: [])
    monkeypatch.setattr(sc.cp, "metal_ligand_positions", lambda *_args: {})
    monkeypatch.setattr(sc.cp, "catalytic_dyad_positions", lambda *_args: {})
    monkeypatch.setattr(sc.cp, "lipid_species", lambda _path: {})
    monkeypatch.setattr(sc.cp, "lipid_chemistry", lambda *_args: (set(), 0))
    monkeypatch.setattr(
        sc.cp, "contract_correspondence", lambda *_args: ([0], [])
    )

    monkeypatch.setattr(sc.tp, "find_reference_topology", lambda bundle: bundle)
    topology = SimpleNamespace(atoms=[], residues=[])
    monkeypatch.setattr(sc.tp, "load_reference", lambda *_args: topology)
    monkeypatch.setattr(
        sc.tp, "load_submission",
        lambda *_args: (submitted_topology, [], None, system)
    )
    monkeypatch.setattr(sc.tp, "backbone_links", lambda *_args: [])
    monkeypatch.setattr(sc.tp, "coordination_shell", lambda *_args, **_kwargs: {})
    monkeypatch.setattr(
        sc,
        "_check_topology_chemistry",
        lambda check, *_args: (
            check("topology_is_chemically_valid", True, "valid"),
            check("disulfide_bonds_match_reference", True, "matches"),
        ),
    )
    monkeypatch.setattr(sc, "pdb_atoms", lambda _path: [("A", "1", "CA")])

    energies = iter((1.0, 0.0))

    def single_point(_system, _state):
        energy = next(energies)
        return {
            "ok": True,
            "energy_is_finite": True,
            "energy_kj_mol": energy,
            "energy_per_particle_kj_mol": energy,
            "max_force_kj_mol_nm": 0.0,
        }

    monkeypatch.setattr(sc.en, "single_point", single_point)
    monkeypatch.setattr(sc.en, "is_physical", lambda *_args, **_kwargs: (True, "ok"))
    monkeypatch.setattr(sc.md, "load", lambda *_args, **_kwargs: _Trajectory())
    monkeypatch.setattr(sc.ex, "dcd_frame_interval_ps", lambda _path: 10.0)
    monkeypatch.setattr(sc.ex, "elapsed_time_ps", lambda *_args, **_kwargs: {
        "measurable": True,
        "elapsed_ps": 1000.0,
        "diffusion_1e5_cm2_s": 2.0,
    })
    monkeypatch.setattr(sc.dy, "atom_fluctuations", lambda _xyz: np.array([0.1]))
    monkeypatch.setattr(sc.dy, "profile_agreement", lambda *_args: 1.0)
    monkeypatch.setattr(sc.dy, "total_fluctuation", lambda _xyz: 1.0)
    monkeypatch.setattr(sc.dy, "radius_of_gyration", lambda _xyz: np.array([1.0]))
    monkeypatch.setattr(sc.dy, "energy_series", lambda _path: {
        "Temperature (K)": np.array([300.0, 300.0]),
        "Density (g/mL)": np.array([1.0, 1.0]),
        "Box Volume (nm^3)": np.array([100.0, 101.0]),
    })


def test_missing_amber_keys_fail_only_the_water_check(tmp_path, monkeypatch):
    _make_every_other_check_pass(monkeypatch)
    report = score_portable(
        _submission(tmp_path / "submission", {}),
        _bundle(tmp_path / "bundle"),
        _task(),
    )

    assert report["passed"] == 19
    assert report["total"] == 20
    failed = [check for check in report["checks"] if not check["passed"]]
    assert [check["check_id"] for check in failed] == [
        "water_model_matches_reference"
    ]
    assert "parameters.water_model is missing" in failed[0]["detail"]
    assert "forcefield_provenance.openmm_xml is missing" in failed[0]["detail"]


def test_mdclaw_amber_shape_keeps_the_water_check_passing(tmp_path, monkeypatch):
    _make_every_other_check_pass(monkeypatch)
    report = score_portable(
        _submission(tmp_path / "submission", {
            "parameters": {"water_model": "tip3p"},
            "forcefield_provenance": {"openmm_xml": ["amber14/tip3p.xml"]},
        }),
        _bundle(tmp_path / "bundle"),
        _task(),
    )

    water = next(
        check for check in report["checks"]
        if check["check_id"] == "water_model_matches_reference"
    )
    assert water["passed"] is True
    assert report["passed"] == report["total"] == 20


def test_one_wrong_backbone_link_does_not_erase_independent_checks(
        tmp_path, monkeypatch):
    _make_every_other_check_pass(monkeypatch, connectivity_mismatch=True)
    report = score_portable(
        _submission(tmp_path / "submission", {
            "parameters": {"water_model": "tip3p"},
            "forcefield_provenance": {"openmm_xml": ["amber14/tip3p.xml"]},
        }),
        _bundle(tmp_path / "bundle"),
        _task(),
    )

    failed = [check for check in report["checks"] if not check["passed"]]
    assert [check["check_id"] for check in failed] == [
        "monomer_count_matches_reference",
    ]
    assert "unexpected link(s): peptide ALA1/A:C--GLY2/A:N" in failed[0]["detail"]
    assert report["passed"] == 19
    assert report["total"] == 20


def test_null_rmsf_outside_the_contract_does_not_destroy_the_score(
    tmp_path, monkeypatch
):
    _make_every_other_check_pass(monkeypatch)
    report = score_portable(
        _submission(tmp_path / "submission", {
            "parameters": {"water_model": "tip3p"},
            "forcefield_provenance": {"openmm_xml": ["amber14/tip3p.xml"]},
        }),
        _bundle(
            tmp_path / "bundle",
            reference_profile=[None, 0.1],
            atom_indices=[1],
        ),
        _task(),
    )

    profile = next(
        check for check in report["checks"]
        if check["check_id"] == "fluctuation_profile_matches_reference"
    )
    assert profile["passed"] is True
    assert "1/1 reference contract atoms" in profile["detail"]
    assert "1/2 full-system entries" in profile["detail"]
    assert report["passed"] == report["total"] == 20


def test_null_rmsf_inside_the_contract_fails_only_the_profile_check(
    tmp_path, monkeypatch
):
    _make_every_other_check_pass(monkeypatch)
    report = score_portable(
        _submission(tmp_path / "submission", {
            "parameters": {"water_model": "tip3p"},
            "forcefield_provenance": {"openmm_xml": ["amber14/tip3p.xml"]},
        }),
        _bundle(tmp_path / "bundle", reference_profile=[None]),
        _task(),
    )

    failed = [check for check in report["checks"] if not check["passed"]]
    assert [check["check_id"] for check in failed] == [
        "fluctuation_profile_matches_reference"
    ]
    assert "0/1 reference contract atoms" in failed[0]["detail"]
    assert report["passed"] == 19
    assert report["total"] == 20


TIP3P = sc.WATER_MODEL_PARAMETERS["tip3p"]
SPCE = sc.WATER_MODEL_PARAMETERS["spce"]
TIP3P_FB = (-0.848448, 0.424224, 0.3177956, 0.6521352)   # OpenMM amber14/tip3pfb.xml
CHARMM_TIP3P = (-0.834, 0.417, 0.3150574, 0.6363864)     # CHARMM36 TIP3P oxygen


def test_the_system_names_its_own_water_model():
    for parameters, expected in ((TIP3P, "tip3p"), (CHARMM_TIP3P, "tip3p"), (SPCE, "spce")):
        name, how = sc.water_model_from_system(*_water_system(parameters))
        assert name == expected, how
        assert "2 molecules" in how


def test_neighbouring_and_four_site_waters_are_not_mistaken_for_tip3p_or_spce():
    name, how = sc.water_model_from_system(*_water_system(TIP3P_FB))
    assert name is None and "matches none" in how
    name, how = sc.water_model_from_system(*_water_system(TIP3P, extra_site=True))
    assert name is None and "not a three-site" in how
    system, structure = _water_system(TIP3P)
    nonbonded = system.getForce(0)
    nonbonded.setParticleParameters(3, -0.8476, 0.316572, 0.649775)
    nonbonded.setParticleParameters(4, 0.4238, 1.0, 0.0)
    nonbonded.setParticleParameters(5, 0.4238, 1.0, 0.0)
    name, how = sc.water_model_from_system(system, structure)
    assert name is None and "more than one parameter set" in how
    assert sc.water_model_from_system(None, structure)[0] is None
    assert sc.water_model_from_system(
        system, SimpleNamespace(atoms=[], residues=[]))[1] == "the System has no water residue"


def test_a_build_openmm_system_record_is_graded_by_the_systems_water(tmp_path, monkeypatch):
    """106_metal_6rnt, test-v6-cli glm r3: no ``parameters`` block, TIP3P built."""
    _make_every_other_check_pass(monkeypatch, submitted_system=_water_system(TIP3P))
    report = score_portable(
        _submission(tmp_path / "submission", {
            "water_model": None,
            "forcefield_provenance": {"openmm_xml": [
                "amber/ff99SBildn.xml", "amber/tip3p_standard.xml", "ligand_2AM.ffxml"]},
        }),
        _bundle(tmp_path / "bundle"),
        _task(),
    )
    water = next(check for check in report["checks"]
                 if check["check_id"] == "water_model_matches_reference")
    assert water["passed"] is True, water["detail"]
    assert "the System's own water parameters" in water["detail"]
    assert report["passed"] == report["total"] == 20


def test_a_system_water_that_is_not_the_reference_water_still_fails(tmp_path, monkeypatch):
    _make_every_other_check_pass(monkeypatch, submitted_system=_water_system(SPCE))
    report = score_portable(
        _submission(tmp_path / "submission", {
            "forcefield_provenance": {"openmm_xml": ["amber14/tip3p.xml"]},
        }),
        _bundle(tmp_path / "bundle"),
        _task(),
    )
    failed = [check for check in report["checks"] if not check["passed"]]
    assert [check["check_id"] for check in failed] == ["water_model_matches_reference"]
    assert "'spce' from the System's own water parameters" in failed[0]["detail"]


def test_no_s_s_bond_on_either_side_needs_no_monomer_pairing():
    """105_ligand_6mj7, test-v6-cli: a free ARG named ARG left no pairing."""
    passed, detail = sc._disulfide_verdict(set(), set(), [], [], True, None, [54], [54, 1])
    assert passed and "neither topology carries any S-S bond" in detail
    passed, _ = sc._disulfide_verdict(set(), set(), [], [], False, None, [54], [54, 1])
    assert passed


def test_s_s_bonds_without_a_pairing_still_fail():
    edge = frozenset(((0, 20), (0, 93)))
    passed, detail = sc._disulfide_verdict({edge}, {edge}, [], [], True, None, [123], [124])
    assert not passed and "no complete monomer correspondence" in detail
    passed, detail = sc._disulfide_verdict(set(), set(), [], ["CYS5-LIG1"], True, None,
                                           [54], [54, 1])
    assert not passed and "touch a residue outside the polymer" in detail
    passed, detail = sc._disulfide_verdict(set(), {edge}, [], [], True,
                                           (1, (0,), set(), set(), {edge}), [54], [54])
    assert not passed and "unexpected" in detail
