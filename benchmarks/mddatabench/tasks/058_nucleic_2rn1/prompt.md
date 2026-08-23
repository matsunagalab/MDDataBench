# Task 058_nucleic_2rn1

Simulate RNA (5'-R(P*GP*CP*UP*GP*GP*UP*CP*CP*CP*AP*GP*AP*CP*AP*GP*C)-3') in complex with RNA (5'-R(P*GP*AP*GP*CP*CP*CP*UP*GP*GP*GP*AP*GP*GP*CP*UP*C)-3'), PDB entry **2RN1**, chain **A** residues **1–16**, chain **B** residues **17–32**, in explicit solvent.

- **TIP3P** water, neutralised
- **300 K**, **NPT** at **1 bar**
- at least **1 ns** of production MD

Simulate every ionisable side chain in its standard state at pH 7: charged aspartate, glutamate, lysine and arginine, and neutral histidine and cysteine.

Leave the prepared structure, the topology, the minimised state and the production
trajectory as artifacts. The evaluator recomputes everything it needs from them.
