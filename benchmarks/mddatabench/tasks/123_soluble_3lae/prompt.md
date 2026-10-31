# Task 123_soluble_3lae

Simulate UPF0053 protein HI0107, PDB entry **3LAE**, chain **A** residues **-2–78**, in explicit solvent.

- **TIP3P** water, neutralised
- **300 K**, **NPT** at **1 bar**
- at least **1 ns** of production MD
- neutral pH; ionisation states of the side chains are your choice

Residue 8 is deposited as **MSE**, a modified MET. Simulate the unmodified residue.

Residue 22 is deposited as **MSE**, a modified MET. Simulate the unmodified residue.

Residue 69 is deposited as **MSE**, a modified MET. Simulate the unmodified residue.

The deposit's **EDO** and **PO4** are not part of the reference. Simulate the protein without them.

Leave the prepared structure, the topology, the minimised state and the production
trajectory as artifacts. The evaluator recomputes everything it needs from them.
