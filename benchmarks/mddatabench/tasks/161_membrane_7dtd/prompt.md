# Task 161_membrane_7dtd

Simulate Sodium channel protein type 1 subunit alpha, PDB entry **7DTD**, chain **A** residues **116–439** and **749–996** and **1201–1795**, in explicit solvent.

- **TIP3P** water, neutralised
- **310 K**, **NPT** at **1 bar**
- at least **1 ns** of production MD
- neutral pH; ionisation states of the side chains are your choice

Residue 283–311 of chain A is not part of the reference. Leave it out.

Residue 440–748 of chain A is not part of the reference. Leave it out.

Residue 997–1200 of chain A is not part of the reference. Leave it out.

Keep chain A residues 282 and 312 as separate termini; do not create a peptide bond between A:282 C and A:312 N.

Keep chain A residues 439 and 749 as separate termini; do not create a peptide bond between A:439 C and A:749 N.

Keep chain A residues 996 and 1201 as separate termini; do not create a peptide bond between A:996 C and A:1201 N.

Embed it in a **DPPC** bilayer.

The deposit's **9Z9** and **NAG** are not part of the reference. Simulate the protein without them.

Leave the prepared structure, the topology, the minimised state and the production
trajectory as artifacts. The evaluator recomputes everything it needs from them.
