# MDDataBench

A benchmark asking whether an agent can **run a molecular dynamics simulation
that reproduces a real deposited one**. Reference answers come from a public
database rather than from a curator: [MDDB](https://mddbr.eu/). Scoring is
deterministic and artifact-based — everything is recomputed from the submitted
system and trajectory, and numbers the agent reports never enter the score.

MDDB is a **federation of eight nodes**, not one database, and accessions are
node-local: `A01M6` is a MemProtMD membrane system on `oxf`, a different project
on `mmb`, and a DynamicPDB entry on `bsc`. A task contract therefore carries
`(node, accession)`. The node registry is served only by the global API
(`mdposit.mddbr.eu`), which is **not** a superset of the nodes — `MCV1900208` is
absent from it. Most references are CC BY 4.0; the licence string MDDB returns
is recorded verbatim per task, and nothing downloaded is redistributed.

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

The `audit_task_contract` and `audit_task_cast` commands require Gemmi for
mmCIF parsing, deposited `struct_conn` records, and wwPDB residue
classification. Gemmi is a declared package dependency and is installed by
`pip install -e .`; unlike OpenMM, it is not an optional conda-only dependency.

## Using it

```bash
# 1. fetch the reference bundle; data is fetched, never vendored.
#    --node selects the MDDB node, --replica one MD of a multi-replica project.
mddatabench fetch_benchmark_reference \
  --node mmb --accession MCV1900209 --out /tmp/refbundle

# 2. measure the task's md bands from the reference's own windows, pooled
#    across every replica it has. Only needed when building a new task.
mddatabench calibrate_benchmark_task \
  --node mmb --accession MCV1900209 --bundle /tmp/refbundle --out calibration.json

# 3. hand prompt.md to your agent, let it produce an MDClaw job directory

# 4. score what it produced
mddatabench score_benchmark_submission \
  --job-dir <study>/jobs/main --bundle /tmp/refbundle \
  --task-file benchmarks/mddatabench/tasks/D01_plpro_sars2_6w9c/task.json

# 5. confirm the md-side checks still reject what they should
mddatabench run_benchmark_negative_controls \
  --job-dir <study>/jobs/main --bundle /tmp/refbundle --task-file <task.json>
```

A submission whose pipeline errored out scores **prep 0 and md 0** with the
reason recorded, rather than raising out of the scorer and vanishing from the
results.

For repeated agent campaigns across harness, model, and capability conditions,
including Slurm handoff and paper-table generation, see
[`docs/experiments.md`](docs/experiments.md). The primary campaign metric is the
strict per-attempt success rate; partial check scores and any-pass-at-k remain
diagnostic secondary measures.

### Run a repeated agent campaign on Rikyu

The shortest safe workflow is:

1. Copy [`examples/experiment-rikyu.json`](examples/experiment-rikyu.json) and
   edit its task and cell lists. Each cell selects one capability condition,
   harness, and model. `replicates: 3` runs three independent attempts.
2. Initialize isolated workspaces. Agents receive `prompt.md`, never the hidden
   task contract or reference trajectory.
3. Run one pilot attempt with `--limit 1` before launching the full matrix.
4. Re-run without `--limit` to launch the remaining agents. Preparation runs on
   the login node; agents submit MD through Slurm. An evaluator-owned scorer is
   attached to the final MD job with `afterany`.
5. After the Slurm jobs finish, regenerate the paper and failure tables.

```bash
cp examples/experiment-rikyu.json /tmp/my-campaign.json

mddatabench init_experiment \
  --experiment-dir /data1/rkp00048/rku00161/runs/my-campaign \
  --spec-file /tmp/my-campaign.json \
  --dataset-dir benchmarks/mddatabench

# First verify one complete agent -> Slurm MD -> scorer path.
mddatabench run_experiment \
  --experiment-dir /data1/rkp00048/rku00161/runs/my-campaign \
  --bundle-root /data1/rkp00048/rku00161/references \
  --scorer-sif /data1/rkp00048/mdclaw-rikyu-arm64-cuda130-cufft121-fusefix-54798ff98538.sif \
  --max-agents 1 --limit 1

# Launch the remaining attempts. This is restart-safe.
mddatabench run_experiment \
  --experiment-dir /data1/rkp00048/rku00161/runs/my-campaign \
  --bundle-root /data1/rkp00048/rku00161/references \
  --scorer-sif /data1/rkp00048/mdclaw-rikyu-arm64-cuda130-cufft121-fusefix-54798ff98538.sif \
  --max-agents 3

mddatabench collect_experiment \
  --experiment-dir /data1/rkp00048/rku00161/runs/my-campaign
```

The three conditions are `cli_skill_sif`, `cli_sif`, and `sif_only`. On Rikyu,
the first two use the shared old SIF as a dependency layer and overlay the
current `mdclaw_source`; skill-enabled attempts explicitly load that checkout's
skills rather than a copy under `~`. `sif_only` requires a separate scientific
runtime image that does not contain MDClaw.

Available pi models can be recorded without exposing credentials:

```bash
mddatabench model_inventory --harness pi --out model-inventory.json
```

The current Rikyu IDs are `rikyu/qwen3.6-35b`, `rikyu/kimi-k2.6`,
`rikyu/glm-5.2`, and `rikyu/kimi-k3`. Failed preparation, MD, timeout, missing
submission, and scorer failure all remain in the denominator as zero. Results
are rebuilt under `<experiment>/summary/`: `summary.csv` is the main table,
`failures.csv` gives failure causes, and `attempts.jsonl` preserves every run.
The example uses 20-minute limits for agent/preparation and each MD Slurm job.
The evaluator-owned scorer keeps its separate 15-minute limit. Change campaign
limits in the spec only before initializing a campaign.

### Run pi + DeepSeek on the laboratory PC cluster

The laboratory pi configuration currently selects
`deepseek-cloudflare/deepseek-v4-flash`. Start from
[`examples/experiment-lab-deepseek.json`](examples/experiment-lab-deepseek.json),
which points at the local MDClaw checkout and SIF. The model is configured as
non-reasoning, so this example deliberately omits `thinking`; do not retain
Rikyu's `"thinking": "high"` when copying its example. Its
`"skill_source": "user"` leaves pi's normal user-wide skill discovery enabled,
for the MDClaw skill installed under `~/.pi`.

```bash
export PI_CMD_TIMEOUT_SECONDS=600

mddatabench model_inventory --harness pi --out /tmp/lab-pi-models.json

mddatabench init_experiment \
  --experiment-dir /home/yasu/tmp/mddatabench-runs/lab-deepseek-pilot \
  --spec-file examples/experiment-lab-deepseek.json \
  --dataset-dir benchmarks/mddatabench

mddatabench run_experiment \
  --experiment-dir /home/yasu/tmp/mddatabench-runs/lab-deepseek-pilot \
  --bundle-root /home/yasu/tmp/mddatabench-references \
  --scorer-sif /home/yasu/tmp/mdclaw/mdclaw/mdclaw.sif \
  --max-agents 1 --limit 1
```

`PI_CMD_TIMEOUT_SECONDS` is consumed by the `shellPath` wrapper configured in
`~/.pi/agent/settings.json`; it bounds a single agent shell command, while the
experiment's `agent_timeout_seconds` bounds the whole attempt. Keep
`--max-agents 1` for this shared local model endpoint unless concurrency has
been revalidated. Re-run the same `run_experiment` command without `--limit`
after the pilot succeeds. To use another image, change the top-level `sif`
field in the experiment JSON and pass the same path to
`run_experiment --scorer-sif`.

## What is here

```
mddatabench/execution.py   elapsed simulated time, measured from the solvent
mddatabench/dynamics.py    the equilibrium estimators the md checks are built on
mddatabench/calibration.py measures each task's bands from the reference's windows
mddatabench/topology.py    the chemistry both sides declare, in any node's format
mddatabench/composition.py per-monomer composition, protonation, and disulfides
mddatabench/energetics.py  potential energies, recomputed and never read
mddatabench/reference.py   MDDB node registry, bundle retrieval and provenance
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

Three tasks shipped first, and are the ones every measurement below was made
on. A hundred were selected on 2026-08-23; the full list with each task's chain
and residue range is in [`docs/task-candidates.md`](docs/task-candidates.md).

| id | system | node:accession | chain | reference | adds |
|---|---|---|---|---|---|
| D01 | SARS-CoV-2 PLpro, 312 res + Zn | mmb:MCV1900209 | 6W9C C | 1 µs | the baseline: prep and 1 ns MD |
| D02 | SARS-CoV-2 PLpro, 312 res + Zn | mmb:MCV1900210 | 6WRH A | 1 µs | the deposit carries C111S; simulate wild type |
| D03 | SARS-CoV PLpro, 312 res + Zn | mmb:MCV1900208 | 4OW0 A | 1 µs | residue 112 is deposited as OCS, an oxidised cysteine |

### The hundred

Surveying every node directly gives **35602 projects**, of which **4036** can
supply a calibrated window. The cast is stratified over nine axes and split
**70 train / 30 evaluation**:

| axis | tasks (train/eval) | source | force field | window |
|---|---|---|---|---|
| membrane proteins | 14 (11/3) | ebrains/mcns (mmb) | CHARMM36 | 1 ns |
| antibody-antigen | 10 (7/3) | Dynabench (inr) | CHARMM36m | 2.5 ns |
| protein-protein | 6 (4/2) | Dynarepo (inr) | CHARMM36m | 2.5 ns |
| VHH nanobodies | 5 (3/2) | nanobodies (mmb) | ff99SB-ILDN | 1 ns |
| protein-ligand | 10 (7/3) | ligate (cin) | ff99SB-ILDN | 1 ns |
| nucleic acids, incl. the nucleosome | 14 (10/4) | bigna (mmb) | ParmBSC1 etc. | 1 ns |
| metal sites | 4 (3/1) | cv19 (mmb) | ff14SB | 1 ns |
| single chains | 24 (16/8) | ATLAS (bsc) | CHARMM36m | 1 ns |
| single chains | 13 (9/4) | MoDEL (mmb) | Parm99 | 1 ns |

Fifty-six deposits are multi-chain and thirty-nine projects carry two or more
replicas. Six force fields are represented on purpose: the md checks are built
to be force-field independent, and a cast that used one would not test that.

The split is by **homology cluster**, not by task: reference sequences are
clustered on 3-mer containment and whole clusters go to one side. The threshold
was measured rather than chosen. At 0.30 all ten VHH domains collapse into one
cluster and the evaluation set loses the nanobody axis entirely; at 0.70 they
separate and only genuinely repeated systems stay together. What must not leak
is the same system, not the same fold — splitting folds would stop the
evaluation measuring generalisation at all.

### What could not be built

Membrane proteins were twice declared impossible here. That was wrong, and the
reason is worth keeping: the survey had read one node of eight.
`mmb.mddbr.eu` serves 4554 of the registered mmb node's 9062 projects, and the
nanobody and membrane collections are only in the difference.

What genuinely cannot be built, measured across all eight nodes:

- **MemProtMD** (oxf, 9007 projects) is MARTINI coarse-grained. One bead is
  about four heavy atoms, so it cannot be an all-atom reference.
- **mdCATH** (jsc, 5398) records one frame per nanosecond and ships no topology
  file. A 1 ns window would hold a single frame. The temperature, 320 K, is not
  the problem.
- **MDBind** (cin, 4960 projects over 4099 distinct PDB entries) has no
  recorded temperature or ensemble.
- **dynamicPDB** (bsc, 3336) ships no topology file.
- The **spike glycoprotein** references model in the loops the deposit does not
  resolve — 3857 residues against 3195 observed — so they cannot be rebuilt
  from the deposit.

## Prompts are minimal

A prompt states only what cannot be inferred, and says nothing about analysis:
the PDB entry, the chain and residue range, the force field and water model,
the temperature and ensemble, and a minimum production length. Protonation, box
geometry, side-chain completion and how to reach the stated range are left to
the agent, and the reference bundle is never staged into the solver workspace —
the evaluator fetches it at scoring time and recomputes every comparison, so
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

Equilibrium properties are what survive, and the md side is five of them plus
the clock. Each carries the same weight, so no check can be paid for by
another being especially good — there is nothing to be especially good at, only
inside or outside.

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

Eight checks, each weight 1.0, so the md score is the fraction of them a
submission passes. Six are the gates listed above; the other two are
`thermodynamic_conditions_match_reference`, which asks whether the run was set
up at the temperature and ensemble the prompt named, and
`production_ran_for_one_nanosecond`, which asks whether it claims to have run
that long at all. The measured temperature check is the one that decides
whether the claim was true.

**The subspace test was retired on 2026-08-22.** It was the centre of the md
side and it decided nothing: an elastic-network ensemble with no dynamics at
all reached RMSIP 0.749 where a real 1 ns run reached 0.704. It was ranking a
fake above the truth, and the negative controls it was judged by only failed
because of the solvent clock. The measurement is in `docs/memo.md`.

**Radius of gyration is back**, having been removed on 2026-08-21 for a reason
that was correct about a different design. It was dropped as a property of the
prepared structure rather than of the simulation when it was graded against a
fixed band; graded against the reference's own window-to-window spread it
measures whether the simulation stayed the size the reference stayed, which a
collapsed or expanded run does not.

### The bands are measured, and pooled across replicas

A submission is an **independent run**: same system, same conditions, different
velocities. Windows taken inside one reference trajectory share that
trajectory's history, so their spread is narrower than the spread between runs.
Measured on 20 ATLAS systems, the pooled standard deviation is **1.21x** the
within-replica one at the median and **1.82x** at the worst, so a band built
from a single trajectory is about a fifth too narrow, and a too-narrow band
rejects correct submissions.

`mddatabench/calibration.py` therefore pools windows across every replica a
project has. Fifty-three per cent of eligible projects have two or more, and
MDDB addresses them as `ACCESSION.N`. With replicas the false-rejection rate can
also be measured honestly instead of by cross-validation inside one run:
calibrate on all but one replica, then score every window of the held-out one.
On ATLAS 16pk_A, **30 per cent** of the held-out replica's windows fall outside
the unwidened band and **none** outside the band widened by the measured two
window standard deviations.

Run `mddatabench run_benchmark_negative_controls` whenever an md-side threshold
or a band changes. The baselines that must fail are isotropic noise, a
duplicated minimum, an elastic-network ensemble, a frozen first frame, shuffled
per-atom amplitudes, motion scaled fivefold, and truncations to 10 and 100 ps.
The report names which gate caught each, and any gate no baseline exercised.

## Reference solves

All three tasks were solved with MDClaw on one NVIDIA GB200 (ff14SB + TIP3P,
cubic 15 A, HMR 4 fs, NVT 100 ps + NPT 200 ps, 1 ns NPT production).

Graded against the current block, measured 2026-08-22:

| task | atoms | prep | md | rank correlation | total RMSF | Rg |
|---|---|---|---|---|---|---|
| D01 | 31355 | 1.000 (12/12) | 1.000 (7/7) | 0.870 | in band | in band |
| D02 | 35469 | 1.000 (12/12) | 1.000 (7/7) | in band | in band | in band |
| D03 | 21656 | 1.000 (12/12) | 1.000 (7/7) | in band | in band | in band |

Two estimator faults were found getting there, and neither was a threshold:

- Fitting each window to **frame 0** instead of to the window's own mean
  structure put the window's drift into every atom's deviation.
- A **crystal-started nanosecond drifts**, and the drift dominated the RMSF.
  Removing a per-atom linear trend in time before computing RMSF took D03's
  rank correlation from 0.803, below the band, to 0.870, inside it.

The slack the bands carry was measured too, not chosen. Held-out reference
windows fall outside the range of the rest 16 / 7 / 9 per cent of the time on
D01 / D02 / D03 with no slack, and 0 per cent at two window standard
deviations; every negative control still fails at three.

## Running the scorer

Always give the container a thread limit. Its OpenBLAS is built
`DYNAMIC_ARCH NO_AFFINITY MAX_THREADS=64` and collapses on the superposition and
correlation work without one. `mddatabench/_threads.py` sets a default before
numpy loads, so this only matters if you import the modules some other way.
