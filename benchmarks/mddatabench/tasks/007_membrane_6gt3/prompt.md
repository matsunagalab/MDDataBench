# Task 007_membrane_6gt3

Simulate Adenosine receptor A2a, PDB entry **6GT3**, chain **A** residues **-1–305**, in explicit solvent.

- **TIP3P** water, neutralised
- **310 K**, **NPT** at **1 bar**
- at least **1 ns** of production MD

Residue 209–218 of chain A is not part of the reference. Leave it out.

Keep chain A residues 208 and 219 as separate termini; do not create a peptide bond between A:208 C and A:219 N.

Embed it in a **DPPC** bilayer.

Residue 264 of chain A is a protonated histidine.

Simulate every other ionisable side chain in its standard state at pH 7: charged aspartate, glutamate, lysine and arginine, and neutral histidine and cysteine.

Leave the prepared structure, the topology, the minimised state and the production
trajectory as artifacts. The evaluator recomputes everything it needs from them.
