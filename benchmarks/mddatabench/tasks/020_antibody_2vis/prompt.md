# Task 020_antibody_2vis

Simulate INFLUENZA VIRUS HEMAGGLUTININ, PDB entry **2VIS**, chain **A** residues **1–210**, chain **B** residues **1–221**, chain **C** residues **43–309**, in explicit solvent.

- **TIP3P** water, neutralised
- **300 K**, **NPT** at **1 bar**
- at least **2.5 ns** of production MD
- neutral pH; ionisation states of the side chains are your choice

Residue 81 (ASN) carries an N-linked glycan in the deposit (a glycosylation site). Simulate the unmodified residue without the glycan: leave the sugar residues bonded to it out.

The deposit's **ZN** is not part of the reference. Simulate the protein without it.

Leave the prepared structure, the topology, the minimised state and the production
trajectory as artifacts. The evaluator recomputes everything it needs from them.
