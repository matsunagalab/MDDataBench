# Task 029_complex_1e3u

Simulate MAD structure of OXA10 class D beta-lactamase, PDB entry **1E3U**, chain **A** residues **22–264**, chain **C** residues **22–266**, in explicit solvent.

- **TIP3P** water, neutralised
- **310 K**, **NPT** at **1 bar**
- at least **2.5 ns** of production MD
- neutral pH; ionisation states of the side chains are your choice

Chain C does not resolve residues 94, 95, 96; the range runs through them, so build them.

The deposit's **AUC**, **EDO** and **SO4** are not part of the reference. Simulate the protein without them.

Leave the prepared structure, the topology, the minimised state and the production
trajectory as artifacts. The evaluator recomputes everything it needs from them.
