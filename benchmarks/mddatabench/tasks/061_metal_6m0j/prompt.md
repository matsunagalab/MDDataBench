# Task 061_metal_6m0j

Simulate Spike protein S1 in complex with Angiotensin-converting enzyme 2, PDB entry **6M0J**, chain **A** residues **19–357**, chain **E** residues **403–526**, in explicit solvent.

- **Amber ff14SB** protein force field, **OPC** water, neutralised
- **300 K**, **NPT** at **1 bar**
- at least **1 ns** of production MD

Residue 34 of chain A is a protonated histidine.

Residue 228 of chain A is a protonated histidine.

Simulate every other ionisable side chain in its standard state at pH 7: charged aspartate, glutamate, lysine and arginine, and neutral histidine and cysteine.

Leave the prepared structure, the topology, the minimised state and the production
trajectory as artifacts. The evaluator recomputes everything it needs from them.
