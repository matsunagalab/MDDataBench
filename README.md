# MDDataBench

A benchmark asking whether an agent can **run a molecular dynamics simulation
that reproduces a real deposited one**. Reference answers come from a public
database rather than from a curator: [MDDB](https://mddbr.eu/)
(`https://mmb.mddbr.eu/api/rest/v1/`), used under CC BY 4.0. Scoring is
deterministic and artifact-based — everything is recomputed from the submitted
system and trajectory, and numbers the agent reports never enter the score.

MDDataBench was extracted from
[matsunagalab/mdclaw](https://github.com/matsunagalab/mdclaw), alongside its
preparation-focused sibling
[MDPrepBench](https://github.com/matsunagalab/MDPrepBench) and the
scientific-question suite
[MDStudyBench](https://github.com/matsunagalab/MDStudyBench).

## Installation

```bash
git clone https://github.com/matsunagalab/MDDataBench
cd MDDataBench
pip install -e .
mddatabench --list
```

Scoring needs an interpreter that can import `openmm`, `mdtraj`, and `numpy`.
OpenMM is best installed from conda-forge.

## Using it

```bash
# 1. fetch the reference bundle for a task; data is fetched, never vendored
mddatabench fetch_benchmark_reference --accession MCV1900209 --out /tmp/refbundle

# 2. hand prompt.md to your agent, let it produce an MDClaw job directory

# 3. score what it produced
mddatabench score_benchmark_submission \
  --job-dir <study>/jobs/main --bundle /tmp/refbundle \
  --task-file benchmarks/mddatabench/tasks/D01_plpro_sars2_6w9c/task.json

# 4. confirm the md-side checks still reject what they should
mddatabench run_benchmark_negative_controls \
  --job-dir <study>/jobs/main --bundle /tmp/refbundle --task-file <task.json>
```

## What is here

```
mddatabench/subspace.py    the pinned analysis contract and the hypothesis test
mddatabench/execution.py   elapsed simulated time, measured from the solvent
mddatabench/composition.py per-monomer composition, protonation, and disulfides
mddatabench/energetics.py  potential energies, recomputed and never read
mddatabench/reference.py   MDDB bundle retrieval and provenance
mddatabench/scoring.py     per-check scoring, split into prep and md
mddatabench/controls.py    adversarial baselines that must fail
mddatabench/_prep_checks.py  the prep check block, written into every task.json
mddatabench/_md_checks.py    the md check block, written into every task.json
mddatabench/_threads.py    BLAS thread guard, imported before numpy
benchmarks/mddatabench/tasks/D01_...  SARS-CoV-2 PLpro (PDB 6W9C, MDDB MCV1900209)
benchmarks/mddatabench/tasks/D02_...  SARS-CoV-2 PLpro (PDB 6WRH, MDDB MCV1900210)
benchmarks/mddatabench/tasks/D03_...  SARS-CoV PLpro   (PDB 4OW0, MDDB MCV1900208)
```

## Tasks

| id | system | MDDB | chain | reference | adds |
|---|---|---|---|---|---|
| D01 | SARS-CoV-2 PLpro, 312 res + Zn | MCV1900209 | 6W9C C | 1 µs | the baseline: prep, 1 ns MD, subspace test |
| D02 | SARS-CoV-2 PLpro, 312 res + Zn | MCV1900210 | 6WRH A | 1 µs | a second deposit of the same protein |
| D03 | SARS-CoV PLpro, 312 res + Zn | MCV1900208 | 4OW0 A | 1 µs | the orthologue, and non-default protonation |

The cast was re-selected on 2026-08-22 by sequence alignment: every reference
monomer is aligned against the RCSB polymer entities of its deposit
(Biopython global alignment, ≥90% coverage and ≥95% identity required), and
every non-polymer component of the reference must also exist in the deposit.
The second condition is what rules out the DE Shaw Anton entries, whose docked
`LIG` / `RT` / `ATP` / `MG` are absent from the deposited structures.

All three references are 1 µs, which is the point: a 1 ns submission is
compared against many independent 1 ns windows of the reference rather than
against a single trajectory, so the reference supplies its own spread and the
agent still only runs 1 ns.

The eligible pool deliberately overlaps MDPrepBench. 1934 of MDDB's 4554 projects are
eligible — CC licensed, classical MD, a full analysis set, and a PDB entry —
and they cover most of MDPrepBench's capability axes:

| axis | eligible entries | example |
|---|---|---|
| disulfides | 677 | `A00EC` 1EDN (D03) |
| terminal caps | 144 | `A007Z` 1CCR |
| selenomethionine | 31 | `A015F` 1WHZ |
| zinc, with the metal retained | 139 | `MCV1900209` PLpro 6W9C |
| ligand bound | 78 | `MCV1900211` PLpro + 3k |
| glycosylation (NAG) | 79 | `MCV1900112` 6VW1 |
| DNA duplex, counterions retained | 126 | `A01MQ` 1ICK |
| RNA | 10 | `A01AU` 1Q9A |
| protein-DNA, with Mg | 26 | `A01FH` 1VTN |
| multimer | 254 | `A007P` 1CDL calmodulin |

Metadata alone is not enough to pick from this. `OTHRATS > 0` together with
`PTM: Acetylation` reads like a metalloprotein but is an ACE cap: 1CCR and
1JEB both come with their haem stripped, as 2CBA comes without its zinc, so
MoDEL cannot supply a metal task at all. The composition that matters is in
`RSNAME`, and the entries above were each confirmed by fetching the deposited
structure. 2CBA is held back for that reason — making it a task would reward
stripping the catalytic metal that MDPrepBench P26 exists to test.

Four axes have no eligible entry: membranes (the only CC bilayers are ten
SARS-CoV-2 viral membranes), implicit solvent, mutants, and phosphorylation.

## Prompts are minimal

A prompt states only what cannot be inferred, and says nothing about analysis:
the PDB entry, the chain and residue range, the force field and water model,
the temperature and ensemble, and a minimum production length. Protonation, box
geometry, side-chain completion and how to reach the stated range are left to
the agent, and the reference bundle is never staged into the solver workspace —
the evaluator fetches it at scoring time and computes both subspaces itself, so
numbers the agent reports are never used and the reference cannot leak.

The residue range is there because it is exactly what a deposit cannot tell
you. Measured 2026-08-22, the three deposits resolve three different ranges and
every reference simulates the same one: 6W9C chain C stops one residue short of
it, 6WRH chain A runs four past it and carries the C111S substitution that
inactivates the enzyme for crystallography, 4OW0 chain A matches. Keeping every
resolved residue is a defensible default and so is leaving an unresolved
terminus alone, yet without the range either choice cost five checks — monomers
are paired by exact sequence, and a range difference blocks the per-residue
comparison the rest depend on. D02's prompt says the deposit carries C111S and
the reference does not; neither prompt says how to act on any of it.

Verified on 2026-08-19 against the earlier task cast: with no protonation
guidance at all, MDClaw landed on 602/1231 atoms for 1UBQ and 521/1014 for
1CSP, both exactly the reference composition, and completed 1CSP's four
truncated glutamates unprompted. The two runs picked opposite histidine
tautomers from the reference, which the checks tolerate by design (heavy-atom
count is tautomer independent).

Measured 2026-08-22 on the current cast, where the systems are 25× larger, the
prompt is no longer enough on its own. D03 reproduces the reference sequence,
monomer count, element composition and disulfide set exactly and still differs
on three residues: the reference simulates two zinc-coordinating cysteines as
thiolates (CYM) and one histidine protonated (HIP), where MDClaw builds neutral
CYS and HIE. That is what grading protonation by atom count rather than by
residue name is for — the difference is −1 −1 +1 hydrogens, and the total atom
count agrees at 4862 against 4861. D01 and D02 differ more coarsely, at 311 and
316 residues against the reference's 312.

## Principles

- **Data is fetched, never vendored.** Task contracts carry the accession, the
  retrieval date, the licence, and the SHA-256 of the bundle. Re-run
  `mddatabench fetch_benchmark_reference` to reproduce it.
- **Only CC BY / CC0 projects are eligible.** 24 of MDDB's 4554 projects carry
  other licences and are excluded.
- **The reference database is blocked at solve time.** RCSB stays reachable;
  `mddbr.eu` does not. Otherwise the agent can fetch what it is scored against.
- **The prompt never names the accession.**
- **Every axis is evaluated independently.** Failing one axis does not skip the
  others; only the final verdict is gated. See the design note.
- **Nothing is scored against an uncalibrated threshold.** Quantities whose
  force-field sensitivity has not been measured are recorded as diagnostics.

## Two scores, not one

Checks are reported under **prep** and **md** separately, because a single
number cannot say whether a submission failed at building the system or at
simulating it. The adversarial baselines make the point: an elastic-network
ensemble and a 10 ps run both score full marks on prep and must fail on md.

## What the md side may and may not see

Three things are deliberately free, and each rules out a family of
observables.

**The force field.** Requiring the reference's would empty the eligible pool,
and running under a different one is a thing to be able to do. So nothing may
key on rotamer or salt-bridge propensities, which are the most systematically
force-field-dependent quantities available. Verified by running one task under
ff99SBildn against a reference built with ff14SB: every md check passes.

**The protonation of ambiguous residues**, which is already exempt on the prep
side and so cannot be graded here by a back door — the maximum RMSD over a
window is one such door, since a metal site given a defensible different
protonation dominates it, and that is why the RMSD statistics are recorded and
not scored.

**The thermostat.** Friction sets relaxation times, so every time-correlation
statistic is out. Measured, a lag-dependent MSD separates real runs (2.9–4.5)
from shuffled frames (0.97–1.08) with no overlap at all, and is still not
usable: it would fail a correct run for its integrator.

Equilibrium properties are what survive, and the md side is five of them
plus the clock, conjoined — a weighted sum would let one complete failure be
paid for elsewhere, and "it ran as asked" is not that kind of claim.

| gate | statistic | band | catches |
|---|---|---|---|
| clock | elapsed time from solvent diffusion | reference-free | truncation, an ensemble, duplicated frames, never having run |
| temperature | mean of the state log | asked-for ±3 K | a different setpoint. The *spread* is never graded: the thermostat sets it |
| solvent box | mean density, and box volume that moved | [0.95, 1.10] g/mL, spread > 0 | vacuum, a bubble, a barostat that was never connected |
| fluctuation shape | rank correlation with the reference's own per-atom profile | one-sided floor | shuffled frames, freezing, noise |
| fluctuation size | total RMSF | two-sided | over-restraint, expansion |
| global shape | mean radius of gyration | two-sided | collapse, coming apart |

The last three are calibrated against the reference's **own one-nanosecond
windows** — the same estimator applied to the same length of the same
trajectory — so the question is not "does a nanosecond reproduce a
microsecond", which it cannot, but "is this distinguishable from a nanosecond
of the reference".

Two of the pairs are there because neither half catches what the other does.
An over-restrained run keeps a rank correlation of 0.872 with a tenth of the
motion, and a threefold expansion keeps 0.867; both are caught only by the
magnitude. Shuffled frames keep the magnitude exactly and lose the ranks.

The bands are widened by twice the window spread, and that number is measured
rather than chosen: five-fold block cross-validation over 100 windows rejects
held-out reference windows 16, 7 and 9 per cent of the time with no slack, and
0 per cent at two. Every negative control still fails at three.

Two further categories are reported and never scored. **precondition** holds
`contract_atoms_resolvable` and `topology_loads_and_is_parameterized`, which
ask whether the scorer can line two systems up at all — that measures the
scorer, not the agent. **diagnostic** holds
`metal_site_coordination_retained`, which counts the side chains coordinating
each metal in the built structure and how many still are for most of
production. It is not a comparison with the reference and cannot be one; it
stays unscored until it has been measured on more than three systems, and when
it is scored it will have to read the spread as well, because a bonded metal
model satisfies a distance test by construction.

## What a submission has to clear on the prep side

Every prep check takes its expectation from the reference bundle rather than
from a curator, so the block is identical across tasks: there are no per-system
prep checks left. D02's completed side chains and D03's disulfides used to be
hand-written per-task entries and are now instances of checks that run
everywhere and expect zero as readily as two.

**Composition is compared per monomer.** Both sides are split into covalently
connected polymer chains by backbone geometry and paired by canonical sequence.
PDB chain IDs are not used: preparation tools relabel and reuse them, and D03's
`system.topology.pdb` carries chains A, B and C where the reference has only A.
A multimer is then N monomers rather than a special case, and a failure names a
chain and a residue instead of a total.

**Protonation is graded by atom count, never by residue name.** Names are a
convention — the same MDClaw submission writes CYX in `merged.pdb` and CYS in
`system.topology.pdb`, GROMACS writes HISD/HISE/HISH, CHARMM HSD/HSE/HSP.
Counts are not, and they have exactly the property the task needs. Measured
2026-08-21, the reference and the submission disagree on the histidine tautomer
in D01 (HIE vs HID) and D02 (HID vs HIE) and agree on every per-residue count:

| variant | hydrogens | detected |
|---|---|---|
| HID ↔ HIE, the agent's free choice | same | no, correctly |
| HIP | +1 | yes |
| ASH, GLH | +1 | yes |
| LYN, CYM | −1 | yes |
| CYX, from a disulfide | −1 | yes |

There is no separate total-atom check. It was the sum of this comparison and
added nothing: a matching sequence with matching per-residue counts cannot have
a different total, and where the monomers do not pair the monomer, sequence and
element checks already say so. It had also stopped being harmless, because the
per-residue comparison exempts the residues below and the total did not.

**Two kinds of residue are exempt from the protonation comparison**, and both
are found by geometry, so the answer is the same whether a file wrote CYM/HIP
or CYS/HIE. Their identity is still compared: a cysteine that became an alanine
is a mutation and has nothing to do with either.

*Metal ligands.* All three references hold a four-cysteine structural zinc with
a bare 12-6 ion — `type Zn2+, charge +2.0, rmin 1.271 A, zero bonds`, the same
parameters our own submissions build — deprotonate two of the four, lose the
other two to 5–13 Å over a microsecond, and let the zinc be chelated by a
glutamine oxygen at 1.75 Å instead. Grading against that rewards copying a
half-open site: a submission that deprotonates all four is further from the
reference and closer to right. Measured, it retains 4 of 4 ligands at
1.97–1.99 Å where the reference retains 2.

*Catalytic pairs.* A cysteine–histidine dyad is exempt because the field does
not agree with itself. Neutron crystallography of SARS-CoV-2 Mpro reports the
thiolate–imidazolium zwitterion, room-temperature X-ray of the same enzyme
reports the neutral form, MD of cruzain reports neutral, and for 3CL-PR the
dominant species reportedly differs between H₂O and D₂O. The cutoff is 3.5 Å:
measured, the dyad sits at 2.98, 3.08 and 3.11 Å and the next closest Cys/His
pair in the same structure is 4.08, 4.63 and 4.08 Å.

**Both sides are read from a topology, on every task.** MDDB serves a
`topology.prmtop` for every project, so the expected bonds are a bond list
rather than CYX names plus a distance, and the expected protonation is a
residue table. The submitted bonds come from the System — `HarmonicBondForce`
together with the constraint list, because with HBonds and rigid water most
bonds are constrained (21451 constraints against 177 bond terms in one measured
task). A CONECT record is metadata and can disagree with what exerts force.
Comparing whole sets rejects a *spurious* disulfide as readily as a missing
one, and zero expected pairs is a real expectation.

**`topology_is_chemically_valid` fails three faults with no reference to
consult**: an atom name repeated inside a residue, an atom over its valence, and
a covalent bond between two ligands of one metal. The last is what MDClaw did
on 6W9C — SG(192) and SG(224) sit 3.00 Å apart with the zinc 2.85 and 2.57 Å
from them, distance detection called that a disulfide, and the built system
carried a real 0.2038 nm bond term that pulled the sulfurs to 2.04 Å during
production. Sulfur is absent from the valence table on purpose: a sulfonamide,
a sulfate and DMSO all carry four bonds on S.

**Energies are recomputed, never read.** The runner's own
`minimization_report.json` is the same class of claim as `simulation_time_ns`,
which the solvent clock exists to distrust. The scorer deserialises the
submitted `system.xml` and evaluates it at the built and minimised states. Two
gates: the energy is finite with a per-particle magnitude below a loose ceiling,
and minimisation lowered it. The per-atom value itself is a diagnostic —
measured 2026-08-21 it is −17.00 / −16.93 / −16.94 kJ/mol/atom on D01 / D02 /
D03, which is tight enough to be tempting and is three systems on one force
field.

Mutating a passing submission confirms each check rejects what it should
(measured 2026-08-21 on D01 and D03):

| mutation | rejected by |
|---|---|
| one HIP (one extra hydrogen) | residue atom counts, total atoms |
| a truncated side chain | residue atom counts, elements, total atoms |
| one backbone N written as O | elements only — the total is unchanged |
| a broken peptide bond | monomer count, sequence, residue atom counts |
| a disulfide's CONECT removed | disulfides |
| a spurious SG–SG CONECT added | disulfides |

**What MDDB cannot support.** Water counts are never available: `SOL`,
`SOLVATS` and `SOLVRES` are empty in all 4554 projects. Ion counts and box size
coexist in only 47 of the 1940 eligible projects, and in 46 of those the ion is
a single neutralising counterion, so no salt concentration can be demanded
either — and a concentration could not be graded tightly anyway, since asking
packmol-memgen for 0.15 M yields 0.146 / 0.118 / 0.130 M across the three tasks
once neutralising counterions and integer quantisation are accounted for. Net
neutrality is the only solvent-side property that is checked. Box shape is
recorded by MDDB (`BOXTYPE`, 89.6% of the eligible pool, `Octahedral` for all
three references against the submitted cubic boxes) and is deliberately not
scored, like the force field: comparable, but not worth grading.

## What a submission has to clear on the md side

Rejecting the random-subspace null turned out to be necessary but far from
sufficient. Measured on 2026-08-19 with that null alone, three submissions that
should have failed passed:

| baseline | RMSIP | rejects random null | verdict then |
|---|---|---|---|
| elastic-network ensemble, **no MD at all** | 0.515 | yes, z = 46 | passed |
| real MD truncated to **100 ps** | 0.627 | yes, z = 60 | passed |
| real MD truncated to **10 ps** | 0.420 | yes, z = 36 | passed |

Two further checks close both holes.

**A better null.** The random-subspace null is replaced outright rather than
supplemented. Anisotropic network models of the deposited structure, swept over
cutoff 7.0-20.0 A, give a null of 0.517 +/- 0.048 with a maximum of 0.588; a run
passes when its RMSIP exceeds every draw. This null subsumes the random one --
anything that cannot beat noise cannot beat the fold -- so it is the only
subspace gate. Against it a real 1 ns run reaches z = 4.4 while the
elastic-network ensemble lands at z = -0.05, dead centre, which is exactly
where a structure-only submission belongs.

**A physical clock.** The recorded `simulation_time_ns` is the runner's own
claim. The self-diffusion coefficient cannot check it — it is intensive and
reads 3.7e-5 cm^2/s whether you take 1 ns or 100 ps of the same trajectory. The
*accumulated* solvent displacement is extensive and does: continuously
unwrapping the frame-to-frame minimum image recovers 989 ps from a 999 ps run,
98 ps from 99 ps, and 15 ps from 9 ps. A submission with no bulk solvent cannot
be clocked at all, which is the right verdict for an ensemble made without
dynamics.

With both in place every adversarial baseline fails and the real runs pass. The
100 ps truncation still clears the structure-only null and is caught only by the
clock, which is why both checks are kept.

**Nothing constrains the overall scale of the trajectory.** Radius of gyration
used to, and was removed on 2026-08-21 because it is a property of the prepared
structure rather than of the simulation: measured that day it is 1.1616 /
1.1031 / 0.8549 nm as built against 1.1784 / 1.1224 / 0.8223 nm averaged over
production, while the within-trajectory SD is only 0.007-0.012 nm against bands
that were 0.2-0.4 nm wide. A nanosecond does not move it, so grading it on the
md side attributed a preparation property to the simulation.

The cost is real and is recorded rather than papered over. RMSIP is invariant to
the overall scale of the fluctuations, because canonical correlations see only
the direction of a subspace: measured on D01, scaling the trajectory by 0.8,
1.3 or 1.5 leaves RMSIP at exactly 0.700 and H0 rejected in every case, while Rg
moves to 0.943, 1.532 and 1.768 nm. The solvent clock is scale-invariant too, as
a ratio of accumulated displacement to a diffusion coefficient fitted from the
same trajectory. A uniform scaling error -- a unit mistake, say -- is therefore
caught by nothing. `rg_mean_nm` is still reported as a diagnostic.

Run `mddatabench run_benchmark_negative_controls` whenever an md-side threshold changes.

## The subspace test

`mddatabench/subspace.py` implements one contract and one test.

`pca_backbone_subspace@1` pins the atom selection, the superposition, the mode
count, and the units. MDDB publishes PCA eigenvalues and projections but not
eigenvectors, so the reference subspace must be recomputed; the pinned contract
reproduces MDDB's published eigenvalues to within -2.6% to +3.4%.

`subspace_unrelated@1` tests H0 = *the two essential subspaces are unrelated*,
using RMSIP against a Monte Carlo null over random orthonormal frames. The null
mean matches the analytic `sqrt(D / 3M)`. Rejecting H0 certifies that the
submitted trajectory explores the same collective directions as the reference.

Measured on the D01 reference (2026-08-19, D = 10, 3M = 684; D02's reference
gives 0.687 +/- 0.035 window-to-window against a 0.129 null at 3M = 603):

| comparison | RMSIP | z | H0 rejected |
|---|---|---|---|
| random subspaces (negative control) | 0.121 | 0.0 | no |
| elastic network model, structure only | 0.47 - 0.62 | ~60 | yes |
| coordinate-frame mismatch | 0.652 | 64 | yes |
| 1 ns window vs 1 ns window | 0.760 | 82 | yes |
| 1 ns window vs full 10 ns | 0.794 | 85 | yes |
| 500 frames spread over 10 ns | 0.969 | - | yes |

The test is a **validity gate, not a quality score**: an elastic network model
built from the fold alone also rejects H0. It certifies that a submission is a
simulation of the right molecule analysed under the right contract. It does not
certify converged sampling — at 1 ns the reference's own leading modes carry
less than one independent sample.

## Reference solves

All three tasks were solved with MDClaw 0.6.6 on one RTX A6000 (ff14SB + TIP3P,
cubic 15 A, HMR 4 fs, NVT 100 ps + NPT 200 ps, 1 ns NPT production). The prep
counts below are the 7-and-8-check block these solves were graded against; the
current block is 11 checks on every task.

| task | atoms | RMSIP | structure-only null (max) | margin | clock | prep | md |
|---|---|---|---|---|---|---|---|
| D01 | 31355 | 0.717 | 0.588 | +0.129 | 1000 ps / 1000 | 7/7 | 5/5 |
| D02 | 35466 | 0.703 | 0.637 | +0.066 | 1013 ps / 1000 | 8/8 | 5/5 |
| D03 | 21656 | 0.828 | 0.766 | +0.062 | 1016 ps / 1000 | 8/8 | 5/5 |

Re-solved 2026-08-21 with MDClaw 0.6.8 on one NVIDIA GB200, same protocol,
graded against the current block:

| task | atoms | RMSIP | null (max) | margin | clock | prep | md |
|---|---|---|---|---|---|---|---|
| D01 | 31355 | 0.700 | 0.588 | +0.112 | 989 ps / 1000 | 12/12 | 5/5 |
| D02 | 35469 | 0.707 | 0.637 | +0.070 | 981 ps / 1000 | 12/12 | 5/5 |
| D03 | 21656 | 0.779 | 0.766 | +0.013 | 1017 ps / 1000 | 12/12 | 5/5 |

D03's margin of +0.013 is the narrowest measurement in the suite and is close
enough to the null's maximum that a different seed could cross it. A one-run
D03 verdict should not be treated as stable.

Both nulls climb as the system shrinks — D03 has 3M = 189, so even the random
null is sqrt(10/189) = 0.230 — which is why the smallest system has the
narrowest margin rather than the widest.

Three D01 replicas (different seeds) give RMSIP 0.729 / 0.743 / 0.717, so a
single 1 ns measurement is reproducible to **SD 0.010**. Differences below about
0.03 between agents are noise. Pooling the three raises RMSIP to 0.764 while an
attacker pooling three elastic-network ensembles gains only 0.022, so replicas
widen the margin -- but the reference-free replica-to-replica agreement (0.801)
is the more useful thing they buy.

## Running the scorer

Always give the container a thread limit. Its OpenBLAS is built
`DYNAMIC_ARCH NO_AFFINITY MAX_THREADS=64` and collapses on the 684x684
eigendecomposition without one: measured 16.3 s per call unlimited against
0.07 s at eight threads, which is the difference between ten minutes and seven
seconds for one task. `mddatabench/_threads.py` sets a default before numpy
loads, so this only matters if you import the modules some other way.

In both, subspace **directions** are recovered while **amplitudes** are 2-6x
too small — exactly what the effective-sample-size diagnostic predicts for
1 ns, and the reason the task scores the H0 rejection rather than quantitative
agreement.
