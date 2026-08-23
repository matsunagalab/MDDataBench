# Task 019_antibody_2dd8

Simulate Crystal Structure of SARS-CoV Spike Receptor-Binding Domain Complexed, PDB entry **2DD8**, chain **H** residues **2–216**, chain **L** residues **2–213**, chain **S** residues **321–512**, in explicit solvent.

- **TIP3P** water, neutralised
- **300 K**, **NPT** at **1 bar**
- at least **2.5 ns** of production MD

Residue 330 is deposited as **ASN**, a modified ASN. Simulate the unmodified residue.

Simulate every ionisable side chain in its standard state at pH 7: charged aspartate, glutamate, lysine and arginine, and neutral histidine and cysteine.

Leave the prepared structure, the topology, the minimised state and the production
trajectory as artifacts. The evaluator recomputes everything it needs from them.
