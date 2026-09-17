# Task 009_membrane_6jzh

Simulate Adenosine receptor A2a, PDB entry **6JZH**, chain **A** residues **-1–308**, in explicit solvent.

- **TIP3P** water, neutralised
- **310 K**, **NPT** at **1 bar**
- at least **1 ns** of production MD

Residue 209–218 of chain A is not part of the reference. Leave it out.

Keep chain A residues 208 and 219 as separate termini; do not create a peptide bond between A:208 C and A:219 N.

Embed it in a **DPPC** bilayer.

Residue 264 of chain A is a doubly protonated histidine (HIP); keep it that way.

Ionisation states of the other side chains are your choice.

The deposit's **CLR**, **NA**, **OLA** and **ZMA** are not part of the reference. Simulate the protein without them.

Leave the prepared structure, the topology, the minimised state and the production
trajectory as artifacts. The evaluator recomputes everything it needs from them.
