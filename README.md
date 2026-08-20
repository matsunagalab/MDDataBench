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
mddatabench fetch_benchmark_reference --accession A0142 --out /tmp/refbundle

# 2. hand prompt.md to your agent, let it produce an MDClaw job directory

# 3. score what it produced
mddatabench score_benchmark_submission \
  --job-dir <study>/jobs/main --bundle /tmp/refbundle \
  --task-file benchmarks/mddatabench/tasks/D01_pca_subspace_ubiquitin/task.json

# 4. confirm the md-side checks still reject what they should
mddatabench run_benchmark_negative_controls \
  --job-dir <study>/jobs/main --bundle /tmp/refbundle --task-file <task.json>
```

## What is here

```
mddatabench/subspace.py    the pinned analysis contract and the hypothesis test
mddatabench/execution.py   elapsed simulated time, measured from the solvent
mddatabench/reference.py   MDDB bundle retrieval and provenance
mddatabench/scoring.py     per-check scoring, split into prep and md
mddatabench/controls.py    adversarial baselines that must fail
mddatabench/_threads.py    BLAS thread guard, imported before numpy
benchmarks/mddatabench/tasks/D01_...  ubiquitin (PDB 1UBQ, MDDB A0142)
benchmarks/mddatabench/tasks/D02_...  cold-shock protein CspB (PDB 1CSP, MDDB A00AJ)
benchmarks/mddatabench/tasks/D03_...  endothelin-1 (PDB 1EDN, MDDB A00EC)
```

## Tasks

| id | system | MDDB | adds over the previous task | companion |
|---|---|---|---|---|
| D01 | ubiquitin, 76 res | A0142 | the baseline: prep, 1 ns MD, subspace test | — |
| D02 | CspB, 67 res | A00AJ | side-chain completion, non-zero solute charge | MDPrepBench P32 |
| D03 | endothelin-1, 21 res | A00EC | two disulfides, and a small mobile peptide | MDPrepBench P10 |

The cast deliberately overlaps MDPrepBench. 1934 of MDDB's 4554 projects are
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
the PDB entry, TIP3P, neutralised, 300 K, NPT, at least 1 ns. Chain selection,
protonation, box geometry and side-chain completion are left to the agent, and
the reference bundle is never staged into the solver workspace — the evaluator
fetches it at scoring time and computes both subspaces itself, so numbers the
agent reports are never used and the reference cannot leak.

Verified on 2026-08-19: with no protonation guidance at all, MDClaw lands on
602/1231 atoms for 1UBQ and 521/1014 for 1CSP, both exactly the reference
composition, and completes 1CSP's four truncated glutamates unprompted. The two
runs pick opposite histidine tautomers from the reference, which the checks
tolerate by design (heavy-atom count is tautomer independent).

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

**Radius of gyration is not redundant with the subspace test.** RMSIP is
invariant to the overall scale of the fluctuations: a trajectory uniformly
expanded by 30% -- a unit error, say -- scores an identical 0.729 while its Rg
moves from 1.14 to 1.48 nm. Even progressive swelling to Rg 1.82 still scores
0.711. Rg is the only check that constrains compactness at all.

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

Both tasks were solved with MDClaw 0.6.6 on one RTX A6000 (ff14SB + TIP3P,
cubic 15 A, HMR 4 fs, NVT 100 ps + NPT 200 ps, 1 ns NPT production).

| task | atoms | RMSIP | structure-only null (max) | margin | clock | prep | md |
|---|---|---|---|---|---|---|---|
| D01 | 31355 | 0.717 | 0.588 | +0.129 | 1000 ps / 1000 | 7/7 | 5/5 |
| D02 | 35466 | 0.703 | 0.637 | +0.066 | 1013 ps / 1000 | 8/8 | 5/5 |
| D03 | 21656 | 0.828 | 0.766 | +0.062 | 1016 ps / 1000 | 8/8 | 5/5 |

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
