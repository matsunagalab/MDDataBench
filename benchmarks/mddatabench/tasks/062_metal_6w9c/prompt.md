# Task 062_metal_6w9c

Simulate Non-structural protein 3, PDB entry **6W9C**, chain **C** residues **4–315**, in explicit solvent.

- **Amber ff14SB** protein force field, **TIP3P** water, neutralised
- **298 K**, **NPT** at **1 bar**
- at least **1 ns** of production MD

Chain C does not resolve residues 225, 226, 315; the range runs through them, so build them.

The entry carries a structural zinc. Keep it.

Leave the prepared structure, the topology, the minimised state and the production
trajectory as artifacts. The evaluator recomputes everything it needs from them.
