# Task 159_soluble_1cs6

Simulate AXONIN-1, PDB entry **1CS6**, chain **A** residues **7–388**, in explicit solvent.

- **TIP3P** water, neutralised
- **300 K**, **NPT** at **1 bar**
- at least **1 ns** of production MD

Residues 134 and 186 of chain A are doubly protonated histidines (HIP); keep them that way.

Ionisation states of the other side chains are your choice.

The deposit's **GOL** is not part of the reference. Simulate the protein without it.

Leave the prepared structure, the topology, the minimised state and the production
trajectory as artifacts. The evaluator recomputes everything it needs from them.
