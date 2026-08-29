# Task 042_ligand_4mn3

Simulate Chromobox protein homolog 7, PDB entry **4MN3**, chain **A** residues **1–56**, in explicit solvent.

- **Amber ff99SB-ILDN** protein force field, **TIP3P** water, neutralised
- **298 K**, **NPT** at **1 bar**
- at least **1 ns** of production MD

Include one extra component named **LIG** bound to the protein. It is **Ac-Phe-Ala-Tyr-Nε-trimethyl-Lys-Ser-NH2**, with formula **C35H52N7O8**, expected formal net charge **+1**, and SMILES `CC(=O)N[C@@H](Cc1ccccc1)C(=O)N[C@@H](C)C(=O)N[C@@H](Cc1ccc(O)cc1)C(=O)N[C@@H](CCCC[N+](C)(C)C)C(=O)N[C@@H](CO)C(N)=O`.

Use the deposited coordinates of chain B positions 1–7 (**ACE–PHE–ALA–TYR–M3L–SER–NH2**) as its placement source. Represent the whole capped peptide as one LIG residue, not as separate residues or caps.

Simulate every ionisable side chain in its standard state at pH 7: charged aspartate, glutamate, lysine and arginine, and neutral histidine and cysteine.

Leave the prepared structure, the topology, the minimised state and the production
trajectory as artifacts. The evaluator recomputes everything it needs from them.
