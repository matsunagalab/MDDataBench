# Task 011_membrane_6kuy

Simulate Alpha2A adrenergic receptor, PDB entry **6KUY**, chain **A** residues **35–227** and **365–443**, in explicit solvent.

- **TIP3P** water, neutralised
- **310 K**, **NPT** at **1 bar**
- at least **1 ns** of production MD

Chain A is deposited as a fusion: 137 residues between those ranges belong to the crystallisation partner. Simulate the protein without them.

Chain A does not resolve residues 37, 36; the range runs through them, so build them.

Residue 173–182 of chain A is not part of the reference. Leave it out.

Embed it in a **DPPC** bilayer.

Leave the prepared structure, the topology, the minimised state and the production
trajectory as artifacts. The evaluator recomputes everything it needs from them.
