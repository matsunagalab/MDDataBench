# Task 006_membrane_6a94

Simulate 5-hydroxytryptamine receptor 2A, PDB entry **6A94**, chain **A** residues **69–265** and **313–399**, in explicit solvent.

- **CHARMM36** protein force field, **TIP3P** water, neutralised
- **300 K**, **NPT**
- at least **1 ns** of production MD

Chain A is deposited as a fusion: 86 residues between those ranges belong to the crystallisation partner. Simulate the protein without them.

Leave the prepared structure, the topology, the minimised state and the production
trajectory as artifacts. The evaluator recomputes everything it needs from them.
