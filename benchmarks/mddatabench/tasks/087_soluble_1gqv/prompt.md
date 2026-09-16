# Task 087_soluble_1gqv

Simulate EOSINOPHIL-DERIVED NEUROTOXIN, PDB entry **1GQV**, chain **A** residues **0–134**, in explicit solvent.

- **TIP3P** water, neutralised
- **300 K**, **NPT** at **1 bar**
- at least **1 ns** of production MD
- neutral pH; ionisation states of the side chains are your choice

Form exactly these disulfide bonds: Cys23–Cys83 of chain A, Cys55–Cys111 of chain A, Cys62–Cys71 of chain A.

Simulate Cys37 and Cys96 of chain A as free (reduced) cysteines; do not form a disulfide bond between them.

The deposit's **ACT** is not part of the reference. Simulate the protein without it.

Leave the prepared structure, the topology, the minimised state and the production
trajectory as artifacts. The evaluator recomputes everything it needs from them.
