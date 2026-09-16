# Task 100_soluble_2axf

Simulate 10-mer peptide from BZLF1 trans-activator protein in complex with Beta-2-microglobulin, PDB entry **2AXF**, chain **A** residues **1–276**, chain **B** residues **1–99**, chain **C** residues **1–10**, in explicit solvent.

- **TIP3P** water, neutralised
- **300 K**, **NPT** at **1 bar**
- at least **1 ns** of production MD

Residues 3, 93, 191, 197, 260 and 263 of chain A are doubly protonated histidines (HIP); keep them that way.

Ionisation states of the other side chains are your choice.

The deposit's **ACY** is not part of the reference. Simulate the protein without it.

Leave the prepared structure, the topology, the minimised state and the production
trajectory as artifacts. The evaluator recomputes everything it needs from them.
