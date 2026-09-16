# Task 022_antibody_3rvw

Simulate the deposited system, PDB entry **3RVW**, chain **A** residues **1–222**, chain **C** residues **1–211**, chain **D** residues **1–222**, in explicit solvent.

- **TIP3P** water, neutralised
- **300 K**, **NPT** at **1 bar**
- at least **2.5 ns** of production MD
- neutral pH; ionisation states of the side chains are your choice

Chain D does not resolve residues 135, 136, 137, 138; the range runs through them, so build them.

Residue 52 (ASN) carries an N-linked glycan in the deposit (a glycosylation site). Simulate the unmodified residue without the glycan: leave the sugar residues bonded to it out.

The deposit's **CA** and **EDO** are not part of the reference. Simulate the protein without them.

Leave the prepared structure, the topology, the minimised state and the production
trajectory as artifacts. The evaluator recomputes everything it needs from them.
