# Task 011_membrane_6kuy

Simulate Alpha2A adrenergic receptor, PDB entry **6KUY**, chain **A** residues **33–227** and **365–443**, in explicit solvent.

- **TIP3P** water, neutralised
- **310 K**, **NPT** at **1 bar**
- at least **1 ns** of production MD
- neutral pH; ionisation states of the side chains are your choice

Chain A is deposited as a fusion: 137 residues between those ranges belong to the crystallisation partner. Simulate the protein without them.

Residue 173–182 of chain A is not part of the reference. Leave it out.

Keep chain A residues 172 and 183 as separate termini; do not create a peptide bond between A:172 C and A:183 N.

Keep chain A residues 227 and 365 as separate termini; do not create a peptide bond between A:227 C and A:365 N.

Embed it in a **DPPC** bilayer.

The deposit's **E39** and **PEG** are not part of the reference. Simulate the protein without them.

Leave the prepared structure, the topology, the minimised state and the production
trajectory as artifacts. The evaluator recomputes everything it needs from them.
