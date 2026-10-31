# Task 151_soluble_2x9o

Simulate 15,16-DIHYDROBILIVERDIN-FERREDOXIN OXIDOREDUCTASE, PDB entry **2X9O**, chain **A** residues **-7–236**, in explicit solvent.

- **TIP3P** water, neutralised
- **300 K**, **NPT** at **1 bar**
- at least **1 ns** of production MD
- neutral pH; ionisation states of the side chains are your choice

Chain A does not resolve residues -7, -6, -5, -4, -3, -2, 128, 129, 234, 235, 236; the range runs through them, so build them.

Residue 81 is deposited as **MSE**, a modified MET. Simulate the unmodified residue.

Residue 133 is deposited as **MSE**, a modified MET. Simulate the unmodified residue.

The deposit's **BLA** is not part of the reference. Simulate the protein without it.

Leave the prepared structure, the topology, the minimised state and the production
trajectory as artifacts. The evaluator recomputes everything it needs from them.
