# Task 069_soluble_1aol

Simulate GP70, PDB entry **1AOL**, chain **A** residues **9–236**, in explicit solvent.

- **TIP3P** water, neutralised
- **300 K**, **NPT** at **1 bar**
- at least **1 ns** of production MD
- neutral pH; ionisation states of the side chains are your choice

Residue 168 (ASN) carries an N-linked glycan in the deposit (a glycosylation site). Simulate the unmodified residue without the glycan: leave the sugar residues bonded to it out.

Residue 12 (ASN) carries an N-linked glycan in the deposit (a glycosylation site). Simulate the unmodified residue without the glycan: leave the sugar residues bonded to it out.

The deposit's **ZN** is not part of the reference. Simulate the protein without it.

Leave the prepared structure, the topology, the minimised state and the production
trajectory as artifacts. The evaluator recomputes everything it needs from them.
