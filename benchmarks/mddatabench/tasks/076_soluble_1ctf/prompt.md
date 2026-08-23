# Task 076_soluble_1ctf

Simulate RIBOSOMAL PROTEIN L7/L12, PDB entry **1CTF**, chain **A** residues **51–120**, in explicit solvent.

- **TIP3P** water, neutralised
- **300 K**, **NPT** at **1 bar**
- at least **1 ns** of production MD

Chain A does not resolve residues 51, 52, 54, 55, 52, 53; the range runs through them, so build them.

Leave the prepared structure, the topology, the minimised state and the production
trajectory as artifacts. The evaluator recomputes everything it needs from them.
