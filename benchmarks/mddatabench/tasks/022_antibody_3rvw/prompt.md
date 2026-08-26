# Task 022_antibody_3rvw

Simulate the deposited system, PDB entry **3RVW**, chain **A** residues **1–222**, chain **C** residues **1–211**, chain **D** residues **1–222**, in explicit solvent.

- **TIP3P** water, neutralised
- **300 K**, **NPT** at **1 bar**
- at least **2.5 ns** of production MD

Residue 52 is deposited as **ASN**, a modified ASN. Simulate the unmodified residue.

The deposit does not resolve every residue of the stated ranges. Build the ones it leaves out, including any at the start or end of a range.

Simulate every ionisable side chain in its standard state at pH 7: charged aspartate, glutamate, lysine and arginine, and neutral histidine and cysteine.

Leave the prepared structure, the topology, the minimised state and the production
trajectory as artifacts. The evaluator recomputes everything it needs from them.
