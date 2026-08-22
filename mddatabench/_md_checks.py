"""The md-side check block, shared by every task contract.

Like the prep block this is identical across tasks: temperature and ensemble come
from the reference's own recorded conditions, and the subspace null is built from
the reference structure at scoring time.  Only the temperature value is per-task,
and it is copied from ``reference_conditions``.

Radius of gyration is deliberately absent: measured 2026-08-21 it is a property
of the prepared structure rather than of the simulation, and grading it here
attributed a preparation property to the run.
"""

from __future__ import annotations

MD_CHECKS = [
    {
        "check_id": "metal_site_coordination_retained",
        "check_type": "metal_coordination_rescan@1",
        "capability": "observable_fidelity",
        "weight": 0.0,
        "category": "diagnostic",
        "metal_ligand_angstrom": 3.5,
        "occupancy_fraction": 0.9,
        "note": "Reported, never scored, until it has been measured on more than three "
                "systems. Counts the side chains coordinating each metal in the built "
                "structure and how many of them are still coordinating for most of "
                "production. It is not a comparison with the reference and cannot be: "
                "measured 2026-08-22, all three references hold a four-cysteine structural "
                "zinc with a bare 12-6 ion, deprotonate two of the four ligands, lose the "
                "other two to 5-13 A, and let the zinc be chelated by a glutamine oxygen at "
                "1.75 A instead. Our own submissions use the same ion with the same "
                "parameters and one thiolate, and retain one ligand. When this is eventually "
                "scored it must also read the spread, because a bonded metal model satisfies "
                "a distance test by construction and an over-restrained site would pass."
    },
    {
        "check_id": "thermodynamic_conditions_match_reference",
        "check_type": "ensemble_conditions_rescan@1",
        "capability": "composition_fidelity",
        "weight": 1.0,
        "category": "md",
        "temperature_tolerance_k": 1.0,
    },
    {
        "check_id": "production_ran_for_one_nanosecond",
        "check_type": "production_length_check@1",
        "capability": "execution_validity",
        "minimum_production_ns": 1.0,
        "require_finite_coordinates": True,
        "weight": 1.0,
        "category": "md",
        "note": "Reads the runner's recorded metadata. Kept as a declaration check; "
                "elapsed_simulated_time_is_physical is what actually verifies it.",
    },
    {
        "check_id": "elapsed_simulated_time_is_physical",
        "check_type": "elapsed_simulated_time@1",
        "capability": "execution_validity",
        "minimum_measured_fraction_of_claim": 0.5,
        "weight": 1.0,
        "category": "md",
        "note": "Elapsed time measured from continuously unwrapped solvent displacement "
                "instead of the runner's simulation_time_ns. The frame interval comes "
                "from the DCD header, not from traj.time, which mdtraj fills with frame "
                "indices.",
    },
    {
        "check_id": "contract_atoms_resolvable",
        "check_type": "reference_subspace_recompute@1",
        "capability": "observable_recompute",
        "contract_id": "pca_backbone_subspace@1",
        "weight": 0.0,
        "category": "precondition",
        "note": "Scorer-side precondition, reported and not scored: the reference's "
                "contract atoms must resolve onto the submitted topology before either "
                "subspace can be computed.",
    },
    {
        "check_id": "subspace_beyond_structure_only_model",
        "check_type": "subspace_beyond_structure@1",
        "capability": "ensemble_reproduction",
        "test_id": "subspace_beyond_structure@1",
        "contract_id": "pca_backbone_subspace@1",
        "weight": 1.0,
        "category": "md",
        "null_hypothesis": "the submission is no better than what the fold alone predicts: "
                           "its RMSIP against the reference is drawn from the spread of "
                           "elastic network models of the same structure, swept over "
                           "cutoff 7.0-20.0 A",
        "decision": "pass when the observed RMSIP exceeds every null draw",
    },
]
