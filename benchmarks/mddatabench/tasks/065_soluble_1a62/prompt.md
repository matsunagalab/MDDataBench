# Task 065_soluble_1a62

Simulate RHO, PDB entry **1A62**, chain **A** residues **1–130**, in explicit solvent.

- **TIP3P** water, neutralised
- **300 K**, **NPT** at **1 bar**
- at least **1 ns** of production MD

Chain A does not resolve residues 126, 127, 128, 129, 130; the range runs through them, so build them.

Residue 1 is deposited as **MSE**, a modified MET. Simulate the unmodified residue.

Residue 21 is deposited as **MSE**, a modified MET. Simulate the unmodified residue.

Residue 29 is deposited as **MSE**, a modified MET. Simulate the unmodified residue.

Leave the prepared structure, the topology, the minimised state and the production
trajectory as artifacts. The evaluator recomputes everything it needs from them.
