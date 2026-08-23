# Task 088_soluble_12ca

Simulate CARBONIC ANHYDRASE II, PDB entry **12CA**, chain **A** residues **5–260**, in explicit solvent.

- **TIP3P** water, neutralised
- **300 K**, **NPT** at **1 bar**
- at least **1 ns** of production MD

Residue 107 of chain A is a protonated histidine.

Simulate every other ionisable side chain in its standard state at pH 7: charged aspartate, glutamate, lysine and arginine, and neutral histidine and cysteine.

Leave the prepared structure, the topology, the minimised state and the production
trajectory as artifacts. The evaluator recomputes everything it needs from them.
