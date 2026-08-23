# Task 014_membrane_6zdv

Simulate Adenosine receptor A2a, PDB entry **6ZDV**, chain **A** residues **0–207** and **1106–1106** and **219–305**, in explicit solvent.

- **TIP3P** water, neutralised
- **310 K**, **NPT** at **1 bar**
- at least **1 ns** of production MD

Chain A is deposited as a fusion: 106 residues between those ranges belong to the crystallisation partner. Simulate the protein without them.

Join the pieces of chain A into a single continuous chain, bonded where the removed part was.

Embed it in a **DPPC** bilayer.

Simulate every ionisable side chain in its standard state at pH 7: charged aspartate, glutamate, lysine and arginine, and neutral histidine and cysteine.

Leave the prepared structure, the topology, the minimised state and the production
trajectory as artifacts. The evaluator recomputes everything it needs from them.
