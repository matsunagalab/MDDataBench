# Task 004_membrane_5zkb

Simulate Muscarinic acetylcholine receptor M2, PDB entry **5ZKB**, chain **A** residues **17–217** and **377–456**, in explicit solvent.

- **TIP3P** water, neutralised
- **300 K**, **NPT** at **1 bar**
- at least **1 ns** of production MD

Chain A is deposited as a fusion: 159 residues between those ranges belong to the crystallisation partner. Simulate the protein without them.

Keep chain A residues 217 and 377 as separate termini; do not create a peptide bond between A:217 C and A:377 N.

Embed it in a **DPPC** bilayer.

Simulate every ionisable side chain in its standard state at pH 7: charged aspartate, glutamate, lysine and arginine, and neutral histidine and cysteine.

Leave the prepared structure, the topology, the minimised state and the production
trajectory as artifacts. The evaluator recomputes everything it needs from them.
