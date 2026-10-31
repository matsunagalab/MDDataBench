# Task 101_membrane_7dfp

Simulate D(2) dopamine receptor, PDB entry **7DFP**, chain **A** residues **35–216** and **364–442**, in explicit solvent.

- **TIP3P** water, neutralised
- **310 K**, **NPT** at **1 bar**
- at least **1 ns** of production MD
- neutral pH; ionisation states of the side chains are your choice

Chain A is deposited as a fusion: 90 residues between those ranges belong to the crystallisation partner. Simulate the protein without them.

Residue 141–147 of chain A is not part of the reference. Leave it out.

Keep chain A residues 140 and 148 as separate termini; do not create a peptide bond between A:140 C and A:148 N.

Connect chain A residue 216 C to residue 364 N with a peptide bond across the omitted A:217-363 span.

Embed it in a **DPPC** bilayer.

The deposit's **SIP** is not part of the reference. Simulate the protein without it.

Leave the prepared structure, the topology, the minimised state and the production
trajectory as artifacts. The evaluator recomputes everything it needs from them.
