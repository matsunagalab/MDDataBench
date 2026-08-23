# Task 049_nucleic_1iv6

Simulate 5'-D(*CP*CP*CP*TP*AP*AP*CP*CP*CP*TP*AP*AP*C)-3' in complex with 5'-D(*GP*TP*TP*AP*GP*GP*GP*TP*TP*AP*GP*GP*G)-3', PDB entry **1IV6**, chain **C** residues **14–26**, chain **B** residues **1–13**, in explicit solvent.

- **TIP3P** water, neutralised
- **300 K**, **NPT** at **1 bar**
- at least **1 ns** of production MD

Simulate every ionisable side chain in its standard state at pH 7: charged aspartate, glutamate, lysine and arginine, and neutral histidine and cysteine.

Leave the prepared structure, the topology, the minimised state and the production
trajectory as artifacts. The evaluator recomputes everything it needs from them.
