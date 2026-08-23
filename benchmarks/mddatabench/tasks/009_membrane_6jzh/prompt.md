# Task 009_membrane_6jzh

Simulate Adenosine receptor A2a, PDB entry **6JZH**, chain **A** residues **-1–308**, in explicit solvent.

- **TIP3P** water, neutralised
- **310 K**, **NPT** at **1 bar**
- at least **1 ns** of production MD

Residue 209–218 of chain A is not part of the reference. Leave it out.

Embed it in a **DPPC** bilayer.

Simulate every ionisable side chain in its standard state at pH 7: charged aspartate, glutamate, lysine and arginine, and neutral histidine and cysteine.

Leave the prepared structure, the topology, the minimised state and the production
trajectory as artifacts. The evaluator recomputes everything it needs from them.
