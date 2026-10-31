# Task 106_metal_6rnt

Simulate RIBONUCLEASE T1, PDB entry **6RNT**, chain **A** residues **1–104**, in explicit solvent.

- **Amber ff99SB-ILDN** protein force field, **TIP3P** water, neutralised
- **298 K**, **NPT** at **1 bar**
- at least **1 ns** of production MD
- neutral pH; ionisation states of the side chains are your choice
- Include the **2AM** ligand bound to the protein, and treat it as having expected formal net charge **-2** at pH 7

The entry carries a structural calcium. Keep it.

Leave the prepared structure, the topology, the minimised state and the production
trajectory as artifacts. The evaluator recomputes everything it needs from them.
