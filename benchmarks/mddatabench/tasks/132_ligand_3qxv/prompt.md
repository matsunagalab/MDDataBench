# Task 132_ligand_3qxv

Simulate Anti-Methotrexate CDR1-4 Graft VHH, PDB entry **3QXV**, chain **A** residues **4–131**, in explicit solvent.

- **Amber ff99SB-ILDN** protein force field, **TIP3P** water, neutralised
- **298 K**, **NPT** at **1 bar**
- at least **1 ns** of production MD
- neutral pH; ionisation states of the side chains are your choice
- Include the **MTX** ligand bound to the protein, and treat it as having expected formal net charge **-2** at pH 7

The deposit's **SO4** is not part of the reference. Simulate the protein without it.

Leave the prepared structure, the topology, the minimised state and the production
trajectory as artifacts. The evaluator recomputes everything it needs from them.
