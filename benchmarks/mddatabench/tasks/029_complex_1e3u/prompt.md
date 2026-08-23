# Task 029_complex_1e3u

Simulate MAD structure of OXA10 class D beta-lactamase, PDB entry **1E3U**, chain **A** residues **22–264**, chain **B** residues **22–266**, in explicit solvent.

- **TIP3P** water, neutralised
- **310 K**, **NPT** at **1 bar**
- at least **2.5 ns** of production MD

Chain B does not resolve residues 265, 266; the range runs through them, so build them.

Simulate every ionisable side chain in its standard state at pH 7: charged aspartate, glutamate, lysine and arginine, and neutral histidine and cysteine.

Leave the prepared structure, the topology, the minimised state and the production
trajectory as artifacts. The evaluator recomputes everything it needs from them.
