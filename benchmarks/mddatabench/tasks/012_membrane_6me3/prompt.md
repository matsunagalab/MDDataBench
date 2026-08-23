# Task 012_membrane_6me3

Simulate chimera protein of Melatonin receptor type 1A and GlgA glycogen, PDB entry **6ME3**, chain **A** residues **23–218** and **1001–1196** and **228–318**, in explicit solvent.

- **TIP3P** water, neutralised
- **310 K**, **NPT** at **1 bar**
- at least **1 ns** of production MD

Residue 1003 of chain A is not part of the reference. Leave it out.

Residue 1004 is deposited as **YCM**, a modified CYS. Simulate the unmodified residue.

Leave the prepared structure, the topology, the minimised state and the production
trajectory as artifacts. The evaluator recomputes everything it needs from them.
