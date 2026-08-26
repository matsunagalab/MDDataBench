# Task 011_membrane_6kuy

Simulate Alpha2A adrenergic receptor, PDB entry **6KUY**, chain **A** residues **33–227** and **365–443**, in explicit solvent.

- **TIP3P** water, neutralised
- **310 K**, **NPT** at **1 bar**
- at least **1 ns** of production MD

Chain A is deposited as a fusion: 137 residues between those ranges belong to the crystallisation partner. Simulate the protein without them.

Residue 173–182 of chain A is not part of the reference. Leave it out.

Embed it in a **DPPC** bilayer.

Simulate every ionisable side chain in its standard state at pH 7: charged aspartate, glutamate, lysine and arginine, and neutral histidine and cysteine.

Leave the prepared structure, the topology, the minimised state and the production
trajectory as artifacts. The evaluator recomputes everything it needs from them.
