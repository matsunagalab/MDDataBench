# Task 044_ligand_5oh3

Simulate Cereblon isoform 4, PDB entry **5OH3**, chain **A** residues **19–123**, in explicit solvent.

- **Amber ff99SB-ILDN** protein force field, **TIP3P** water, neutralised
- **298 K**, **NPT** at **1 bar**
- at least **1 ns** of production MD
- Include the **9V2** ligand bound to the protein, and treat it as having expected formal net charge **0** at pH 7

Simulate every ionisable side chain in its standard state at pH 7: charged aspartate, glutamate, lysine and arginine, and neutral histidine and cysteine.

Leave the prepared structure, the topology, the minimised state and the production
trajectory as artifacts. The evaluator recomputes everything it needs from them.
