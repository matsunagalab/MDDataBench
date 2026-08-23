# Task 021_antibody_3eoa

Simulate Crystal structure the Fab fragment of Efalizumab in complex with, PDB entry **3EOA**, chain **L** residues **1–214**, chain **H** residues **1–220**, chain **I** residues **128–306**, in explicit solvent.

- **TIP3P** water, neutralised
- **300 K**, **NPT** at **1 bar**
- at least **2.5 ns** of production MD

Chain H does not resolve residues 137, 138, 140, 141, 143; the range runs through them, so build them.

Leave the prepared structure, the topology, the minimised state and the production
trajectory as artifacts. The evaluator recomputes everything it needs from them.
