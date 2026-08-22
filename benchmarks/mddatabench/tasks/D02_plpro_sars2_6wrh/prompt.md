# Task D02

Simulate SARS-CoV-2 papain-like protease, PDB entry **6WRH**, chain **A**,
**residues 4–315**, in explicit solvent.

- **Amber ff14SB** protein force field, **TIP3P** water, neutralised
- **298 K**, **NPT**
- at least **1 ns** of production MD

The entry carries a structural zinc. Keep it.

The deposited chain carries the **C111S** substitution, which inactivates the
enzyme for crystallography. Simulate the wild-type: residue 111 is a cysteine.

Leave the prepared structure, the topology, the minimised state and the production
trajectory as artifacts. The evaluator recomputes everything it needs from them.
