# Task 076_soluble_1ctf

Simulate RIBOSOMAL PROTEIN L7/L12, PDB entry **1CTF**, chain **A** residues **47–120**, in explicit solvent.

- **TIP3P** water, neutralised
- **300 K**, **NPT** at **1 bar**
- at least **1 ns** of production MD

Chain A does not resolve residues 47, 48, 49, 50, 51, 52; the range runs through them, so build them.

Simulate every ionisable side chain in its standard state at pH 7: charged aspartate, glutamate, lysine and arginine, and neutral histidine and cysteine.

Leave the prepared structure, the topology, the minimised state and the production
trajectory as artifacts. The evaluator recomputes everything it needs from them.
