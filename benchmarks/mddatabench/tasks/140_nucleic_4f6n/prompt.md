# Task 140_nucleic_4f6n

Simulate DNA in complex with DNA, PDB entry **4F6N**, chain **E** residues **20–38**, chain **D** residues **1–19**, in explicit solvent.

- **TIP3P** water, neutralised
- **300 K**, **NPT** at **1 bar**
- at least **1 ns** of production MD
- neutral pH; ionisation states of the side chains are your choice

Chain E does not resolve residue 20; the range runs through them, so build them.

Residue 8 is deposited as **5CM**, a modified DC. Simulate the unmodified residue.

Residue 10 is deposited as **5CM**, a modified DC. Simulate the unmodified residue.

Residue 28 is deposited as **5CM**, a modified DC. Simulate the unmodified residue.

Residue 30 is deposited as **5CM**, a modified DC. Simulate the unmodified residue.

The deposit's **GOL** is not part of the reference. Simulate the nucleic acid without it.

Leave the prepared structure, the topology, the minimised state and the production
trajectory as artifacts. The evaluator recomputes everything it needs from them.
