"""Portable metadata faults cost their own check, not the whole score."""

from __future__ import annotations

import json

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


def _bundle(root):
    root.mkdir()
    (root / "reference.pdb").write_text("END\n")
    (root / "reference.prmtop").write_text("")
    (root / "pca_atom_indices.json").write_text(json.dumps({"atom_indices": [0]}))
    (root / "reference_fluctuation.json").write_text(json.dumps({
        "y": {"rmsf": {"data": [0.1]}},
    }))
    return root


def _make_every_other_check_pass(monkeypatch):
    reference, submitted = _Monomer(), _Monomer()
    system = mm.System()
    system.addParticle(1.0)
    nonbonded = mm.NonbondedForce()
    nonbonded.addParticle(0.0, 1.0, 0.0)
    system.addForce(nonbonded)

    monkeypatch.setattr(sc.cp, "read_residues", lambda _path: [])
    monomers = iter(([reference], [submitted]))
    monkeypatch.setattr(sc.cp, "split_monomers", lambda _residues: next(monomers))
    monkeypatch.setattr(
        sc.cp, "match_monomers", lambda _reference, _submitted: (
            [(reference, submitted)], []
        ),
    )
    monkeypatch.setattr(sc.cp, "compare_monomer", lambda *_args, **_kwargs: {
        "sequence": [], "atom_counts": [], "elements": [],
    })
    monkeypatch.setattr(sc.cp, "element_totals", lambda _monomers: {})
    monkeypatch.setattr(sc.cp, "read_metals", lambda _path: [])
    monkeypatch.setattr(sc.cp, "metal_ligand_positions", lambda *_args: {})
    monkeypatch.setattr(sc.cp, "catalytic_dyad_positions", lambda *_args: {})
    monkeypatch.setattr(sc.cp, "lipid_species", lambda _path: {})
    monkeypatch.setattr(sc.cp, "lipid_chemistry", lambda *_args: (set(), 0))
    monkeypatch.setattr(
        sc.cp, "contract_correspondence", lambda *_args: ([0], [])
    )

    monkeypatch.setattr(sc.tp, "find_reference_topology", lambda bundle: bundle)
    monkeypatch.setattr(sc.tp, "load_reference", lambda *_args: object())
    monkeypatch.setattr(
        sc.tp, "load_submission", lambda *_args: (object(), [], None, system)
    )
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
