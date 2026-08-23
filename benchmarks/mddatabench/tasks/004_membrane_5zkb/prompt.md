# Task 004_membrane_5zkb

Simulate Muscarinic acetylcholine receptor M2, PDB entry **5ZKB**, chain **A** residues **17–217** and **377–456**, in explicit solvent.

- **CHARMM36** protein force field, **TIP3P** water, neutralised
- **300 K**, **NPT**
- at least **1 ns** of production MD

Chain A is deposited as a fusion: 159 residues between those ranges belong to the crystallisation partner. Simulate the protein without them.

1 residue(s) of that range are not resolved in the deposit. Build them.

Leave the prepared structure, the topology, the minimised state and the production
trajectory as artifacts. The evaluator recomputes everything it needs from them.
