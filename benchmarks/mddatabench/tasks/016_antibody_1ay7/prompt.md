# Task 016_antibody_1ay7

Simulate RIBONUCLEASE SA COMPLEX WITH BARSTAR, PDB entry **1AY7**, chain **A** residues **1–96**, chain **B** residues **1–89**, in explicit solvent.

- **TIP3P** water, neutralised
- **300 K**, **NPT** at **1 bar**
- at least **2.5 ns** of production MD

Simulate Cys7 and Cys96 of chain A as free (reduced) cysteines; do not form a disulfide bond between them.

Simulate every other ionisable side chain in its standard state at pH 7: charged aspartate, glutamate, lysine and arginine, and neutral histidine and cysteine.

Leave the prepared structure, the topology, the minimised state and the production
trajectory as artifacts. The evaluator recomputes everything it needs from them.
