# Task 001_membrane_5yc8

Simulate Muscarinic acetylcholine receptor M2, PDB entry **5YC8**, chain **A** residues **16–214** and **380–458**, in explicit solvent.

- **TIP3P** water, neutralised
- **300 K**, **NPT** at **1 bar**
- at least **1 ns** of production MD
- neutral pH; ionisation states of the side chains are your choice

Chain A is deposited as a fusion: 165 residues between those ranges belong to the crystallisation partner. Simulate the protein without them.

Keep chain A residues 214 and 380 as separate termini; do not create a peptide bond between A:214 C and A:380 N.

Embed it in a **DPPC** bilayer.

The deposit's **3C0** and **HG** are not part of the reference. Simulate the protein without them.

Leave the prepared structure, the topology, the minimised state and the production
trajectory as artifacts. The evaluator recomputes everything it needs from them.
