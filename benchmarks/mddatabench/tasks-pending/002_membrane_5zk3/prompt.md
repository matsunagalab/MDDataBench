# Task 002_membrane_5zk3

Simulate Muscarinic acetylcholine receptor M2, PDB entry **5ZK3**, chain **A** residues **18–214** and **382–458**, in explicit solvent.

- **CHARMM36** protein force field, **TIP3P** water, neutralised
- **300 K**, **NPT**
- at least **1 ns** of production MD

Chain A is deposited as a fusion: 114 residues between those ranges belong to the crystallisation partner. Simulate the protein without them.

Leave the prepared structure, the topology, the minimised state and the production
trajectory as artifacts. The evaluator recomputes everything it needs from them.
