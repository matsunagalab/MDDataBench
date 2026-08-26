# Task 065_soluble_1a62

Simulate RHO, PDB entry **1A62**, chain **A** residues **1–130**, in explicit solvent.

- **TIP3P** water, neutralised
- **300 K**, **NPT** at **1 bar**
- at least **1 ns** of production MD

Residue 1 is deposited as **MSE**, a modified MET. Simulate the unmodified residue.

Residue 21 is deposited as **MSE**, a modified MET. Simulate the unmodified residue.

Residue 29 is deposited as **MSE**, a modified MET. Simulate the unmodified residue.

The deposit does not resolve every residue of the stated ranges. Build the ones it leaves out, including any at the start or end of a range.

Simulate every ionisable side chain in its standard state at pH 7: charged aspartate, glutamate, lysine and arginine, and neutral histidine and cysteine.

Leave the prepared structure, the topology, the minimised state and the production
trajectory as artifacts. The evaluator recomputes everything it needs from them.
