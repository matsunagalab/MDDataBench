# Task 029_complex_1e3u

Simulate MAD structure of OXA10 class D beta-lactamase, PDB entry **1E3U**, chain **A** residues **22–264**, chain **B** residues **22–266**, in explicit solvent.

- **TIP3P** water, neutralised
- **310 K**, **NPT** at **1 bar**
- at least **2.5 ns** of production MD

The deposit does not resolve every residue of the stated ranges. Build the ones it leaves out, including any at the start or end of a range.

Simulate every ionisable side chain in its standard state at pH 7: charged aspartate, glutamate, lysine and arginine, and neutral histidine and cysteine.

Leave the prepared structure, the topology, the minimised state and the production
trajectory as artifacts. The evaluator recomputes everything it needs from them.
