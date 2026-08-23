# Task 001_membrane_5yc8

Simulate Muscarinic acetylcholine receptor M2, PDB entry **5YC8**, chain **A** residues **16–214** and **380–458**, in explicit solvent.

- **TIP3P** water, neutralised
- **300 K**, **NPT** at **1 bar**
- at least **1 ns** of production MD

Chain A is deposited as a fusion: 165 residues between those ranges belong to the crystallisation partner. Simulate the protein without them.

Chain A does not resolve residue 16; the range runs through them, so build them.

Embed it in a **DPPC** bilayer.

Leave the prepared structure, the topology, the minimised state and the production
trajectory as artifacts. The evaluator recomputes everything it needs from them.
