# Task 022_antibody_3rvw

Simulate the deposited system, PDB entry **3RVW**, chain **A** residues **1–222**, chain **C** residues **1–211**, chain **D** residues **1–222**, in explicit solvent.

- **TIP3P** water, neutralised
- **300 K**, **NPT** at **1 bar**
- at least **2.5 ns** of production MD

Chain D does not resolve residues 135, 136, 137, 138; the range runs through them, so build them.

Residue 52 is deposited as **ASN**, a modified ASN. Simulate the unmodified residue.

Leave the prepared structure, the topology, the minimised state and the production
trajectory as artifacts. The evaluator recomputes everything it needs from them.
