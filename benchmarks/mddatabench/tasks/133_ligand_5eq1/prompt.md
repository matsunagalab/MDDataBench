# Task 133_ligand_5eq1

Simulate Peregrin, PDB entry **5EQ1**, chain **A** residues **628–739**, in explicit solvent.

- **Amber ff99SB-ILDN** protein force field, **TIP3P** water, neutralised
- **298 K**, **NPT** at **1 bar**
- at least **1 ns** of production MD
- neutral pH; ionisation states of the side chains are your choice
- Include the **BEA** ligand bound to the protein, and treat it as having expected formal net charge **0** at pH 7

The deposit's **NO3** is not part of the reference. Simulate the protein without it.

Leave the prepared structure, the topology, the minimised state and the production
trajectory as artifacts. The evaluator recomputes everything it needs from them.
