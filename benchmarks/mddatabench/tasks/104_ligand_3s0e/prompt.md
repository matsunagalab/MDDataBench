# Task 104_ligand_3s0e

Simulate OBP14, PDB entry **3S0E**, chain **A** residues **1–119**, in explicit solvent.

- **Amber ff99SB-ILDN** protein force field, **TIP3P** water, neutralised
- **298 K**, **NPT** at **1 bar**
- at least **1 ns** of production MD
- neutral pH; ionisation states of the side chains are your choice
- Include the **EOL** ligand bound to the protein, and treat it as having expected formal net charge **0** at pH 7

Leave the prepared structure, the topology, the minimised state and the production
trajectory as artifacts. The evaluator recomputes everything it needs from them.
