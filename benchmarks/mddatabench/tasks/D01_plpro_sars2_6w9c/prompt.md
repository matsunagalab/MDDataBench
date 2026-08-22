# Task D01

Simulate SARS-CoV-2 papain-like protease, PDB entry **6W9C**, chain **C**,
**residues 4–315**, in explicit solvent.

- **Amber ff14SB** protein force field, **TIP3P** water, neutralised
- **298 K**, **NPT**
- at least **1 ns** of production MD

The entry carries a structural zinc. Keep it.

Chain C does not resolve residue 315; the construct runs to it, so build it.

Leave the prepared structure, the topology, the minimised state and the production
trajectory as artifacts. The evaluator recomputes everything it needs from them.
