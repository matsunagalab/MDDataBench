# Task 062_metal_6w9c

Simulate Non-structural protein 3, PDB entry **6W9C**, chain **C** residues **4–315**, in explicit solvent.

- **Amber ff14SB** protein force field, **TIP3P** water, neutralised
- **298 K**, **NPT** at **1 bar**
- at least **1 ns** of production MD

The entry carries a structural zinc. Keep it.

The deposit does not resolve every residue of the stated ranges. Build the ones it leaves out, including any at the start or end of a range.

Simulate every ionisable side chain in its standard state at pH 7: charged aspartate, glutamate, lysine and arginine, and neutral histidine and cysteine.

Leave the prepared structure, the topology, the minimised state and the production
trajectory as artifacts. The evaluator recomputes everything it needs from them.
