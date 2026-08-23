# Task 013_membrane_6ps2

Simulate Fusion protein of Beta-2 adrenergic receptor and T4 Lysozyme, PDB entry **6PS2**, chain **A** residues **28–230** and **263–342**, in explicit solvent.

- **TIP3P** water, neutralised
- **310 K**, **NPT** at **1 bar**
- at least **1 ns** of production MD

Chain A is deposited as a fusion: 160 residues between those ranges belong to the crystallisation partner. Simulate the protein without them.

Embed it in a **DPPC** bilayer.

Leave the prepared structure, the topology, the minimised state and the production
trajectory as artifacts. The evaluator recomputes everything it needs from them.
