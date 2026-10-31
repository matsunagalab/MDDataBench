# Task 146_antibody_5o14

Simulate Fab 1A12 Light Chain in complex with Fab 1A12 Heavy Chain, PDB entry **5O14**, chain **B** residues **14–255**, chain **D** residues **1–212**, chain **C** residues **1–222**, in explicit solvent.

- **TIP3P** water, neutralised
- **300 K**, **NPT** at **1 bar**
- at least **2.5 ns** of production MD
- neutral pH; ionisation states of the side chains are your choice

Chain B does not resolve residues 14, 83, 84, 85, 86, 87, 117, 118, 119, 120, 121, 122; the range runs through them, so build them.

The deposit's **CL** is not part of the reference. Simulate the protein without it.

Leave the prepared structure, the topology, the minimised state and the production
trajectory as artifacts. The evaluator recomputes everything it needs from them.
