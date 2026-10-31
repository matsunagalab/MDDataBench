# Task 131_ligand_2pql

Simulate D7r4 protein, PDB entry **2PQL**, chain **A** residues **1–144**, in explicit solvent.

- **Amber ff99SB-ILDN** protein force field, **TIP3P** water, neutralised
- **298 K**, **NPT** at **1 bar**
- at least **1 ns** of production MD
- neutral pH; ionisation states of the side chains are your choice
- Include the **TSS** ligand bound to the protein, and treat it as having expected formal net charge **+1** at pH 7

Leave the prepared structure, the topology, the minimised state and the production
trajectory as artifacts. The evaluator recomputes everything it needs from them.
