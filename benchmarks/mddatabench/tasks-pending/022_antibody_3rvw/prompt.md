# Task 022_antibody_3rvw

Simulate the deposited system, PDB entry **3RVW**, chain **A** residues **1–222**, chain **C** residues **1–211**, chain **D** residues **1–222**, in explicit solvent.

- **CHARMM36m** protein force field, **TIP3P** water, neutralised
- **300 K**, **NPT**
- at least **2.5 ns** of production MD

4 residue(s) of that range are not resolved in the deposit. Build them.

Residue 52 is deposited as **ASN**, a modified ASN. Simulate the unmodified residue.

Leave the prepared structure, the topology, the minimised state and the production
trajectory as artifacts. The evaluator recomputes everything it needs from them.
