# Task 015_antibody_1ahw

Simulate A COMPLEX OF EXTRACELLULAR DOMAIN OF TISSUE FACTOR WITH AN INHIBITORY, PDB entry **1AHW**, chain **A** residues **1–214**, chain **B** residues **1–214**, chain **C** residues **4–211**, in explicit solvent.

- **TIP3P** water, neutralised
- **300 K**, **NPT** at **1 bar**
- at least **2.5 ns** of production MD

The deposit does not resolve every residue of the stated ranges. Build the ones it leaves out, including any at the start or end of a range.

Simulate every ionisable side chain in its standard state at pH 7: charged aspartate, glutamate, lysine and arginine, and neutral histidine and cysteine.

Leave the prepared structure, the topology, the minimised state and the production
trajectory as artifacts. The evaluator recomputes everything it needs from them.
