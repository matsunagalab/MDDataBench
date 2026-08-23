# Task 003_membrane_5zk8

Simulate Muscarinic acetylcholine receptor M2, PDB entry **5ZK8**, chain **A** residues **18–214** and **383–458**, in explicit solvent.

- **TIP3P** water, neutralised
- **300 K**, **NPT** at **1 bar**
- at least **1 ns** of production MD

Chain A is deposited as a fusion: 115 residues between those ranges belong to the crystallisation partner. Simulate the protein without them.

Join the pieces of chain A into a single continuous chain, bonded where the removed part was.

Embed it in a **DPPC** bilayer.

Leave the prepared structure, the topology, the minimised state and the production
trajectory as artifacts. The evaluator recomputes everything it needs from them.
