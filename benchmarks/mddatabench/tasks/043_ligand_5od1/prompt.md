# Task 043_ligand_5od1

Simulate MID1sc10, PDB entry **5OD1**, chain **A** residues **3–94**, in explicit solvent.

- **Amber ff99SB-ILDN** protein force field, **TIP3P** water, neutralised
- **298 K**, **NPT** at **1 bar**
- at least **1 ns** of production MD

Chain A does not resolve residues 3, 2; the range runs through them, so build them.

Leave the prepared structure, the topology, the minimised state and the production
trajectory as artifacts. The evaluator recomputes everything it needs from them.
