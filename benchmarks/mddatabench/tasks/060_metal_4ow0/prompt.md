# Task 060_metal_4ow0

Simulate papain-like protease, PDB entry **4OW0**, chain **A** residues **4–315**, in explicit solvent.

- **Amber ff14SB** protein force field, **TIP3P** water, neutralised
- **298 K**, **NPT** at **1 bar**
- at least **1 ns** of production MD
- neutral pH; ionisation states of the side chains are your choice

Residue 112 is deposited as **OCS**, a modified CYS. Simulate the unmodified residue.

The entry carries a structural zinc. Keep it.

The deposit's **DMS**, **GOL** and **S88** are not part of the reference. Simulate the protein without them.

Leave the prepared structure, the topology, the minimised state and the production
trajectory as artifacts. The evaluator recomputes everything it needs from them.
