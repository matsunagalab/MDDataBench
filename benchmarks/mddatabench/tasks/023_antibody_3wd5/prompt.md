# Task 023_antibody_3wd5

Simulate Crystal structure of TNFalpha in complex with Adalimumab Fab fragment, PDB entry **3WD5**, chain **A** residues **6–157**, chain **L** residues **1–213**, chain **H** residues **1–219**, in explicit solvent.

- **TIP3P** water, neutralised
- **300 K**, **NPT** at **1 bar**
- at least **2.5 ns** of production MD

The deposit does not resolve every residue of the stated ranges. Build the ones it leaves out, including any at the start or end of a range.

Simulate every ionisable side chain in its standard state at pH 7: charged aspartate, glutamate, lysine and arginine, and neutral histidine and cysteine.

Leave the prepared structure, the topology, the minimised state and the production
trajectory as artifacts. The evaluator recomputes everything it needs from them.
