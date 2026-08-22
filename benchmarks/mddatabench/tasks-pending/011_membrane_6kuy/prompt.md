# Task 011_membrane_6kuy

Simulate Alpha2A adrenergic receptor, PDB entry **6KUY**, chain **A** residues **35–227** and **365–443**, in explicit solvent.

- **CHARMM36** protein force field, **TIP3P** water, neutralised
- **310 K**, **NPT**
- at least **1 ns** of production MD

Chain A is deposited as a fusion: 137 residues between those ranges belong to the crystallisation partner. Simulate the protein without them.

3 residue(s) of that range are not resolved in the deposit. Build them.

Residue 173–182 of chain A is not part of the reference. Leave it out.

Leave the prepared structure, the topology, the minimised state and the production
trajectory as artifacts. The evaluator recomputes everything it needs from them.
