# Task 076_soluble_1ctf

Simulate RIBOSOMAL PROTEIN L7/L12, PDB entry **1CTF**, chain **A** residues **47–120**, in explicit solvent.

- **TIP3P** water, neutralised
- **300 K**, **NPT** at **1 bar**
- at least **1 ns** of production MD
- neutral pH; ionisation states of the side chains are your choice

Chain A does not resolve residues 47, 48, 49, 50, 51, 52; the range runs through them, so build them.

The deposit's **SO4** is not part of the reference. Simulate the protein without it.

Leave the prepared structure, the topology, the minimised state and the production
trajectory as artifacts. The evaluator recomputes everything it needs from them.
