# Task 048_nucleic_1h9t

Simulate 5'-D(*GP*AP*TP*CP*TP*GP*GP*TP*CP*GP*TP*AP* CP*CP*AP*GP*AP*TP*G)-3' in complex with 5'-D(*CP*AP*TP*CP*TP*GP*GP*TP*AP*CP*GP*AP* CP*CP*AP*GP*AP*TP*C)-3', PDB entry **1H9T**, chain **X** residues **1–19**, chain **Y** residues **1–19**, in explicit solvent.

- **TIP3P** water, neutralised
- **300 K**, **NPT** at **1 bar**
- at least **1 ns** of production MD

Simulate every ionisable side chain in its standard state at pH 7: charged aspartate, glutamate, lysine and arginine, and neutral histidine and cysteine.

Leave the prepared structure, the topology, the minimised state and the production
trajectory as artifacts. The evaluator recomputes everything it needs from them.
