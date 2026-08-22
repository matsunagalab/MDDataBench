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
