# Task 080_soluble_1ez3

Simulate SYNTAXIN-1A, PDB entry **1EZ3**, chain **B** residues **24–150**, in explicit solvent.

- **TIP3P** water, neutralised
- **300 K**, **NPT** at **1 bar**
- at least **1 ns** of production MD

Chain B does not resolve residues 24, 25, 26; the range runs through them, so build them.

Simulate every ionisable side chain in its standard state at pH 7: charged aspartate, glutamate, lysine and arginine, and neutral histidine and cysteine.

Leave the prepared structure, the topology, the minimised state and the production
trajectory as artifacts. The evaluator recomputes everything it needs from them.
