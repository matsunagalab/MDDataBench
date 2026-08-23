# Task 053_nucleic_1qn5

Simulate DNA (5'-D(*TP*GP*CP*CP*CP*TP*CP*TP*TP*AP*TP*AP*GP*C)-3') in complex with DNA (5'-D(*GP*CP*TP*AP*TP*AP*AP*GP*AP*GP*GP*GP*CP*A)-3'), PDB entry **1QN5**, chain **D** residues **215–228**, chain **C** residues **201–214**, in explicit solvent.

- **TIP3P** water, neutralised
- **300 K**, **NPT** at **1 bar**
- at least **1 ns** of production MD

Simulate every ionisable side chain in its standard state at pH 7: charged aspartate, glutamate, lysine and arginine, and neutral histidine and cysteine.

Leave the prepared structure, the topology, the minimised state and the production
trajectory as artifacts. The evaluator recomputes everything it needs from them.
