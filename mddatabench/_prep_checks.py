"""The prep-side check block shared by every task contract.

Kept in one place because it is genuinely identical across tasks: every check
takes its expectation from the reference bundle rather than from a curator, so
nothing here is per-system.  D02's completed side chains and D03's disulfides
used to be hand-written per-task checks; they are now instances of
``residue_atom_counts_match_reference`` and ``disulfide_bonds_match_reference``,
which run on every task and expect zero as readily as two.

Run ``python -m mddatabench._prep_checks`` to write the block into every
``benchmarks/mddatabench/tasks/*/task.json``.
"""

from __future__ import annotations

import json
import pathlib

TASKS = pathlib.Path(__file__).resolve().parents[1] / "benchmarks" / "mddatabench" / "tasks"

PREP_CHECKS = [
    {
        "check_id": "monomer_count_matches_reference",
        "check_type": "monomer_partition_rescan@1",
        "capability": "identity",
        "weight": 1.0,
        "category": "prep",
        "note": "Splits both sides into covalently connected polymer chains by backbone "
                "geometry, then pairs them by canonical sequence. PDB chain IDs are not used: "
                "preparation tools relabel and reuse them, and D03's system.topology.pdb "
                "carries chains A, B and C where the reference has only A. Every later "
                "composition check runs inside a matched pair, so a multimer is N monomers "
                "instead of a special case and a failure names a chain and a residue."
    },
    {
        "check_id": "sequence_matches_reference",
        "check_type": "sequence_identity_rescan@1",
        "capability": "identity",
        "weight": 1.0,
        "category": "prep",
        "note": "Residue-by-residue, after collapsing every protonation and bonding variant "
                "onto its parent (HID/HIE/HIP -> HIS, CYX/CYM -> CYS, ...). Comparing counts "
                "alone would miss a wrong chain of the right length."
    },
    {
        "check_id": "residue_atom_counts_match_reference",
        "check_type": "residue_composition_rescan@1",
        "capability": "composition_fidelity",
        "weight": 1.0,
        "category": "prep",
        "note": "Atom count of every residue, per monomer. Graded by count and never by "
                "residue name: the same MDClaw submission writes CYX in merged.pdb and CYS in "
                "system.topology.pdb, GROMACS writes HISD/HISE/HISH, CHARMM HSD/HSE/HSP. "
                "Counts are tautomer-blind by construction (HID and HIE have the same formula, "
                "and measured 2026-08-21 the reference and the submission disagree on the "
                "tautomer in both D01 and D02) while detecting every ionisation and bonding "
                "variant, each of which costs or adds exactly one hydrogen: HIP, ASH, GLH, "
                "LYN, CYM, and CYX. It also subsumes the truncated-side-chain check this "
                "replaces, and does so for every residue rather than four named ones."
    },
    {
        "check_id": "element_composition_matches_reference",
        "check_type": "element_composition_rescan@1",
        "capability": "composition_fidelity",
        "weight": 1.0,
        "category": "prep",
        "note": "Heavy atoms counted per element rather than in total, so a substitution that "
                "preserves the total does not pass. Tautomer independent."
    },
    {
        "check_id": "protein_atom_count_matches_reference",
        "check_type": "reference_composition_rescan@1",
        "capability": "composition_fidelity",
        "weight": 1.0,
        "category": "prep",
        "note": "Exact, with no tolerance. The earlier +/-2 allowance was believed to be needed "
                "for histidine tautomers; measured 2026-08-21, D02 picked the opposite tautomer "
                "from the reference and still matched 1014/1014 exactly, because HID and HIE "
                "have the same formula. The tolerance protected nothing and admitted up to two "
                "ionisation errors, each of which is exactly one hydrogen."
    },
    {
        "check_id": "disulfide_bonds_match_reference",
        "check_type": "disulfide_bond_rescan@1",
        "capability": "composition_fidelity",
        "weight": 1.0,
        "category": "prep",
        "maximum_sg_distance_angstrom": 2.5,
        "note": "Runs on every task; zero expected pairs is a real expectation. Expected pairs "
                "come from the reference's own CYX residues and coordinates, not from a curator "
                "list. Observed pairs come from the CONECT records of the submitted topology, "
                "because system.system.xml is a compiled force-field object with no atom names "
                "and, once HBonds and rigid water turn bonds into constraints, no usable bond "
                "list either: D03's System keeps 177 HarmonicBondForce terms against 21451 "
                "constraints. Comparing the whole pair set also catches a spurious disulfide, "
                "which the earlier per-task check could not."
    },
    {
        "check_id": "topology_loads_and_is_parameterized",
        "check_type": "openmm_system_load@1",
        "capability": "physical_validity",
        "weight": 0.0,
        "category": "precondition",
        "note": "Reported and not scored. Deserialising the submitted System is what lets the "
                "scorer look at the force field at all; a file that will not load leaves it "
                "unable to measure, rather than telling it the agent prepared badly. The checks "
                "that depend on it -- force-field coverage, net charge, and both energies -- do "
                "fail in that case, and they are the ones that carry the marks. Until "
                "2026-08-21 this raised straight out of the scorer: a truncated file, an empty "
                "System, or a System with no NonbondedForce each crashed the run instead of "
                "being recorded, so the graded condition (particle count above zero) could only "
                "ever be reached when it was already true."
    },
    {
        "check_id": "forcefield_applied_to_every_atom",
        "check_type": "forcefield_applied_rescan@1",
        "capability": "physical_validity",
        "weight": 1.0,
        "category": "prep"
    },
    {
        "check_id": "system_is_neutral",
        "check_type": "net_charge_check@1",
        "capability": "physical_validity",
        "expected_net_charge": 0,
        "weight": 1.0,
        "category": "prep",
        "note": "The only solvent-side quantity that can be checked at all. MDDB records SOL, "
                "SOLVATS and SOLVRES as zero in all 4554 projects, so water counts are never "
                "available; ion counts and box size coexist in only 47 of the 1940 eligible "
                "projects and in 46 of those the ion is a single neutralising counterion, so "
                "no salt concentration can be demanded either."
    },
    {
        "check_id": "potential_energy_is_physical",
        "check_type": "openmm_energy_rescan@1",
        "capability": "physical_validity",
        "weight": 1.0,
        "category": "prep",
        "maximum_abs_energy_per_particle_kj_mol": 1000000.0,
        "note": "Single-point energy recomputed from the submitted system.xml at the submitted "
                "state; the runner's own minimization_report.json is not read, for the same "
                "reason the solvent clock does not read simulation_time_ns. The ceiling is "
                "deliberately loose and catches only clash-driven systems. The per-atom value "
                "is a diagnostic: measured 2026-08-21 it is -17.00 / -16.93 / -16.94 kJ/mol/atom "
                "for D01 / D02 / D03, which is three systems on one force field and one water "
                "model and does not yet justify a band."
    },
    {
        "check_id": "minimization_reduced_the_energy",
        "check_type": "minimization_rescan@1",
        "capability": "physical_validity",
        "weight": 1.0,
        "category": "prep",
        "note": "Both energies are recomputed by the scorer from the same system.xml, at the "
                "built state and at the minimised state. Measured 2026-08-21: +505918 -> "
                "-532908, +400845 -> -600622, +331474 -> -366799 kJ/mol, with the maximum force "
                "falling from 32235 / 45717 / 25096 to 1727 / 1820 / 2427 kJ/mol/nm. The force "
                "is recorded as a diagnostic and not graded."
    },
    {
        "check_id": "water_model_matches_reference",
        "check_type": "water_model_fingerprint@1",
        "capability": "composition_fidelity",
        "weight": 1.0,
        "category": "prep",
        "note": "MDDB records WAT for 96.5% of eligible projects, so the model name is a "
                "database-backed expectation. The amount of water is not: SOL is empty "
                "everywhere. MDClaw defaults to opc; TIP3P must be requested explicitly."
    },
]


def apply() -> list[str]:
    """Replace the prep block of every task contract; leave md checks untouched.

    The block carries no per-system expectations. Residue, atom and element
    counts come from the reference bundle at scoring time, which is already the
    authority for them -- copying them here as well would leave two numbers to
    keep in step, and `reference.reference_system` is the one the scorer reads.
    """
    touched = []
    for path in sorted(TASKS.glob("*/task.json")):
        task = json.loads(path.read_text())
        checks = task["scoring"]["deterministic_checks"]
        block = [dict(c) for c in PREP_CHECKS]
        keep = [c for c in checks
                if c["check_id"] != "radius_of_gyration_is_physical"
                and (c.get("category") in ("md", "precondition")
                     or c["check_id"] == "contract_atoms_resolvable")]
        for check in keep:
            if check["check_id"] == "contract_atoms_resolvable":
                check["category"] = "precondition"
                check["weight"] = 0.0
                check["note"] = (
                    "Scorer-side precondition, reported and not scored: the reference's contract "
                    "atoms must resolve onto the submitted topology before either subspace can "
                    "be computed. It measures the scorer's ability to line the two systems up, "
                    "not the agent's preparation, so it does not belong in the prep total.")
        task["scoring"]["deterministic_checks"] = block + keep
        path.write_text(json.dumps(task, indent=2) + "\n")
        touched.append(path.name)
    return touched


if __name__ == "__main__":
    for name in apply():
        print("rewrote", name)
