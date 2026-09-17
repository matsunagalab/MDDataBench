# Task 019_antibody_2dd8

Simulate Crystal Structure of SARS-CoV Spike Receptor-Binding Domain Complexed, PDB entry **2DD8**, chain **H** residues **2–216**, chain **L** residues **2–213**, chain **S** residues **321–512**, in explicit solvent.

- **TIP3P** water, neutralised
- **300 K**, **NPT** at **1 bar**
- at least **2.5 ns** of production MD
- neutral pH; ionisation states of the side chains are your choice

Residue 330 (ASN) carries an N-linked glycan in the deposit (a glycosylation site). Simulate the unmodified residue without the glycan: leave the sugar residues bonded to it out.

The deposit's **PO4** is not part of the reference. Simulate the protein without it.

Leave the prepared structure, the topology, the minimised state and the production
trajectory as artifacts. The evaluator recomputes everything it needs from them.
