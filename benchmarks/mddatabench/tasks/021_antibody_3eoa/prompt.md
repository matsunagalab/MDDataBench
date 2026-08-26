# Task 021_antibody_3eoa

Simulate Crystal structure the Fab fragment of Efalizumab in complex with, PDB entry **3EOA**, chain **L** residues **1–214**, chain **H** residues **1–220**, chain **I** residues **128–306**, in explicit solvent.

- **TIP3P** water, neutralised
- **300 K**, **NPT** at **1 bar**
- at least **2.5 ns** of production MD

The deposit does not resolve every residue of the stated ranges. Build the ones it leaves out, including any at the start or end of a range.

Simulate every ionisable side chain in its standard state at pH 7: charged aspartate, glutamate, lysine and arginine, and neutral histidine and cysteine.

Leave the prepared structure, the topology, the minimised state and the production
trajectory as artifacts. The evaluator recomputes everything it needs from them.
