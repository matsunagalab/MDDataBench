# Task 008_membrane_6i53

Simulate Gamma-aminobutyric acid receptor subunit gamma-2 in complex with Gamma-aminobutyric acid receptor subunit alpha-1, PDB entry **6I53**, chain **E** residues **10–312** and **418–447**, chain **A** residues **10–323** and **384–418**, chain **B** residues **8–312** and **418–447**, chain **C** residues **28–323** and **406–436**, chain **D** residues **10–322** and **384–417**, in explicit solvent.

- **TIP3P** water, neutralised
- **310 K**, **NPT** at **1 bar**
- at least **1 ns** of production MD

Chain E is deposited as a fusion: 105 residues between those ranges belong to the crystallisation partner. Simulate the protein without them.

Chain E does not resolve residue 10; the range runs through them, so build them.

Chain A is deposited as a fusion: 60 residues between those ranges belong to the crystallisation partner. Simulate the protein without them.

Join the pieces of chain A into a single continuous chain, bonded where the removed part was.

Chain B is deposited as a fusion: 105 residues between those ranges belong to the crystallisation partner. Simulate the protein without them.

Chain B does not resolve residue 8; the range runs through them, so build them.

Chain C is deposited as a fusion: 82 residues between those ranges belong to the crystallisation partner. Simulate the protein without them.

Chain C does not resolve residues 28, 29, 30, 31, 32, 34; the range runs through them, so build them.

Chain D is deposited as a fusion: 61 residues between those ranges belong to the crystallisation partner. Simulate the protein without them.

Join the pieces of chain D into a single continuous chain, bonded where the removed part was.

Embed it in a **DPPC** bilayer.

Leave the prepared structure, the topology, the minimised state and the production
trajectory as artifacts. The evaluator recomputes everything it needs from them.
