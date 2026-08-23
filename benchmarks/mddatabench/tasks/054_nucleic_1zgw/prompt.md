# Task 054_nucleic_1zgw

Simulate 5'-D(*TP*CP*TP*TP*GP*CP*GP*CP*TP*TP*TP*AP*AP*TP*TP*TP*GP*C)-3' in complex with 5'-D(*GP*CP*AP*AP*AP*TP*TP*AP*AP*AP*GP*CP*GP*CP*AP*AP*GP*A)-3', PDB entry **1ZGW**, chain **B** residues **190–207**, chain **C** residues **221–238**, in explicit solvent.

- **TIP3P** water, neutralised
- **300 K**, **NPT** at **1 bar**
- at least **1 ns** of production MD

Simulate every ionisable side chain in its standard state at pH 7: charged aspartate, glutamate, lysine and arginine, and neutral histidine and cysteine.

Leave the prepared structure, the topology, the minimised state and the production
trajectory as artifacts. The evaluator recomputes everything it needs from them.
