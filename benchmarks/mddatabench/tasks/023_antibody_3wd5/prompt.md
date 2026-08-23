# Task 023_antibody_3wd5

Simulate Crystal structure of TNFalpha in complex with Adalimumab Fab fragment, PDB entry **3WD5**, chain **A** residues **6–157**, chain **L** residues **1–213**, chain **H** residues **1–219**, in explicit solvent.

- **TIP3P** water, neutralised
- **300 K**, **NPT** at **1 bar**
- at least **2.5 ns** of production MD

Chain A does not resolve residue 6; the range runs through them, so build them.

Chain H does not resolve residues 137, 138, 140, 141, 143; the range runs through them, so build them.

Leave the prepared structure, the topology, the minimised state and the production
trajectory as artifacts. The evaluator recomputes everything it needs from them.
