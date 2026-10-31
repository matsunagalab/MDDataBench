# Task 121_soluble_2o6x

Simulate Secreted cathepsin L 1, PDB entry **2O6X**, chain **A** residues **8–317**, in explicit solvent.

- **TIP3P** water, neutralised
- **300 K**, **NPT** at **1 bar**
- at least **1 ns** of production MD
- neutral pH; ionisation states of the side chains are your choice

Chain A does not resolve residues 94, 95, 96, 97; the range runs through them, so build them.

Form exactly these disulfide bonds: Cys120–Cys163 of chain A, Cys154–Cys195 of chain A.

Simulate Cys253 and Cys302 of chain A as free (reduced) cysteines; do not form a disulfide bond between them.

Leave the prepared structure, the topology, the minimised state and the production
trajectory as artifacts. The evaluator recomputes everything it needs from them.
