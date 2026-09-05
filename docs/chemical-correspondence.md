# Chemical correspondence contract

Pass criteria are fixed independently of final MD scores: relabeling/reordering
the same ligand must preserve the contract atoms and measured observables;
isomers, missing/extra atoms or bonds and inverted stereochemistry must not pass.
Reference atom indices, reference hashes, calibration and score thresholds stay
unchanged. A correspondence repair makes a measurement evaluable, not correct.

Polymer residue pairing and backbone naming retain the existing behavior.
For non-polymer contract atoms, including same-name matches, the evaluator uses
the matched component's unique `reference.extra_components` isomeric SMILES.
RDKit and NetworkX are required for this path. Without declared chemistry or
usable topology it reports unevaluable; there is no name-only rescue.

The independent evidence is the reference topology bond list and the submitted
System's force-bearing bonds/constraints, attached hydrogens, component net
charge and coordinate-derived stereochemistry. Force-field topologies do not
generally carry chemical bond orders or atom-local formal charges: the declared
SMILES supplies these, subject to the observed evidence. This is a template-
validated chemical correspondence, not a claim to independently measure formal
charge on each atom or identify every exotic electronic state from an MD System.
External covalent links require a broader chemistry contract and are refused.
Component membership uses the paired coordinate records, not topology residue
labels: 042's 102-atom PDB LIG is split into 1+101 atoms in its TPR. The atom-order
check anchors the topology bonds onto those coordinate components.

All element/H-count-preserving graph isomorphisms are tested against the stated
stereochemistry. A contract atom is placed only if its submitted index is the
same across every admissible reference and submission correspondence. Whole-
ligand symmetry is allowed when the scored atoms are unaffected. An ambiguous
scored atom, incomplete stereo specification, or 4096-map search overflow is
reported explicitly, never resolved by names, coordinate proximity or first hit.
MDClaw provenance maps are not trusted as evaluator evidence.

Reference atom names/order are checked against the bundle PDB. A converter's
conflicting atomic number is corrected only when the PDB's explicit element and
the topology mass agree (0.25 u tolerance); unresolved evidence is refused.
In particular, a PDB atom named CA is not assumed to be calcium.
When the optional PDB element column is absent, the topology's own element
must instead agree with its mass; missing/conflicting evidence is refused.

Validation phases in this change stop at unit/negative/integration regression
tests. Rescoring the historical 042 trajectory and new pi/DeepSeek experiments
are separate phases, not claims made by passing these tests.
