# Task 008_membrane_6i53

Simulate Gamma-aminobutyric acid receptor subunit gamma-2 in complex with Gamma-aminobutyric acid receptor subunit alpha-1, PDB entry **6I53**, chain **E** residues **8–312** and **10–312** and **418–447**, chain **B** residues **418–447**, chain **A** residues **10–323** and **384–418**, chain **C** residues **28–323** and **406–436**, chain **D** residues **10–322** and **384–417**, in explicit solvent.

- **CHARMM36** protein force field, **TIP3P** water, neutralised
- **310 K**, **NPT**
- at least **1 ns** of production MD

Chain E is deposited as a fusion: 105 residues between those ranges belong to the crystallisation partner. Simulate the protein without them.

8 residue(s) of that range are not resolved in the deposit. Build them.

4 residue(s) of that range are not resolved in the deposit. Build them.

Chain A is deposited as a fusion: 60 residues between those ranges belong to the crystallisation partner. Simulate the protein without them.

Chain C is deposited as a fusion: 82 residues between those ranges belong to the crystallisation partner. Simulate the protein without them.

10 residue(s) of that range are not resolved in the deposit. Build them.

Chain D is deposited as a fusion: 61 residues between those ranges belong to the crystallisation partner. Simulate the protein without them.

Leave the prepared structure, the topology, the minimised state and the production
trajectory as artifacts. The evaluator recomputes everything it needs from them.
