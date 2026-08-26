# Task 068_soluble_1ail

Simulate NONSTRUCTURAL PROTEIN NS1, PDB entry **1AIL**, chain **A** residues **1–73**, in explicit solvent.

- **TIP3P** water, neutralised
- **300 K**, **NPT** at **1 bar**
- at least **1 ns** of production MD

The deposit does not resolve every residue of the stated ranges. Build the ones it leaves out, including any at the start or end of a range.

Simulate every ionisable side chain in its standard state at pH 7: charged aspartate, glutamate, lysine and arginine, and neutral histidine and cysteine.

Leave the prepared structure, the topology, the minimised state and the production
trajectory as artifacts. The evaluator recomputes everything it needs from them.
