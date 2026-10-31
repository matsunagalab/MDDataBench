# Task 102_ligand_4mre

Simulate CD44 antigen, PDB entry **4MRE**, chain **A** residues **24–173**, in explicit solvent.

- **Amber ff99SB-ILDN** protein force field, **TIP3P** water, neutralised
- **298 K**, **NPT** at **1 bar**
- at least **1 ns** of production MD
- neutral pH; ionisation states of the side chains are your choice
- Include the **2C9** ligand bound to the protein, and treat it as having expected formal net charge **0** at pH 7

The deposit's **DMS** is not part of the reference. Simulate the protein without it.

Leave the prepared structure, the topology, the minimised state and the production
trajectory as artifacts. The evaluator recomputes everything it needs from them.
