"""The md-side check block, shared by every task contract.

Like the prep block this is identical across tasks: temperature and ensemble come
from the reference's own recorded conditions, and the subspace null is built from
the reference structure at scoring time.  Only the temperature value is per-task,
and it is copied from ``reference_conditions``.

The subspace test is gone.  Measured 2026-08-22 on the negative controls, an
elastic-network ensemble scored RMSIP 0.749 against the real run's 0.704, so a
model with no dynamics beat the simulation and the control it was meant to
reject was rejected by the solvent clock instead.

What replaced it is bounded by three deliberate blindnesses.  The force field
is free, so nothing may key on rotamer or salt-bridge propensities.  The
protonation of ambiguous residues is free and already exempt on the prep side.
The thermostat is free, so every time-correlation statistic is out -- a
lag-dependent MSD separates real runs (2.9-4.5) from shuffled frames
(0.97-1.08) cleanly and is still unusable, because it would fail a correct run
for its integrator.  Equilibrium properties are what survive.
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
        "check_id": "measured_temperature_matches_reference",
        "check_type": "measured_temperature@1",
        "capability": "execution_validity",
        "weight": 1.0,
        "category": "md",
        "tolerance_kelvin": 3.0,
        "note": "The mean temperature the run actually reported, from the OpenMM "
                "state log, not the value it was asked for -- the same class of "
                "claim the solvent clock exists to distrust. The tolerance is 3 K "
                "against a measured offset of +0.46 to +0.49 K across three runs, "
                "so it has six times the room the artefact needs while a 310 K "
                "run misses by four times the band. The spread of the temperature "
                "is deliberately not graded: it is set by the thermostat's "
                "friction, which the task leaves free."
    },
    {
        "check_id": "solvent_box_is_physical",
        "check_type": "solvent_box_physical@1",
        "capability": "physical_validity",
        "weight": 1.0,
        "category": "md",
        "density_range_g_per_ml": [0.95, 1.10],
        "note": "Mean density inside a band wide enough for every water model, and "
                "a box volume that actually moved. The band is not a water-model "
                "check -- prep already has one -- it is a check that the box holds "
                "a liquid: pure TIP3P is 0.982, SPC/E 0.994, TIP4P-Ew 0.995, OPC "
                "0.997 g/mL at 298 K, and a solvated protein runs a little above "
                "that (measured 1.011 to 1.013). A vacuum, a bubble or a system "
                "that flew apart misses by far more than the margin. The volume "
                "having non-zero spread is what says a barostat was connected; "
                "zero against non-zero needs no threshold."
    },
    {
        "check_id": "fluctuation_profile_matches_reference",
        "check_type": "fluctuation_profile_rank@1",
        "capability": "ensemble_reproduction",
        "weight": 1.0,
        "category": "md",
        "note": "Spearman correlation between the submission's per-atom "
                "fluctuation profile and the reference's own, over the contract "
                "atoms. Rank-based on purpose: it asks which atoms move more than "
                "which and nothing about how much, which is what lets a different "
                "force field and a different thermostat pass -- measured, the same "
                "system under ff99SBildn scores 0.840 against a band whose floor "
                "is 0.840, where ff14SB scores 0.870. It is blind to an "
                "over-restrained run (0.872 with a tenth of the motion), which is "
                "what the magnitude check is for. The band is the range over the "
                "reference's own one-nanosecond windows; the floor is what is "
                "graded, since agreement above it is agreement."
    },
    {
        "check_id": "fluctuation_magnitude_is_physical",
        "check_type": "fluctuation_magnitude@1",
        "capability": "ensemble_reproduction",
        "weight": 1.0,
        "category": "md",
        "note": "Total root-mean-square fluctuation of the contract atoms, against "
                "the range over the reference's own one-nanosecond windows. Two "
                "sided, and it is the half of the pair that catches what ranks "
                "cannot: measured, an over-restrained run falls to 0.077 A and a "
                "threefold expansion rises to 2.328 A while both keep a rank "
                "correlation near 0.87. A linear drift is removed from each atom "
                "first, on both sides: the quantity wanted is the equilibrium "
                "fluctuation, and a run started from a crystal structure carries "
                "a drift the reference's windows do not."
    },
    {
        "check_id": "radius_of_gyration_matches_reference",
        "check_type": "radius_of_gyration_band@1",
        "capability": "ensemble_reproduction",
        "weight": 1.0,
        "category": "md",
        "note": "Mean radius of gyration against the reference's own "
                "one-nanosecond windows. It needs no superposition at all, which "
                "is why the high side of the judgement rests here: a fit puts a "
                "run's drift into every atom's deviation, and a crystal-started "
                "nanosecond drifts. Catches a system that came apart or collapsed."
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
]
