# Task 020_antibody_2vis

Simulate INFLUENZA VIRUS HEMAGGLUTININ, PDB entry **2VIS**, chain **A** residues **1–210**, chain **B** residues **1–221**, chain **C** residues **43–309**, in explicit solvent.

- **TIP3P** water, neutralised
- **300 K**, **NPT** at **1 bar**
- at least **2.5 ns** of production MD

Residue 81 is deposited as **ASN**, a modified ASN. Simulate the unmodified residue.

Simulate every ionisable side chain in its standard state at pH 7: charged aspartate, glutamate, lysine and arginine, and neutral histidine and cysteine.

Leave the prepared structure, the topology, the minimised state and the production
trajectory as artifacts. The evaluator recomputes everything it needs from them.
