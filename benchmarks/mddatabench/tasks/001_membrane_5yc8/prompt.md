# Task 001_membrane_5yc8

Simulate Muscarinic acetylcholine receptor M2, PDB entry **5YC8**, chain **A** residues **16–214** and **380–458**, in explicit solvent.

- **TIP3P** water, neutralised
- **300 K**, **NPT** at **1 bar**
- at least **1 ns** of production MD

Chain A is deposited as a fusion: 165 residues between those ranges belong to the crystallisation partner. Simulate the protein without them.

Embed it in a **DPPC** bilayer.

Simulate every ionisable side chain in its standard state at pH 7: charged aspartate, glutamate, lysine and arginine, and neutral histidine and cysteine.

Leave the prepared structure, the topology, the minimised state and the production
trajectory as artifacts. The evaluator recomputes everything it needs from them.
