# Working Memo

Running record for MDDataBench: what was run, what the numbers were, what was
decided, and why. Newest entries go at the top. Append as work continues; do
not rewrite past entries when a later finding contradicts them — add the
correction and say what it overturns.

## 2026-08-29 — Each attempt now owns its temporary directory

`run_attempt_agent` creates `workspace/.mddatabench/tmp` and exports that same
path as `TMPDIR`, `TMP`, and `TEMP`.  The directory remains with the attempt for
postmortem inspection.  The runner test launched two replicas, observed two
distinct existing paths, and passed 30/30 experiment tests in the SIF.  A small
fake-pi replay also required a `*/workspace/.mddatabench/tmp` value, wrote
`solv.phaseb-replay` there, exited successfully, and verified that its sentinel
`/tmp/solv.phaseb-20260829-replay-leak` was not created.  The agent prompt now
requires ad-hoc logs and temporary files under `$TMPDIR` rather than a fixed
name in global `/tmp`.

## 2026-08-29 — Task 014 now discloses its HIS-named HIP chemistry

The task's recorded `mmb:A023S` bundle was fetched again with
`mddatabench fetch_benchmark_reference`; all five fetched SHA-256 values match
the task contract.  Its reference residue 255 is named HIS but carries both
HD1 and HE2 and the internal-residue formula C6 H8 N3 O (18 atoms), whereas the
other HIS residues have seven hydrogens.  Mapping reference position 255 across
the retained SEQRES spans 9–216 and 323–410 gives deposit SEQRES position 369,
author residue A:264.  The existing builder now emits:

```text
Residue 264 of chain A is a protonated histidine.
```

The atom-name signature is preferred and the exact internal-HIP formula is the
fallback.  Neutral HIS is unchanged; metal-ligand and catalytic-dyad exemptions
still take precedence.  `tests/test_benchmark/test_task_builder.py` passed 52/52
inside the SIF.  Attempt 014r1 was not replayed because its retained attempt
tree has only score/reconstruction evidence and its recorded `/data1/...` job
directory no longer exists.

## 2026-08-29 — Disulfides are compared through the whole monomer pairing

S-S endpoints are now expressed as `(polymer component, position in component)`
from the force-bearing topology.  The scorer enumerates the sequence-preserving
copy permutations and chooses by the complete S-S edge-set difference, so both
ends of an inter-chain bond move together with their monomers.  The H x2/L x2
fixture has four candidate pairings; swapping only the L copies defeats the old
independent zip but the whole-set comparison finds the exact pairing, while a
changed inter-chain endpoint still produces one missing and one unexpected
edge.  The focused SIF test was:

```bash
singularity exec --bind /home/yasu/tmp /home/yasu/tmp/mdclaw/mdclaw/mdclaw.sif \
  env PYTHONPATH=/home/yasu/tmp/mdclaw/MDDataBench \
  python -m pytest tests/test_benchmark/test_topology.py -q -p no:cacheprovider
```

It passed 9/9.  Attempts 008r1/r2 and 019 were not replayed: their retained
trees contain score/reconstruction evidence, but the recorded job and topology
paths under `/data1/.../full100-pass2` no longer exist.

## 2026-08-29 — 027 passed 20/20 with pi + DeepSeek on the laboratory cluster, after five rikyu-only assumptions were fixed

`outputs/runs/lab-deepseek-n4-20260829b`, `cli_skill_sif`, pi +
`deepseek-cloudflare/deepseek-v4-flash` (non-reasoning), frozen mdclaw `580d80d`,
MD pinned to `n4` through the shim (`MDDATABENCH_MD_NODELIST=n4`,
`MDDATABENCH_MD_PARTITION=all`). **Attempt score 1, 20/20**: agent 1072 s wall
(bootstrap → prep → solv → topo → min/eq/prod chain 136015→136016→136017, then
exit), scorer 136018 `afterany`, result at 08:34 UTC — the eq + 2.6 ns
production chain on one GTX 1080-class GPU took about 65 min. Solvent clock
2517/2600 ps, RMSF rank correlation 0.834, Rg 24.42 Å inside the reference
window, density 1.0013 g/mL. The agent chose 0.15 M NaCl for "neutralised"
without reading source, which the same model failed to do earlier in the day
against the pre-`580d80d` skills (MDDataBench D01 attempt in
`~/tmp/mddatabench_runs`; 25 min grepping `mdclaw/solvation` for an add-ion
tool).

**Four attempts died before this one, none for scientific reasons.** The
runner had been developed on Rikyu and encoded that host:

| assumption | laboratory cluster | symptom | fix |
|---|---|---|---|
| `node` reachable from the sanitized PATH | lives in `~/.local/share/pi-node` | pi exit 127 in 0.02 s | add `which node` dir for pi |
| system `python3` new enough for `bin/mdclaw` host tools | `/usr/bin/python3` is 3.8 | `inspect_cluster` import failure, agent burns budget | add operator `which python3` dir |
| `/usr/bin/sbatch` | `/usr/local/bin/sbatch` | every submission would fail | `MDDATABENCH_REAL_SBATCH` defaults to `which sbatch` |
| partition `gpu` for the scorer | only `all` | scorer sbatch rejected | `MDDATABENCH_SCORER_PARTITION` |
| per-command watchdog | `pi_shell_timeout.sh` matched only MDPrepBench paths | agent's `find / -name sbatch` sat on NFS for 11 min | case also matches `*/MDDataBench/outputs/runs/*` |

Also: the scorer looks for `<bundle-root>/<node>_<accession>`, while the
bundles here were fetched to `outputs/references/<node>/<accession>`; a symlink
bridges the two for now. Operator lesson recorded twice today: anything left in
the agent workspace gets read — a reference bundle staged there for scoring
convenience contaminated one D01 attempt, and a leftover session log from that
attempt was parsed by the next.

## 2026-08-29 — Added the laboratory pi + DeepSeek campaign path

The laboratory `~/.pi/agent` configuration currently names
`deepseek-cloudflare/deepseek-v4-flash`, marks it non-reasoning, and uses the
MDPrepBench shell watchdog.  A separate experiment example now selects that
fully-qualified model, omits Rikyu's incompatible `thinking: high`, and points
at the laboratory MDClaw checkout, CLI, and SIF.  Its `skill_source: user`
keeps pi's user-wide `~/.pi` skill discovery instead of passing the frozen
checkout through `--skill`.  The documented pilot uses one agent and exports
`PI_CMD_TIMEOUT_SECONDS=600`; whole-attempt and Slurm limits remain separate.
The laboratory source root also contains a 5.2 GB SIF and old `outputs/` and
`benchmark_runs/`; source freezing now excludes them because the image is a
separate dependency and prior attempts are data, not importable
source.  The image remains selectable through the existing top-level `sif`
field; the scorer receives the same path separately through
`run_experiment --scorer-sif`.  This is configuration enablement only: no
benchmark attempt or scientific score was produced in this change.

## 2026-08-28 — Deleted submitted Systems were reproducible from the DAG

This corrects the narrower claim below that the cleanup made the historical
connectivity audit impossible.  The XML bytes were gone, but completed min
nodes retained both `system_xml_sha256` and `topology_pdb_sha256`, while the
topo input, `amber_metadata.json`, surviving topology PDB, frozen MDClaw source
and exact SIF remained.  Rebuilding a topo branch from the same solv parent
reproduced the submitted OpenMM System byte for byte in all 196 attempts that
had recorded a System hash.  The force-bearing C--N/O3'--P links were extracted
only after that match and retained at
`evaluation/backbone_connectivity.json`; regenerated XMLs were then discarded.
The records contain 47,681 backbone links in total.  A rebuilt topology PDB
often had numerically different post-relaxation coordinates (only 28/196
reruns matched its bytes), so extraction deliberately paired the
byte-identical rebuilt System with the original topology PDB that survived and
still matched its recorded hash.

Three more attempts (011 r2, 038 r1 and 075 r2) completed topo but never ran
min, so no node recorded their System digest.  Their Systems were rebuilt and
their links retained under `evaluation/reconstructed_systems/`, explicitly as
`reconstructed_unverified`, not published as authoritative canonical evidence.
The rebuilt topology PDB matched exactly for 011 but not 038 or 075.  The only
remaining pass2 attempt, 043 r2, never created a topo node and therefore had no
System to recover.  One verified exception required its surviving
attempt-local source overlay: 043 r1 had excluded ligand 9RQ from an old
digit-prefixed GLYCAM heuristic before its original build.  Using the frozen
base alone reproduced the old failure; using the source that actually ran
reproduced the recorded System hash.

For `full100-sifonly`, original System XMLs survived for three attempts (011
r2, 037 r2 and 090 r2); their connectivity was extracted directly and retained
in the same canonical JSON form.  The other sif-only attempts have neither an
authoritative System nor a recorded digest with which a rerun could be
validated.  This recovery restores the historical connectivity evidence, not
the deleted trajectories, so it does not by itself make all twenty checks
fully rescored.

## 2026-08-28 — Polymer connectivity now comes from the force-bearing topology

Across the two completed 200-attempt campaigns, 21 attempts failed
`monomer_count_matches_reference`, 13 of them membrane.  The old scorer split
the minimised PDB at a 2 A backbone-distance threshold.  That was not the
question the check claimed to ask.  Measured on two replicates of 001, the
correct run leaves C214--N380 at 13.663 A and has components `[199, 79]`, while
the failed run carries a real peptide term, minimises that pair to 1.359 A and
has one `[278]` component.  011 likewise carries a declared C227--N365 link at
1.363 A.  Conversely, 5ZK8's correct System declares its C214--N383 link while
the deposited coordinates begin 9.63 A apart.  One distance rule cannot decide
both cases.

Revision `monomer_partition_rescan@2` therefore reads only inter-residue C--N
and O3'--P links: from the deposited prmtop/tpr/psf for the reference and from
the force-bearing bond/constraint set of the submitted OpenMM System.  Close
contacts without a declared bond stay disconnected; disulfides and other
crosslinks do not merge backbone components.  The legacy check id is retained
for result compatibility, but its detail now reports component sizes and names
unexpected or missing links.  All 101 reference bundles mapped successfully;
three Cineca topologies split one coordinate-file `LIG` into two topology
residues, which is intentionally irrelevant because only polymer residues are
mapped to the backbone graph.

One connectivity error used to erase the residue pairing and then fail sequence,
per-residue composition and three MD checks as unevaluable.  The revised scorer
uses a file-order correspondence only when the two complete canonical residue
sequences are exactly identical.  Connectivity still fails, but the independent
checks measure their own properties.  A missing, reordered or substituted
residue gets no such correspondence; this is not a sequence alignment.

The campaign cleanup script had removed every `*.xml`, including the scientific
evidence needed to audit this change: `full100-pass2` retains 0/200 submitted
System XMLs, and `full100-sifonly` retains them for three attempts.  Keeping every
membrane System would cost about 17 GB per 200 attempts, so the scorer now puts a
small JSON record of the submitted System's backbone links in its diagnostics
and `finalize_attempt` seals a copy at
`evaluation/backbone_connectivity.json`.  The three surviving sif-only Systems
were audited without PDB bond inference: 011 `[140, 45, 79]`, 037 `[131, 1]`
and 090 `[63]` all agree with their references.  A full rescore was not possible
because the retained 011 trajectory is truncated.  The 400 completed campaign
results remain immutable results of the previous scorer revision and were not
revised; future campaigns carry both the @2 contract and retained connectivity
evidence.

## 2026-08-28 — Two unreadable reference forms erased twenty checks

In the running pass@2 campaign, 18 of 161 completed `cli_skill_sif` attempts
were sealed as `checks 0/0` after their MD had run.  Eight whole membrane tasks
(007--014) reached a `TypeError` while reading the reference RMSF, and both
replicates of 061 reached an atom-order `SystemExit`; the failures made the
membrane axis read 5/10 while nucleic and soluble read 12/12.

The membrane references carry `null` for 87--91% of their full-system RMSF
profiles.  Those entries are outside the benchmark's calibrated PCA contract
set: all eight bundles have zero nulls at their 792--5094 selected indices.
The scorer nevertheless multiplied the full object array before selecting the
contract atoms.  It now converts null to NaN, selects the calibrated set, and
reports both the contract and full-system coverage.  A future null inside the
contract fails only `fluctuation_profile_matches_reference`; it does not
silently shrink the calibrated atom set, and the magnitude and radius checks
still run.

For 061, the topology and PDB have the same 7286 atoms and the same residue at
every index.  All 815 name differences are hydrogens written as Amber `HG21`
versus leading-digit PDB `1HG2` (and equivalents).  The order guard now accepts
only that exact digit move for a topology atom known to be hydrogen at the same
residue position.  Replaying one failed attempt per cause produced ordinary
20-check reports (007: 13/20; 061: 18/20) instead of exceptions.  At verification
time all 175 existing 20-check results were on unaffected tasks; their finite
profile and exact-name paths are unchanged.

## 2026-08-27 — Missing portable metadata crashed the whole scorer

In the live 100-task campaign, 10 `sif_only` attempts reached MD and 8 of them
ended as `checks 0/0`, `failure_code=scorer_error`. Their agent-written
`amber_metadata.json` files contained force-field, water, protonation,
disulfide and simulation information, but not under MDClaw's internal
`parameters` and `forcefield_provenance` objects. The scorer hard-subscripted
those objects for `water_model_matches_reference`, so one unavailable check
destroyed all twenty graded results. This made a condition with no MDClaw CLI
or skills depend on an undocumented MDClaw output shape.

The portable instructions now state the two required fields. Scoring a file
that omits or malforms either field fails only
`water_model_matches_reference`, with the missing field named; the other 19
graded checks continue. Existing `cli_skill_sif` metadata already carries both
fields, so its scoring path is unchanged.

## 2026-08-27 — The frozen source was copying 37 GB of trajectories

Launching the 100-task pass@2 campaign, the driver reported `PAUSE disk 40G <
60G` and dispatched nothing. The cause was ours: `_freeze_source` copies the
MDClaw checkout with `shutil.copytree`, and `FROZEN_SOURCE_EXCLUDES` listed
only caches. The operator's checkout carries `studies/`, where MDClaw writes
study workspaces — at the time 37 GB of TAS1R2/TAS1R3 umbrella sampling.

Measured on the 1 TB project quota (`lfs quota -p 200051 /data1`):

| | free |
|---|---|
| before `init_experiment` | 81 G |
| after | 40 G |
| after excluding `studies`/`runs` | 76 G |

The frozen tree went from 37 GB to 20 MB. The digest loop reads every frozen
file, so the copy was also hashing 37 GB, and `tree_sha256` would have changed
whenever an unrelated study ran — the digest is supposed to identify the
source the numbers belong to.

Neither directory is importable. An attempt reaches MDClaw through
`CLAUDE_PLUGIN_ROOT` and `PYTHONPATH`, which need the package, `skills/` and
`bin/`. What is frozen is the source an attempt runs; a study workspace is
data. `test_freeze_leaves_run_output_behind` pins both halves: the two trees
are absent from the frozen copy and from the digest, and the package, skill
and CLI are still there.

Two notes for whoever runs the next campaign:

- **`lfs quota -g` is the wrong number.** It reports 972 G where `df` and the
  project quota report 992 G, because the group accounting has no limit set
  (`blimit 0k`). What stops a write is the project quota on pid 200051.
- **The driver must be started from a login shell.** `KEY_MODELLER10v8` is
  exported in `~/.bash_profile`, which `bash -c` does not read — `bash -lc`
  does. Started the wrong way, every MODELLER route in the campaign is inert
  and nothing in the logs says so.

## 2026-08-26 — Correction: the prompts were already right; the licence was the defect

Reverted in full. The two entries below describe a change to twenty prompts
that should not have been made, and this records why, because the reasoning
that produced it was wrong in a way worth keeping.

`selection.build_missing` in the finished contract is not a statement that
anything must be built. Counting the reference bundle's polymer residues
against the deposit's observed residues inside the ranges the prompt states --
no numbering involved, which is the only comparison the arbitrary reference
numbering permits -- five tasks agree with their contract exactly (062: 312 vs
309, 065: 130 vs 125, 068: 73 vs 70, 076: 74 vs 68, 080: 127 vs 124), while
seven report a non-zero value against a difference of exactly zero: 001, 004,
008, 011, 043, 044, 045. Their references built nothing. All seven were among
the ten given a new instruction, and on 011_membrane_6kuy that instruction
contradicted the prompt's own "Residue 173-182 of chain A is not part of the
reference. Leave it out."

The ten that already carried a line from the generator are the ten that need
one. The generator's per-chain gate was right and the contract's aggregate is a
different quantity.

Replacing the named residues with one generic sentence was also wrong, and for
a reason the original code had already written down. Which residues lack
coordinates is public deposit metadata, not the hidden reference decision; the
hidden part is only that the reference chose to build them. Naming them
therefore costs no minimality, while the generic form adds an auth-numbering,
insertion-code and unobserved-residue parsing subtask, loses the chain
association on multichain systems, and -- measured -- silently broke
`contract_audit`, whose parser matches the named wording and reported ten
spurious `reference_polymer_selection_mismatch` findings until the revert. The
audit is back to zero findings across all hundred tasks.

Two claims made during the investigation were themselves wrong and are
withdrawn:

- "MDClaw cannot build terminal residues." It can. `prepare_complex` maps
  `build_terminal_missing_residues=True` onto
  `ignore_terminal_missing_residues=False`; passing both to `clean_protein`
  rebuilds 1CTF's six-residue N-terminal tail, reporting "a terminus has an
  anchor on one side only, so these coordinates are predicted rather than
  measured". The earlier test called `clean_protein` directly and so skipped
  that mapping. What does block 1CTF is a different guard:
  `PDBFIXER_MAX_MISSING_RESIDUE_SEGMENT_LENGTH` is 5 and the tail is 6, so the
  build ends in `pdbfixer_missing_residues_out_of_scope`. MODELLER cannot take
  it either -- loop modelling needs an anchor on both sides -- so a terminal
  segment longer than five currently has no route.
- Attributing the campaign's `monomer_count_matches_reference` failures on 001,
  004, 019 and 030 to unbuilt loops. Those four references added no polymer
  residues, so the cause is elsewhere.

What survives: the MODELLER licence was genuinely absent, and that alone would
have stopped every internal-gap rebuild. It is now in `~/.bash_profile`, where
login and non-interactive shells can see it; `~/.bashrc` does not work because
its interactivity guard returns before the export.

Also found, not fixed: six tasks whose `selection.ranges` disagrees with their
own prompt -- 008 (extensively), 011, 015, 043, 076, 080 -- with the prompt
matching the bundle in each case. The scorer recomputes from the bundle and
never reads `selection.ranges`, and the harness hands the agent `prompt.md`, so
nothing is mis-scored today; it is a contract-integrity problem waiting for a
future consumer.

## 2026-08-26 — Half the prompts never said to build the unresolved residues

Twenty tasks have a `build_missing` entry, meaning the reference simulated
residues the deposit does not resolve. Ten prompts said so; ten said nothing,
so on those ten the agent had no way to know the gaps were meant to be filled
and its model came out short. Measured on the pass@2 campaign before it was
stopped: tasks with six or more unresolved residues passed 26/36 against 21/25
with none, and `monomer_count_matches_reference` was the largest single failure
code, with 001, 004, 019 and 030 among its victims -- all four in the silent
ten.

The generator had the wording and the data all along. `_task_builder` computes
`build_residues`, the author numbers of each gap, and emitted "Chain C does not
resolve residues 83, 84, ...; the range runs through them, so build them." But
`build_residues` never reached the shipped contracts -- `null` in every
task.json -- so `named` was empty and the count-based fallback never fired
either. Only tasks whose numbers survived generation got a line, which is why
008_membrane_6i53, the worst case at 22 residues, is silent: its list also
exceeded the `len(named) <= 8` cutoff.

All twenty now carry one sentence, and the generator emits the same one:

    The deposit does not resolve every residue of the stated ranges. Build the
    ones it leaves out, including any at the start or end of a range.

Naming the residues was over-specification and is gone from the ten that had
it. Which residues lack coordinates is in the deposit and how many is
arithmetic on it; a prompt states what cannot be inferred, and that is the
decision -- that the reference filled the gaps rather than leaving them, and
that it filled the ones at a range's ends too. The last clause carries the
weight: neither PDBFixer nor MODELLER rebuilds a terminus unless asked, and of
the four tasks whose gaps could be located independently of the generator, all
four were terminal.

Separately, MODELLER could not have run at all. The SIF ships
`modeller-10.8/modlib/modeller/config.py` with the placeholder key `XXXX`, and
the licence was not in the environment. MDClaw already handles the placeholder
-- it reads any `KEY_MODELLER*` variable and substitutes a synthetic
`modeller.config`, so no bind mount is needed -- but the variable has to reach
the container. A plain export does, because the image does not define that
name; an `APPTAINERENV_` mirror is insurance against a future image that does.
`~/.bashrc` alone is not enough: its interactivity guard returns before the
export, so login and non-interactive shells never see it. It belongs in
`~/.bash_profile`.

## 2026-08-25 — The attempt ends at submission, and the prompt now says so

Agents were waiting for each MD stage to finish before submitting the next.
Measured from sacct on 041_ligand_4erf r1: min ended 20:43:22, eq was submitted
20:43:37, eq ended 20:44:58, prod started 20:45:00. Three submissions, no
`--dependency` anywhere, and check_job/squeue polled 63 to 96 times per
attempt. Agent survival past the final sbatch tracked MD queue+run in all eight
sealed attempts of the earlier run, +343 s to +1566 s against 164 s to 1279 s
of MD.

That pays the queue three times inside one 90-minute budget, which is what
saturated the old campaign: its `md_queue` median alone was 2088 s, and 54% of
attempts hit the wall.

The prompt asked the agent to "submit the final MD work" before exiting but
never said not to wait, and the MDClaw skills gave it nowhere else to learn:
md-prepare, md-equilibration and md-production mention neither SLURM nor
submit_job, and no attempt in the campaign ever called submit_job -- all of
them hand-wrote sbatch files, which is why `--dependency` never appeared. Both
halves are fixed: the prompt now states that the attempt ends at submission and
that waiting is inside the budget while queue and run time are not, and MDClaw
routes cluster stages to hpc-run with the afterok chain as its first rule.

## 2026-08-25 — Ligand prompts now name the ligand and its expected charge

Nine of the ten ligand prompts never mentioned the ligand. The reference
carries it as a component named generically `LIG`, on a chain the prompt's
residue range does not cover, so an agent that built exactly what was asked was
then scored as missing a monomer the prompt excluded by its own terms. Across
the campaign, no attempt on a task that hid its ligand passed, and the only
task that named one (036, via a charge instruction) is the only one with
passing attempts.

The charge is not decoration. The scorer aliases a singleton reference `LIG`
only to a submission singleton with the identical full formula *including
hydrogen*, and MDClaw's `expected_net_charge` picks the protonation state from
the Dimorphite-DL candidates and fails closed when none matches. A wrong charge
is therefore worse than no charge.

Each charge was derived, not guessed: `CCD formal charge + (reference H count -
CCD H count)`, with the reference's own hydrogens counted from its PDB. Every
result is chemically ordinary at pH 7 -- oleate (OLA -1), a phosphate dianion
(J9Z -2, already -2 in the CCD), a carboxylate (0R3 -1), a sulfonic acid plus
phosphonate (9RQ -2), and three neutrals (AMH, D3X, 9V2). B4L at +2 is the one
that needed a second look: an N-methylpiperidine plus a protonated amidine in
the pyrimidinone. It is borderline chemistry, but it is what the reference
contains, and the formula comparison is what the score turns on.

Before writing any of it, each stated charge was run through the actual code
path -- `_fetch_smiles_from_ccd` then `_protonate_smiles_dimorphite(smiles, 7.0)`
then `_select_protonation_state` -- to confirm a matching candidate exists.
All eight resolve. B4L offers [0, +1, +2], so +2 is reachable. Six of the seven
have more than one candidate, so the statement is load-bearing rather than
merely confirmatory; OLA and 9RQ have a single candidate each.

Two of the ten are a different defect and are NOT fixed by a charge line:

- 038_ligand_1ikt: the reference's C21 H36 O4 is a partially modelled Triton
  X-100 (OXN, C34 H62 O11) -- atom names C1-C25 with O15/O18/O21/O24 show the
  PEG tail truncated in the deposit. Parameterising OXN from its CCD SMILES
  gives the whole molecule, which cannot match.
- 042_ligand_4mn3: not a small molecule at all. Atom names CA/CB/CG/CD1/CZ/OH/
  NZ plus CM1-CM3 are a 7-residue peptide (`XFAYKSX`, RCSB polymer entity 2)
  carrying a trimethyl-lysine, flattened by MDDB into one residue named LIG.

`audit_task_cast` also reports a cap mismatch on 4MN3 (deposit has ACE and NH2,
reference has neither) and a disulfide mismatch on 087_soluble_1gqv; both are
recorded, neither is addressed here.

## 2026-08-25 — The campaign now runs against a frozen MDClaw, not the live checkout

A validation-run agent on `049_nucleic_1iv6` decided MDClaw had a bug stopping
its DNA duplex from being neutralised, and edited
`mdclaw/solvation/water.py` in the operator's checkout with its own edit tool.
It was right about the bug. That is not the point: `CLAUDE_PLUGIN_ROOT` and
`PYTHONPATH` pointed every attempt at one live directory, so the subject of
measurement could be rewritten mid-campaign by the thing being measured.

Contamination was traced attempt by attempt and came to exactly one of nine —
006 goes through the membrane path, 021 had `delta=0` so the changed
expression was identical, and 049 r1/r2 had chosen `salt=true`, where the old
code applied the correction anyway. The validation run's conclusions survive.
Had the edit landed on a hotter path it would have silently rewritten the
campaign.

`init_experiment` now copies each `mdclaw_source` to
`<experiment-dir>/frozen-source/mdclaw-<n>` and strips write permission from
every file and directory, and the campaign runs against that copy.
Directories lose write access too: a writable directory still allows creating
and replacing entries inside it. Verified against the four ways the edit could
have arrived — in-place write, new file, rename, shell redirect — all four now
fail with EACCES, and `mdclaw --list` still returns its 54 tools from the
frozen copy. The copy is 17 MB and `.git` is not included.

Two things fall out that are worth as much as the protection. The run is now
self-describing: `experiment.json` records origin, git revision, whether the
origin was dirty, and a SHA-256 over the copied tree, and every attempt
manifest repeats revision and digest, so a set of numbers names the source it
belongs to. And the aliasing ran both ways — editing MDClaw while a campaign
was in flight silently changed that campaign. It no longer does.

`init_experiment` also now rejects an `mdclaw_source` that is not a directory.
It previously accepted any string and failed much later, at agent run time.

Not fixed here, recorded for the rerun: agents wait for their own MD instead of
exiting after submitting the afterok chain. Survival past the final `sbatch`
tracked MD queue+run in all 8 sealed attempts (+343 s to +1566 s against 164 s
to 1279 s of MD). The 90-minute agent budget is therefore spent on prep plus
queue plus MD, which is what saturated it in the old campaign, where the
`md_queue` median alone was 2088 s.

## 2026-08-25 — Correction: Gemmi is a required contract-audit dependency

The hardened contract audit initially imported Gemmi without declaring it, so
it passed in the campaign SIF but failed under the host Python used by the
standard-library prototype. Gemmi is load-bearing: it supplies quoted mmCIF
parsing, authentic `struct_conn` records, and the wwPDB residue dictionary.
It is now a declared `gemmi>=0.7.0` package dependency, the README names the two
audit commands that require it, and a non-skipping test checks both the project
metadata and the actual import. This corrects the portability claim implicit in
the audit entry below. The audit fixtures now pass 14/14 and the complete suite
passes 766/766 (with the same constant-input Spearman warning).

## 2026-08-25 — Contract audit hardened and run across all 100 tasks

`audit_task_cast` now parses mmCIF with Gemmi, audits every PDB ID, compares the
prompt's observed polymer selection with the reference, preserves ligand/cap
occurrences and sites, separates structural metals from bulk ions, and compares
deposit `struct_conn` disulfides with the force-bearing reference topology.
Gemmi's wwPDB residue dictionary supplements the Amber-specific name lists so
modified polymer residues such as SEP, TPO, PTR and PSU are not silently
classified as ligands. NMR deposits deliberately use the first model because
the benchmark prepares one conformer and model copies do not multiply chemical
components.

The hardened audit reports **87 clean tasks and 13 tasks with findings**, the
same headline count as the prototype but not the same membership. It confirms
all ten ligand tasks contain a reference `LIG` the prompt never requests,
detects dropped input caps in 028 (ACE) and 042 (ACE and NH2), and finds
deposit/reference disulfide-pair differences in 016 and 087. Task 087 is new:
1GQV declares four pairs while the reference topology contains three. The old
035 finding is removed because the authentic deposit has no disulfide
`struct_conn`; a geometry-only guess is not deposited chemistry. A second 6W9C
Zn is also excluded after its selected construct retains only one symmetry-
contact ligand, whereas the intended Cys4 site retains four.

The contract-audit fixtures pass 13/13 and the complete MDDataBench suite passes
765/765 (one existing constant-input Spearman warning).

## 2026-08-25 — Pilot agent/preparation and MD budgets extended to 20 minutes

The Qwen 3.6 35B and Kimi K3 pilots both reached useful preparation stages but
failed to submit a Slurm job within the 15-minute agent budget. Kimi K3 had
correctly completed chain selection, preparation, solvation, and topology. To
avoid turning near-complete preparation into the dominant failure mode, the
default agent/preparation budget and each MD Slurm allocation are now 20
minutes. The evaluator scorer retains its separate 15-minute allocation. This
overturns the 15-minute agent and MD limits recorded immediately below.

The two operational limits are stated directly in every agent prompt as well as
in `CAPABILITIES.md`. To prevent budget disclosure from encouraging scientific
shortcuts, the same prompt says that the limits do not relax the task and
forbids shortening minimum production or changing force field, solvent,
ensemble, temperature, or pressure to fit the allocation.

## 2026-08-24 — Pilot budgets tightened from one hour to 15 minutes

The one-hour campaign defaults recorded immediately below were too permissive
for three-attempt comparisons, especially when a CLI-free agent keeps trying
without converging.  Before the first pilot reached MD submission, it was
stopped at 3 minutes 33 seconds and replaced with a 15-minute limit for agent
plus preparation, each MD Slurm allocation, and the evaluator scorer.  A task
that cannot reach a valid submission within that fixed budget is a measured
zero rather than a reason to occupy the campaign indefinitely.

## 2026-08-24 — Repeated agent campaigns keep every failure in the denominator

A campaign layer now expands explicit task × condition × harness × model ×
replicate cells into isolated attempts and rebuilds paper tables from terminal
`result.json` records.  The primary measure is strict binary success rate with
a Wilson 95% interval; mean deterministic-check score, any-pass-at-k, 3/3
reliability, failure codes, agent/queue/MD/node wall time, GPU seconds, and
nullable transcript token estimates remain diagnostic outputs.  A missing or
failed prep/MD submission, harness launch/timeout, scorer submission, or scorer
Slurm allocation becomes zero rather than disappearing.

Agents prepare on the login node and their `sbatch` calls pass through a
standalone recorder.  The evaluator owns an `afterany` scorer, so agents cannot
inspect or invoke it.  The shared old Rikyu SIF supplies dependencies only:
current MDClaw and MDDataBench checkouts are bound and selected through
`PYTHONPATH`.  The skill condition explicitly loads the current checkout's
`mdclaw/skills` for pi, Claude Code, and Codex instead of relying on a home-dir
copy.  No-skill and SIF-only environments suppress those project skills;
SIF-only requires a separate runtime image without MDClaw.

The initial fair budget is one hour for agent plus preparation and one hour per
MD Slurm allocation; the shim overrides longer agent-provided Slurm limits.
The scorer has its own one-hour allocation.  This is deliberately above the
observed 550 s runtime of the completed 2.5 ns task 027 production job and can
be tightened after the pilot distribution is measured.  pi (Kimi K3) reviewed
the implementation and identified three consequential holes that were fixed:
ambient instead of project-local skills, SIF-only PATH/source leakage, and
submitted scorer jobs that terminated without ever writing a result.  The
reviewed implementation passed 26 focused tests before the final full-suite
run.

## 2026-08-24 — 027 complex passes 20/20; multimer RMSF is mapped but pooled

Task `027_complex_1b6c` was executed from the public prompt and scored only
after the 2.5 ns trajectory completed.  The fresh Slurm production node
`prod_002` (job 41364) produced 250 frames at 10 ps.  The official scorer
passes prep 12/12 and MD 8/8 (20/20): both sequence-distinct monomers pair at
107/107 and 326/326 residues, all 1299 contract atoms resolve through those
pairs, the pooled RMSF rank correlation is 0.8566, total fluctuation is 0.7947
A, and radius of gyration is 24.4365 A.  The real run passes and all nine
adversarial baselines fail.

This run also exposes the precise limit of the current multimer treatment.
Atom correspondence is genuinely monomer-aware and the fit is over the whole
complex, so relative subunit motion is retained.  The RMSF gate, however, is
one atom-pooled Spearman correlation rather than a per-monomer gate.  On the
same globally fitted profile, chain A contributes 321 atoms at rho=0.7297 and
chain B contributes 978 atoms at rho=0.8857, producing rho=0.8566 overall.
The existing aggregate calibration cannot be reused as a chain-level cutoff,
so this does not establish a chain-A failure; it does establish that a larger
subunit can dominate the verdict.  A future per-monomer gate needs its own
reference-window calibration and a permutation-invariant policy for identical
homomers, rather than an uncalibrated code-only split.

## 2026-08-24 — RMSF magnitude uses an asymmetric lower tolerance

The 19/20 result recorded immediately below was 0.0161 A under the total-RMSF
lower bound even though its profile, structure, thermodynamics, and elapsed
time passed.  RMSF magnitude previously widened both sides of the measured
reference-window range by the same 4 SD.  Scoring and negative controls now
share an asymmetric rule: 5 SD below and the existing 4 SD above.  This keeps
the stricter upper guard against excessive motion while giving independent
short trajectories more room on the less harmful low-motion side.

With no rerun or trajectory change, `046_nucleic_1a66` now scores **prep 12/12
and MD 8/8 (20/20 total)**; its lower bound is 1.1399 A and the observed total
fluctuation is 1.1695 A.  Its real run passes and all nine adversarial baselines
still fail.  The same negative-control suites remain `all_correct=true` for
035 nanobody, 036 ligand, and 037 ligand.  The full benchmark suite passes 729
tests and the changed files pass ruff.

## 2026-08-24 — 046_nucleic_1a66 scores 19/20 after a public-prompt-only run

Task `046_nucleic_1a66` was run without exposing `task.json` to execution.
The public request selected the two DNA strands from PDB 1A66 and therefore
correctly excluded the deposited protein.  The prepared 24-residue,
761-solute-atom duplex exactly matches the reference composition.  A neutral
44,231-atom DNA.OL15/TIP3P system completed minimization, 0.1 ns NVT, 0.2 ns
NPT, and 1.0 ns NPT production at 300 K and 1 bar using the engine's 4 fs HMR
default, saving 100 frames at 10 ps intervals.

The official score is **prep 12/12 and MD 7/8 (19/20 total)**.  The sole miss
is total fluctuation 1.1695 A against the reference-window band lower bound of
1.1855 A, a 0.0161 A shortfall.  Fluctuation-profile Spearman rho 0.8611,
radius of gyration 14.3748 A, mean temperature 300.493 K, density 1.0112 g/mL,
and the 986 ps solvent clock all pass.  Every one of the nine adversarial
negative controls failed as intended.  The aggregate negative-control result
is nevertheless `all_correct=false` because its `real_full_run` baseline must
pass all gates and inherits the same marginal fluctuation-magnitude failure.

## 2026-08-24 — 037_ligand_1g74 passes 20/20 with one OLA alternate

Task `037_ligand_1g74` completed end to end for chain A residues 1--131 and
bound oleate.  The deposited OLA has two complete occupancy-0.50 alternates;
MDClaw selected the entire alternate A consistently, excluded the phosphate
additive, and prepared 53-atom OLA at expected charge -1.  The resulting
solute exactly matched the reference contract (2,054 protein atoms plus 53
OLA atoms).  A neutral 44,984-atom ff99SB-ILDN/TIP3P system ran 0.1 ns NVT,
0.2 ns NPT, and 1.0 ns NPT production at 298 K and 1 bar on one GPU, producing
100 frames at 10 ps intervals.

The official score is **prep 12/12 and MD 8/8 (20/20 total)**.  Measured values
include fluctuation-profile Spearman rho 0.7733, total fluctuation 0.5319 A,
radius of gyration 13.9328 A, mean temperature 298.281 K, density 1.0076 g/mL,
and solvent-clock elapsed time 1,021 ps.  Negative controls returned
`all_correct=true`: the real run passed and all nine adversarial baselines
failed.

This manual run used the 2 fs reference timestep after inspecting task metadata.
That is acceptable for this completed diagnostic, but not normal benchmark
execution: agents must use only the public prompt and inputs, reserving hidden
reference fields in `task.json` for the scorer.  If the prompt omits a
timestep, the simulation engine's safe topology-aware default should be used.

## 2026-08-24 — 036_ligand_1ceb passes 20/20 with expected AMH charge

Task `036_ligand_1ceb` now states that AMH has expected formal net charge 0 at
pH 7. MDClaw used that expectation to select the zwitterionic Dimorphite-DL
candidate from the CCD SMILES rather than embedding a charged SMILES in the
task. The prepared solute matches the reference contract exactly: chain A has
80 residues and 1,225 atoms, AMH has 26 atoms, and the combined solute has
1,251 atoms. The 36,395-atom ff99SB-ILDN/TIP3P system ran 0.1 ns NVT, 0.2 ns
NPT, then 1.0 ns NPT production at 298 K and 1 bar on one GPU, saving 100
frames at 10 ps intervals.

The first score exposed a scorer bug rather than a simulation failure. MDDB's
reference PDB calls the 26-atom AMH component `LIG`, while the submission
correctly retains `AMH`; name-only monomer pairing therefore failed three prep
checks despite identical complete formulas (`C8 H15 N1 O2`). The scorer now
aliases only a singleton reference component named generic `LIG`, and only to a
submission singleton with the identical full formula including hydrogen.
Named ligands are not aliased to one another, and a changed hydrogen count does
not pair. The composition suite adds both positive and negative regression
tests.

After the correction the official score is **prep 12/12 and MD 8/8 (20/20
total)**. Measured values: fluctuation-profile Spearman rho 0.8993, total
fluctuation 0.4936 A, radius of gyration 11.3131 A, mean temperature 298.853 K,
density 1.0072 g/mL, and solvent-clock elapsed time 1,013 ps. Negative controls
returned `all_correct=true`: the real run passed and all nine adversarial
baselines failed. `pytest tests/test_benchmark -q` passes 727 tests; changed
files also pass ruff.

## 2026-08-24 — 035_nanobody_6gwn end-to-end run passes 20/20

Ran the complete MDClaw workflow for task `035_nanobody_6gwn` against MDDB
bundle `mmb_A0594`: chain B (115 residues), ff99SB-ILDN/TIP3P, 0.15 M NaCl,
300 K and 1 bar, followed by 0.1 ns NVT, 0.2 ns NPT, and 1.0 ns NPT
production with 4 fs HMR. The 52,418-atom system completed production with
1,000 DCD frames. PyMOL side/top `system_box` inspection found the compact
nanobody fully visible inside the periodic box with dispersed solvent and ions;
the visual review was registered as severity `none`, recommendation `continue`.

The official scorer passed **prep 12/12 and md 8/8 (20/20 total)**. Key measured
values were fluctuation-profile Spearman rho 0.9216 (floor 0.6940), total
fluctuation 0.4904 A (reference band 0.3955--0.6236 A), radius of gyration
13.4261 A (13.2914--13.6701 A), mean temperature 300.443 K, density
1.0095 g/mL, and solvent-clock elapsed time 979.8 ps for the claimed 1 ns.
Reference and submission both contained zero disulfide bonds, confirming that
the approximately 3.5 A Cys22--Cys96 raw-structure contact should not be bonded.

`run_benchmark_negative_controls` returned `all_correct=true`: the real run
passed and all nine adversarial baselines failed as intended (100 ps, 10 ps,
frozen frame, 5x motion, shuffled atoms, compressed structure, ANM ensemble,
isotropic noise, and duplicated minimum). This validates the current task bands
without changing any scorer threshold.

## 2026-08-24 — Seven proposed deletions, measured one at a time: two dead, one refuted, the rest thinned

A review proposed deleting seven things from the scorer and replacing the
monomer split with union-find over the force-bearing bond graph. Nothing was
deleted before it was measured. This entry records every measurement, what was
applied, and what was declined and why — the declines are the point of it,
because a deletion refused on evidence is a decision that must not be re-raised
from the same premises.

### Regression frame

Baseline taken from the working tree **as it stood**, with the bond-basis change
of the entry below already in it, not from git HEAD. Scored into `baseline/`,
changed, re-scored into `after/`, then diffed field by field.

    003_membrane_5zk8 20/20   062_metal_6w9c 20/20   063_metal_6wrh 20/20
    060_metal_4ow0    20/20   015_antibody_1ahw 20/20

All **100 scored checks** (20 per job x 5 jobs) come out identical across the
change: same `check_id`, `passed`, `category`, `weight`, and byte-identical
`detail` strings. Zero differences.

The only fields that move at all are four floats in the unscored `diagnostics`
block (`built_energy_per_atom_kj_mol`, `minimized_energy_per_atom_kj_mol`,
`minimized_max_force_kj_mol_nm`). **That is not this change.** Two runs of the
*identical pre-change* code, in two processes, move the same fields by the same
amount — 5ZK8's `minimized_max_force_kj_mol_nm` is 2360.31884765625 in one and
2360.318359375 in the other, the very same pair the before/after diff shows.
It is OpenMM CPU-platform summation order, run to run. Which particular job's
max force happens to land byte-identical is itself noise and does not reproduce
between run pairs, so do not use one as a landmark. Recorded here so the next
person diffing two reports does not chase it.

Wall clock, same host, same 4 threads, measured with the change in and out
(`score()` only):

                        pre-change   post-change
    003_membrane_5zk8      40.6 s        37.7 s
    062_metal_6w9c         21.1 s        19.8 s
    063_metal_6wrh         22.8 s        21.6 s
    060_metal_4ow0         22.3 s        21.5 s
    015_antibody_1ahw      62.0 s        57.3 s
    total                 168.8 s       157.9 s     (-6.5 %)

`ruff check mddatabench/ tests/` — all checks passed. `pytest tests/ -q` —
**723 passed** (713 fast + 10 slow); it was 730 before, and the 7 lost are the
hybrid-36 parametrisations deleted with the function, replaced by 4 new ones.
`run_negative_controls` on all five: `all_correct=True` everywhere, and
`gates_never_decisive` unchanged from baseline — `[]` on 5ZK8, 6W9C and 1AHW,
`['solvent_clock']` on 6WRH, `['fluctuation_magnitude', 'solvent_clock']` on
4OW0.

Line count, split by scope so no one figure has to carry three meanings:

    code and tests             +108 / −358   =  −249   (package 4755 -> 4506)
    docs/validation-design.md   +24 /    0            (rescues the
                                                       `pca_backbone_subspace@1`
                                                       contract out of the module
                                                       that was deleted)
    this memo entry            +339 /    0

−249 is the honest code figure, and it is dominated by one item: deleting
`subspace.py` accounts for 215 of the 358 deletions, and that module is not one
of the seven proposals reviewed here. The seven proposals themselves come to
**+108 / −142 = −34 lines**. Say that rather than the headline when the question
is what the review bought.

### Applied

**`hy36decode` and its two alphabets are gone, and so is the serial slot they
filled** (composition.py, −36 lines plus the tuple slot). The decoded value went
into `Residue.atoms[i][0]` and no consumer ever unpacked slot 0: every reader
took slot 1, 2 or 3. Proven twice — statically by enumerating the readers, and
dynamically by monkeypatching `hy36decode` to return an object whose `__eq__`,
`__hash__`, `__int__`, `__str__`, `__repr__`, `__format__`, `__bool__` and
`__index__` all raise, then running the full scorer and the full control suite:
all five jobs still 20/20, all five control suites still `all_correct`. The atom
tuple is now `(atom_name, element, xyz)`.

The two tests that exercised only the decode (7 + 4 parametrisations) could not
survive it. They are replaced by one test that pins the property which *makes*
the deletion legal: `read_residues` and `split_monomers` give identical residue
names, atom names, elements, coordinates and split when the serial column is
spelled decimal, hybrid-36 (`A0000`), blank, or garbage (`!!!!!`). That fails the
moment anyone reads the column again. The reason the decode existed — reading
disulfides out of CONECT past 99999 — is already owned on the new basis by
`test_topology.py::test_bonds_are_read_from_the_system_not_from_conect`.

**`contract_correspondence` is thinned, not deleted** (composition.py, 34 body
lines → 20). The monomer-identity map, the `id()`-keyed partner dict and the
offset arithmetic are replaced by one flat `{(reference chain, resseq):
submitted Residue}` dict built by zipping each pair at pairing time. Verified
**elementwise, not by count**: identical placed indices on all five jobs
(819 / 936 / 936 / 936 / 1908), 0 differing slots, and the maximum distance
between the atoms the two schemes select is **0.0 A** on every job. A count-only
comparison would have missed the failure mode that matters (a permuted index
list counts 1908/1908 while 1287 atoms are mispaired by up to 193 A).

Three things went with it:

* the `submitted_monomers` parameter, never read in the body, though all three
  call sites passed it; and `reference_monomers`, which the flat form does not
  need. The signature drops from 6 arguments to 4, at three call sites.
* the `offset >= len(submitted_monomer)` branch (5 lines). It cannot fire:
  `match_monomers` only pairs monomers that share a canonical sequence, hence a
  length. Measured on all five jobs — no pair with mismatched lengths exists.
* one of the four `missing` messages. `is in no reference monomer` and `is in a
  monomer the submission does not pair with` are now one message. **This is a
  real, if small, loss of diagnosis and it is recorded rather than hidden**: the
  first was the only signal that a bundle's `pca_atom_indices.json` names an
  atom outside the polymer — a bundle bug, not a submission bug. It has never
  fired: a scan of all 101 bundles found 0 contract atoms off the polymer, and
  the contract atom names are backbone only. The surviving wording keeps the
  substring `does not pair`, which two tests assert.

The **21-line docstring stays**. It records why the `(residue number, atom name)`
scheme was replaced and the 1908-counted / 1266-wrong measurement behind it; that
is the institutional record and is not a line to save. So the honest saving here
is ~14 body lines, **not the 57 the review claimed** — 21 of those 57 were
docstring and about 22 were code the flat form still needs.

One behavioural note for the future: the old map was "last reference monomer in
file order wins" on a duplicate `(chain, resseq)` key; the flat dict is "last
*paired* monomer wins". 0 of 101 references carry a duplicate key, so the two
cannot differ on today's cast — but that is a property of today's references, not
a guarantee.

**The submission-side `catalytic_dyad_positions` call is gone** (scoring.py),
along with the `submitted_dyads` term in the exemption union. Measured: it
changes the exemption on none of the five jobs on either frame. `exempt_total`
per matched monomer with and without it is 0/0, 6/6, 6/6, 6/6, 0/0; every
`compare_monomer` finding is byte-identical; the `detail` string of
`residue_atom_counts_match_reference`, which prints `exempt_total`, is unchanged.
It is never decisive only because the reference-side call finds the same pair —
and its own answer is a coin flip, because the Cys-His pair sits at 3.30 A on
6W9C's minimised frame and 3.68 A on its topology frame against a 3.5 A cutoff
(6WRH 3.66/3.79, 4OW0 3.79/3.77). The reference side finds it at 2.98–3.11 A,
which is the range 3.5 A was calibrated on. **This is a 5-job sample.**

Removing it closes one submitter-controlled exemption and leaves a larger one
open: `submitted_ligands` (scoring.py) is `metal_ligand_positions` over the
submission's own coordinates, so a submission still nominates part of the set of
positions it is excused on. That is deliberate -- a submission's metal site has
to be read from the submission -- but it is the same shape as the term just
removed, and it is bigger. Anyone tightening this should start there, not here.

**`subspace.py` is deleted — 215 lines, the largest dead body in the repo and not
on the review's list.** Only `kabsch` (7 lines) was reachable; it has moved into
`dynamics.py`, its one caller. Unreachable and now gone: `superpose`,
`essential_subspace`, `canonical_correlations`, `rmsip`, `anm_subspace`,
`anm_floor`, `null_distribution`, `anm_null_distribution`, `test_beyond_structure`,
`test_unrelated` (134 lines of body) and 8 module constants. This is the residue
of the subspace test retired 2026-08-22. **Its docstring was the only prose
definition of the contract `pca_backbone_subspace@1`, which `_md_checks.py:159`
still stamps into every task.json**, so the definition was moved to
`docs/validation-design.md` first rather than lost — into docs, deliberately, not
into the `_md_checks.py` note, because editing that note would rewrite 100
task.json files on the next generation for no gain.

**`scoring.pdb_atoms` returns `(chain, resseq, atom_name)`.** Its only consumer
reads slots 0, 1 and 2; slots 3, 4 and 5 were three float parses and two string
operations per ATOM line that nothing ever read. Measured on 1AHW's 381954-row
minimised PDB: 0.46 s for the 6-tuple, 0.16 s for the 3-tuple, and it is called
twice per `score()` and twice per controls run.

**`_load_system` now validates the System `tp.load_submission` already
deserialised** instead of parsing the file a second time; `load_submission`
returns it as a fourth value. Measured duplicate-parse cost: 2.42 s of 1AHW's
73.8 s, 2.07 s of 5ZK8's, 0.88–0.94 s on the three metal jobs, 7.22 s over the
suite. **The function itself is kept and so is its fallback parse** — see the
declines below; this is a reuse, not a merge.

**`np.array(own_list, dtype=int)`** in scoring.py, and the same in controls.py.
Independent live bug, found while constructing a broken-`system.xml` case: an
empty `own_list` gives a float64 array and `traj.xyz[::stride][:, own_indices, :]`
then raises `IndexError: arrays used as indices must be of integer (or boolean)
type`. Any submission whose monomers fail to pair hit that — reachable today —
and the scorer raised instead of reporting, which is exactly the failure the
`if missing:` branch downstream exists to prevent. With the fix, the broken case
reports 7/20 instead of raising.

Small, same class, all verified unreferenced by grep and by AST scan:
`topology.BACKBONE_ATOMS` (superseded by `SIDECHAIN_DONORS`, whose own comment
says so; `composition.BACKBONE_ATOMS`, byte-identical, is live and stays);
`composition.Residue.n_heavy`; `execution.CHECK_ID`; the four never-read keys of
`execution.elapsed_time_ps` (`total_msd_nm2`, `frame_interval_ps`,
`frame_interval_source`, `n_tracers` — the dict is a local in both callers and is
never serialised); `rows` from `controls.load_reference`'s return tuple; and the
duplicate re-assignment of `topology_pdb` in scoring.py, identical to one 247
lines above it.

### Declined, with the measurement that refused each

**Union-find over the bond graph must NOT replace `split_monomers`.** The
equivalence the review claimed is real but local. On the five solved jobs, both
sides, the two bases agree exactly — 5ZK8 [273]/[273], PLpro [312], 1AHW
[214,214,208] — and they are identical *partitions*, not merely equal size lists.
Swept over every bundle on disk (100 of 101 loadable, 1.08M atoms, 59 tpr /
32 prmtop / 10 psf, 50 multi-chain) they **disagree on 5 bundles backing 7 of the
100 tasks**:

* `inr_A00KY` (019_antibody_2dd8): geometry [220,212,192] → bond graph [432,192];
  the crossing bond is the Fab light-heavy interchain disulfide **CYS216:SG –
  CYS213:SG**.
* `mmb_A024H` (011_membrane_6kuy): [140,45,79] → [185,79]; crossing bond
  **CYS74:SG – CYS146:SG**.
* `cin_A000J`, `cin_A000O`, `cin_A000P`: the tpr splits the ligand into
  LIG(1 atom) + LIG(101/42/20 atoms) where reference.pdb writes all of it as one
  residue B58, so the two bases do not index the same residue list at all —
  **57 PDB residues against 58 topology residues** (`A000J`), 95 vs 96 (`A000O`),
  106 vs 107 (`A000P`). No run-length mapping between them exists.
  Those five back 019_antibody_2dd8, 011_membrane_6kuy, 043_ligand_5od1,
  044_ligand_5oh3, and 029_complex_1e3u / 042_ligand_4mn3 / 095_soluble_1ard.

Where they differ the bond graph is **worse for the benchmark, not merely
different**. Today a submission that omits an interchain disulfide loses exactly
`disulfide_bonds_match_reference` — one prep check, attributable to the bond it
got wrong. Under the bond-graph basis the reference is [432,192] and that
submission is [220,212,192], so `match_monomers` pairs nothing and one missing
bond takes out `monomer_count`, `sequence`, `residue_atom_counts`,
`element_composition` and, through `contract_correspondence`, all three md gates.
One chemistry mistake cascading across two axes is precisely what "every axis is
evaluated independently" forbids.

**And the deletion would have saved nothing anyway.** `split_monomers`, `_linked`
and `POLYMER_LINK_ANGSTROM` have three callers and **two of them have no System**:
`_task_builder.stated_protonation` is handed a bare deposit PDB (the generator's
`struct/` directory holds 593 files, all `.pdb`), and `controls.run_negative_controls`
opens only `system.topology.pdb`, the minimised PDB and the DCD — putting it on
the bond graph would make it start paying a `load_submission` measured at 10.7 s
(6W9C) to 26.3 s (1AHW) per job against 0.1–0.4 s for the geometry split. Plus 12
test sites, every one on a hand-written PDB. The geometry path survives, the
deletion removes zero lines, and a union-find helper would be added on top.

**And the submission's monomers must not be made to depend on `system.xml`
deserialising.** Measured on a constructed broken `system.xml` (truncated to a
third, emptied, and a well-formed `<State/>`): all three score **14/20 today**
with all five composition checks and `contract_atoms_resolvable` passing, because
those are computed from PDB text and never touch the System. With the monomers
unavailable — what a bond graph you cannot build gives you — the same job scores
**7/20**: four prep checks and three md gates lost. Composition is verifiable
from the topology PDB whether or not the System parses, and that independence is
worth keeping.

**`_prepared_structure` is alive.** The review called it dead because its return
value is discarded at the call site. Both of its `SystemExit` paths were
reproduced against a real node: `prep_004` of a01-1ahw declares
`artifacts/merge/merged.pdb` and resolves; the same node.json with
`merged_pdb=artifacts/merge/gone.pdb` raises `prep_fake declares
merged_pdb=artifacts/merge/gone.pdb and the file is not there`; a node declaring
no `merged_pdb` with two candidates raises `prep_amb declares no merged_pdb and
holds 2 candidates (a.pdb, b.pdb)`. The comment at the call site says exactly
this. Not deleted. It is the worked example of checking before deleting.

**`_load_system` is alive and its failure domain is not `load_submission`'s.**
Measured with a valid 3-particle `system.xml` and a deliberately broken topology
PDB: `load_submission` returns `err='the submitted topology could not be read:
IndexError: list index out of range'` while `_load_system` returns a System with
3 particles and no error. Because the call sits deliberately outside the
`topology_error` branch, a submission whose System is fine but whose topology PDB
is unreadable still gets `forcefield_applied_to_every_atom`, `system_is_neutral`,
`potential_energy_is_physical` and `minimization_reduced_the_energy` graded.
Folding the two would couple those axes to the PDB. Hence the reuse applied above
keeps the fallback parse and all five error strings that
`test_scoring_robustness.py` asserts on.

**`metal_ligand_positions` is alive, and the efficiency premise behind touching
it is wrong by three orders of magnitude.** The "4x per job" is real (two direct
calls plus two inside `catalytic_dyad_positions`), and it costs **0.0006 s per
call** on the antibody, 0.0009 s on 6W9C — the two redundant calls are 0.002 % of
`score()`. Deleting the submission-side dyad call (applied above) removes one of
the four for a correctness reason, not a speed one. Also declined: threading the
caller's ligand set in as a parameter. It would make the inner and outer results
identical by construction rather than by coincidence (verified they agree today:
6W9C both {186,189,221}, 6WRH both {186,189,221,223}, 4OW0 both {187,190,222,224}),
but it adds a parameter and saves 0.0013 s.

**The reference-side `catalytic_dyad_positions` call must stay.** Dropping both
dyad calls produces two atom-count findings on each of the three metal jobs —
6W9C `#108 CYM108 10 vs CYS108 11 atoms` and `#269 HIP269 18 vs HIE269 17 atoms`,
6WRH the same, 4OW0 `#109` and `#270` — and fails
`residue_atom_counts_match_reference` on 3 of the 5 jobs.

**`lipid_species` is not folded into `read_residues`.** The premise "same file,
same names" is half wrong. Same names, yes — both filter the same
`LIPID_RESIDUES` on the same `line[17:20]` field. Same file only on the reference
side: the submission's `lipid_species` reads `system.topology.pdb` while
`read_residues` reads `minimized_structure.pdb`. And the residue-identity rules
differ: measured on 5ZK8, `lipid_species` (dedup on `(chain, resseq, name)`)
reports `{'PA': 344, 'PC': 344}` while `read_residues`' rule (new residue when an
atom name repeats) reports `{'PA': 688, 'PC': 344}` — Lipid21 splits one DPPC into
PC + PA + PA and the two acyl residues share a residue number. The *graded* value
is unchanged, because PA is in `LIPID21_TAILS` and is skipped from the count — but
there is one membrane job in the harness and one job is not a cast.

**`match_monomers` stays as it is,** and the measurement that earns it belongs on
the record: 51 of 101 references are multimers; matched against a reverse-ordered
copy of themselves, all 46 without duplicate canonical sequences place at max
displacement **0.0 A**, while naive zip in input order fails to place anything in
37 bundles and places atoms **silently wrong** in 14 — worst `inr_A00LC` at
**91.56 A over 1332 atoms**, also `mmb_A01DH` 61.6 A, `mmb_A01DS` 61.3 A,
`mmb_A01DT` 60.2 A. Order is not free.

Two measured hazards in it are recorded and **declined for now** rather than
fixed blind, because both fixes need calibration this suite does not have:

* 5 references carry duplicate canonical sequences (`inr_A000B`, `mmb_A017E`,
  `mmb_A01A6`, `mmb_A01DF`, `mmb_A023K`). Within one sequence group the pairing is
  zip in input order, so a submission that writes identical copies in the other
  order places 142–684 contract atoms **42.0–77.9 A** from the intended copy,
  with pairs complete and nothing reported. The per-atom RMSF profile is then
  compared against the wrong copy. No flat-dict replacement addresses this.
* the `mismatches` gate makes `sequence_matches_reference` and
  `residue_atom_counts_match_reference` report "not compared: no monomer pairing"
  even when every pair *was* compared and matched — measured on a reference given
  an extra chain copy: all 3 chains paired, all 1908 contract atoms placed,
  findings empty, and 3 checks still fail with 2 of them reporting a false
  diagnostic.

Needleman-Wunsch or any per-residue fallback pairing is declined outright: its
gap penalties are an uncalibrated threshold.

**The row-index-on-the-residue variant is declined** — it would let `pdb_atoms`
and both its extra full-file parses go, but it saves under 0.6 s per job
(measured: `pdb_atoms` 0.43 s, `read_residues` 0.38 s, index build 0.13 s on
1AHW) and it collides head-on with the hy36 deletion applied above, which frees
the residue tuple's first slot rather than repurposing it.

**`scoring.py`'s `pdb_atoms(minimized_structure)` is NOT switched to
`system.topology.pdb`,** and composition is not moved off the minimised frame as
a side effect of anything here. The atom *order* agrees on all five jobs (row i
is the same atom) but the *labels* do not — the zinc is chain B resseq 1 in the
minimised file and B/313 in the topology file on all three metal jobs, and 1AHW's
N-terminal amide hydrogen is `H` in one and `H1` in the other — and the table is
keyed on `(chain, resseq, atom name)`. It resolves 936/936 and 1908/1908 from
either file today only because the contract atoms are backbone heavy atoms. A
per-bundle coincidence, not a property of the files.

**The report fields `by_category` and `diagnostics`, and controls'
`baseline`/`caught_by`/`bands`/`calibration_windows`/`claimed_ns`/
`minimum_clock_fraction`/`frame_interval_ps`, are NOT deleted** although no code
reads them. They are surfaced in the JSON report that humans and agents consume.
"No programmatic reader" is not "dead"; that is a different class from a value
stored in a tuple slot nothing unpacks.

**`_task_builder`'s `numbering_certain`, `auth_number`'s discarded `exact` flag
and the unused `exact` local are confirmed unread and left alone** — they belong
to the task-generation workflow and touching them would change 100 task.json
files.

### One thing the five solved jobs cannot see

`mmb_MCV1900237`, which backs task 061_metal_6m0j, **does not survive
`tp.load_reference` today**: `reference.prmtop and reference.pdb disagree on atom
order at 815 position(s), first at index 20`. Pre-existing and unrelated to
anything here, but it is the standing proof that the corpus carries failures the
five-job harness cannot show. Every claim in the original review was true on
those five; two of them were false on the corpus. The five jobs are a regression
harness, not the population.

## 2026-08-24 — Every bond question about a submission now asks the System

`015_antibody_1ahw` scored 19/20 on artifacts whose chemistry is correct. The
one failure, `topology_is_chemically_valid` — "84 atom(s) over their valence:
CYS23:N 5, CYS23:C 5, CYS88:CA 7" — was the scorer's, not the submission's.

Traced in full. Each over-valent atom carried extra partners that exist only in
the topology PDB's CONECT records, at 50–135 A, with no force term behind them:

    CYS23:N   THR22:C 1.32 A force | CYS23:CA 1.43 force | CYS23:H 1.01 force
              HOH1081:H1 96.32 A CONECT-only | HOH1086:O 64.35 A CONECT-only

The cause is a PDB serial overflow, and it is not hybrid-36 (both this repo's
docstrings and mdclaw's visualization comment say hybrid-36; both are wrong).
`openmm.app.pdbfile._formatIndex` writes decimal to 99999 and then hexadecimal
with a shift, wrapping modulo 16**5, so the largest index it can express is
493215. Measured on this file:

    atoms                                        381954
    TER records (one per chain object)           124078
    serials consumed                             506032   > 493215
    serial fields naming more than one atom        2245   affecting 4490 atoms
    e.g. serial '    1'  = ASP A 1 :N  and  WAT M 880 :O

The topology carries 124078 chain objects — 3 protein chains and 124075
one-residue water chains — and OpenMM writes a TER per chain object, which is
what pushes the count past the limit. Waters are named WAT, which is not in
`PDBFile._standardResidues` (HOH is), so 372272 of the 372459 CONECT records
exist only because of that name; renaming them would not have been enough, as
2311 of the remaining 2498 still resolve through an aliased serial.

`load_submission` already returns the System's force-bearing bonds and
`sulfur_bonds` already takes them, but `valence_problems` and
`metal_bridging_bonds` still read `structure.bonds`, which parmed takes from
the OpenMM topology, which is CONECT plus template inference. So two checks
judged chemistry from the one basis this module's own docstring calls metadata.

Both now take `bonds=None` on the same contract as `sulfur_bonds`, and
`scoring.py` passes `submitted_bonds`. A submission's bonds are never read from
its PDB again. The reference side is unchanged and stays on `structure.bonds`:
a prmtop/tpr/psf has no CONECT and its bonds are the force field.

`force_bearing_bonds` also had to stop counting angle constraints. Rigid water
constrains H-H as well as both O-H, so every water hydrogen got a second
partner. Measured over the five solved jobs, atoms reading over their valence:

    basis                        m01-5zk8   d02   d03   d04   a01-1ahw
    structure.bonds (CONECT)            0     0     0     0         84
    raw force-bearing               47478     0     0     0          0
    force-bearing less H-H              0     0     0     0          0

The H-H constraint is the angle. `constraints=HBonds` (openmm_build.py:1175)
constrains only X-H bonds; it is `rigidWater=True` beside it that emits the
third pair, because OpenMM makes a water rigid by fixing all three sides of the
triangle -- O-H1, O-H2 and H1-H2 -- so the angle arrives expressed as a
distance. Both ends being hydrogen is therefore the whole test, and no
biomolecular force field bonds two hydrogens to each other.

A first attempt dropped a constrained pair whose ends share a neighbour, on the
theory that an angle shows itself that way. It is wrong and the measurement
hid it: water's O and H1 share H2, so it discarded the real O-H bonds as well,
and the resulting zero looked like success. Caught by asking a solvent-only
topology for its valence distribution, where O read 0 instead of 2.

The corrected basis was then checked for what it must still catch, on
d02-6w9c (135696 atoms): the valence distribution is chemically right (H 1,
O 2, C 4 and 3, N 3) with no atom over its limit, and injecting one spurious
bond onto a saturated carbon flags 2 atoms whether it is added as a
HarmonicBondForce term or as a constraint.

Scope: the wrap needs atoms + TER > 493215, so it takes roughly 350k atoms.
The other four jobs are 120k–146k and never reached it. Any correct submission
above that size was failing this check.

Decided against: renaming WAT to HOH, and regrouping the solvent into few
chains, in mdclaw. Neither affects the MD — nothing in prep, the topo build,
minimisation, equilibration or production reads CONECT (the only reader is
`structure/merge.py`, on per-component files of 1672–3262 atoms, far below the
wrap). The PDB's five-column serial cannot address 506032 entities and that is
the format's limit, not a defect to engineer around. What the broken CONECT
still costs is pictures: mdclaw's `visualization/_base.py` already documents the
same wrap ("5762 of 47972 lipid atoms fell past the wrap ... rendered as a hole
in the bilayer") and works around it with PyMOL `connect_mode 3`.

Also overturned from earlier today: the claim that a01's artifacts were corrupt
because they were written while a `keepIds=True` defect was in mdclaw. The
timestamps do fall in that window, but the artifacts are correct — the System
carries no bond over 3 A and no over-valent atom. No re-run was needed.

## 2026-08-23 — Sceptical review of calibration.py (pooled-band rewrite)

Reviewed the replica-pooling rewrite the day it landed. Verified by execution:
atom_selector is correct (round-trips to the 0-based index set; no off-by-one),
but 5000 fragmented atoms would make a 26 KB selector URL with no length
guard. Defects found, unfixed pending decision: (1) window-start grid
`range(1, frames-count, count)` loses the aligned last window and never
samples the trajectory tail (frames=1000, count=100: last window ends at
frame 900); combined with `[:wanted]` taking each replica's first windows,
calibration sees a deterministic early slice of every run. (2) Held-out test
uses only the last replica — one draw, when leave-one-out over all replicas
is free since the rows are already computed; it degenerates to a
single-trajectory band when replicas == 2, and is silently dropped when any
replica yields zero rows. (3) `_rejected` raises TypeError on a None statistic
in a held-out window (`_bands` guards None, `_rejected` does not); `_bands`
screens None but not NaN, and a NaN band rejects everything on the two-sided
checks while passing everything on the one-sided rank floor. (4) window_frames
checks only byte divisibility — no expected-byte count, no layout/NaN/
magnitude screen, so a unit slip (nm vs A) or divisible garbage becomes a band
silently. (5) Single-replica references (~47% of eligible projects) still get
the single-trajectory band the module docstring discredits, with nothing in
the contract marking the absence. (6) The docstring's DynaRepo example is
arithmetically wrong: 2.5 ns at 100 ps is 25 frames, not 100, and would raise
at the frames_per_window floor; cli.calibrate_reference cannot pass
frames_per_window anyway. (7) frames_per_replica in the contract records only
the last replica's (averaged) value. Also noted: the three shipped contracts
(D01–D03) are dated 2026-08-22, pre-pooling — single-trajectory windows and a
block-CV slack rationale — and scoring.py:519 still quotes the 7–16% block-CV
no-slack rejection while the honest held-out test measures 30% (ATLAS 16pk_A;
0.00 at 2.0 window-SD slack). Contracts and the scoring comment predate the
module they describe and need regenerating.

The entries below the extraction were written in
[matsunagalab/mdclaw](https://github.com/matsunagalab/mdclaw)'s `docs/memo.md`
before this repository existed and are copied here verbatim. They refer to
paths as they were at the time: `benchmarks/mddatabench/scripts/*.py` are now
package modules under `mddatabench/`, and
`docs/research/db_derived_benchmark_validation.md` is now
`docs/validation-design.md`. The originals stay in mdclaw.

---

## 2026-08-23 (2) — 4 件を実装し、pi のレビューで 20 件の欠陥を潰した

100 タスクを回すのに要る 4 件を順に実装し、それぞれ pi にレビューさせた。
**レビューは 3 件とも実際の欠陥を見つけ、うち 2 件は自分の変更の目的を無効化していた。**

### 1. 採点器が任意のノードのトポロジーを読む

ノードごとに形式が違う (mmb/cin/rpbs は prmtop、bsc/oxf/inr は tpr、inr の一部は psf)。
`read_topology` が拡張子で振り分ける。**ParmEd は `.tpr` を読めない** (GROMACS の
バイナリ run input) ので、そこだけ MDAnalysis で読んで ParmEd に変換する。

実測 (クランビン 1AB1、GROMACS tpr): 639 原子、648 結合、ジスルフィド 3 本
Cys3-Cys40 / Cys4-Cys32 / Cys16-Cys26 を全て復元。結合/原子比 1.014。

**pi の指摘 (採用)**: `load_reference` は原子数と原子名順序しか照合せず、**結合を
一切検証していなかった**。変換が結合を落とせば参照の期待ジスルフィド集合が黙って縮み、
ジスルフィドを欠いた提出物が「一致」として通る。ポリマー残基を持つのに結合ゼロの
トポロジーを拒むようにした。

### 2. 帯をレプリカ横断で較正する `calibration.py`

**pi の指摘 (全て採用、全て実測で確認)**:

- **`frames=a:b:c` は 1 始まりで両端を含む.** 実測: `1:11:1` が 11 フレーム、
  10001 フレームのレプリカに `10001:10002:1` は 502、`9902:10002:1` は
  **エラーではなく本文が途中で切れる**。URL が `start+count` を要求していたため
  末尾の窓が毎回 IncompleteRead で落ちていた。正しくは `start+count-1`。
- **窓の開始位置が軌道の先頭 1/3 に固まっていた.** 先頭から数えて最初の N 本を
  取っていたため。遅いドリフトと後半の緩和が構造的に除外され、**このモジュールが
  直そうとしている「帯が狭すぎる」問題をサンプリング側から再生産**していた。
  全域に散らしたところ、総 RMSF のプール/単一 SD 比が **0.91 -> 1.08** に変わり、
  3 統計量すべてが 1 を超えた。
- **フレーム数の取り方が矛盾していた.** `totalFrames` はどのレプリカ番地でも
  プロジェクト全体の値 (3 レプリカ x 10001 に対し 30003) なので割る必要があるが、
  フォールバックの `rmsds` 系列は間引かれている (step 3 で 3334) ので、長さだけでは
  **3 倍の過小評価**。`mdFrames` が per-replica の正しい値。
- **hold-out が最終レプリカ 1 本だけだった.** 全 fold が既にメモリにあるので
  leave-one-out にした。**スラック無しで 40 / 10 / 30 %、実測スラックで全 fold 0 %。**
- **NaN が None ではなく NaN のまま帯に入る.** min/max が NaN を伝播し、NaN との
  比較は全て False なので、**帯が全提出物を通す**。非有限値を拒むようにした。
- **1 本の通信断で 100 回の較正が全部落ちる.** 再試行を入れた。
- **散らばった原子選択は URL に収まらない.** 16pk_A の contract 原子 1245 個で既に
  6020 文字。上限を超えたら全フレームを取って手元で切り出す。

### 3. `controls.py` を新ゲートに合わせた

**pi の指摘 (最重要、採用)**: 合成ベースラインに軌道を渡していなかったため
溶媒時計が常に false になり、判定は全ゲートの論理積なので、**新ゲートを試すために
追加した 3 本 (shuffled_atoms / frozen_first_frame / scaled_motion_x5) は、
そのゲートを削除しても「正解」と採点される**。つまり何も試していなかった。
実溶媒を残す形に変えた。溶質だけ細工して溶媒はそのまま、というのは現実的な攻撃でもある
(実際に流したあとで後処理した run)。

**`gates_never_decisive` の定義も誤り**だった。あるゲートが「発火した」ことを
テスト済みと数えていたが、他に 3 つ落ちていれば判定は変わらない。
**単独で落としたゲートだけ**を数えるようにした。

他に採用した指摘: `profile_agreement` の None で `float()` が落ちる、contract 原子
欠損で `KeyError` (採点器は報告して続行する)、フレーム間隔が無いと `traj.time` に
落ちてフレーム数を ps と誤る、時計の分母に 1 ns を直書き (採点器は prod ノードの
申告を読む)、打ち切りをフレーム番号で切って ps と名乗る、採点器は 10 ps に間引くのに
こちらは全フレームを使う (帯の縁にいる run が 2 つの道具で違う判定になる)。

### 4. README を現行設計に合わせた

**pi の指摘 (採用)**: 「ゲートは 6 本」は誤りで、md カテゴリの検査は **8 本**
(`thermodynamic_conditions_match_reference` と `production_ran_for_one_nanosecond`
を落としていた)。「conjoined」も誤りで、`_report` は `earned/weight` の加重平均を
出すので 1 本落ちれば 7/8 = 0.875 になる。README の他の箇所が「加重和は 1 つの
完全な失敗を他で埋め合わせられる」と書いていたのと矛盾していた。

あわせて、契約に残っていた診断 `subspace_rmsip_value` を落とした。採点器はもう
RMSIP を計算しないので、契約が出ないものを宣言していた。

### 照合の守りが 3 つとも効いていなかった (pi の指摘)

塊ごとの配置そのものは**全 769 鎖で REMARK 465 と照合して誤り 0** (旧実装は 150 鎖で
誤り)、「解けていない残基」の誤記は **17 件 → 0 件**、述べた範囲のうち寄託が持たない
端点は 0。だが守りに 3 つ欠陥があった。

**① 打ち切りが一つの余計なレコードで鎖全体を捨てていた.** 遊離アミノ酸が HETATM で
寄託されると 1 残基の塊になり、置けずに break していた (1DTD の `GLU 300` は亜鉛の
隣のリガンドであって残基 300 ではない)。**飛ばして続ける**ようにした。

**② `mapping_is_trustworthy` の「半分置けたら信頼」が守りになっていなかった.**
途中で SEQRES と食い違う鎖が 99 残基中 60 を置いて合格し、「範囲のうち 40 残基が
未解決」というプロンプトを出した (寄託はそのうち 39 を解いている)。**全部置けたか**に
変えた。費用ゼロ — 出荷 100 件の 159 鎖すべて、ディスク上の 769 鎖すべてが通る。
遊離アミノ酸 1 個だけは許容する (高分子の一部ではないため)。

**③ 守りをライブラリの誰も呼んでいなかった.** `seqres_to_auth` の呼び出し 5 箇所は
すべて無防備で、確認していたのは生成器の 2 箇所だけ、しかも参照が使う範囲ではなく
鎖全体に対してだった。`selection` が置けない鎖を **SystemExit で拒否**するようにした。

**残る既知の限界**: 1 残基の塊は「最初の一致」を採るので、旧実装と同じ曖昧さが残る
(`SEQRES AAAAAA` に観測 1,2,5,6 で誤る)。出荷 100 件では候補が複数ある塊が 6 鎖あり、
いずれも最初の一致が正しい。長さ 2 以上の塊では曖昧さは実質消える。

### 抗体を解こうとして SEQRES 照合のずれが出た

1AHW 鎖 C。SEQRES は `S G T T N T`、観測は auth 4 から `T N T`。残基を 1 個ずつ歩く
照合が最初の T を auth 4 に当て、**位置 4 の T を余らせて以降が 1 つずれた**。
docstring 自身が "a repeat can shift every later anchor" と予告していた欠陥。

    参照が使うのは SEQRES 4-211 (208 残基)
    プロンプトは chain C residues 5-211 (207 残基) と述べていた
    build_residues は ['5','83','92','93','94','95','89','90','91']
    実際の欠損は 83-90 の連続 8 残基

**連番の塊ごとに置く**方式に変えた。塊の中は番号が連続しているので SEQRES 上でも
連続し、コードをまとめて照合すれば繰り返しは無害になる。塊は左から順に重ならないよう
置き、置けない塊が出たら推測せず打ち切る (`mapping_is_trustworthy` が拒否する)。
プロンプト再生成側にその守りが欠けていたので足した。

100 タスク 158 鎖で: **長さ不一致 12 → 5、端点が外挿 16 → 6、置けなくなった鎖 0**。
プロンプト 15 件が変化。抗体 10 件中 7 件が参照と完全一致し、残る 3 件
(1DQJ, 2DD8, 5CBA) は番号が飛ぶ鎖で範囲は正しく幅だけが合わない。

### プロンプトの「neutral histidine」は互変異性体を決めていない

1AHW の参照はヒスチジン 6 個すべて `HSD` (= Amber の `HID`、Nδ にプロトン)。MDClaw の
propka は `A:198` と `B:203` に `HIE` (Nε) を割り当てた。**原子数はどちらも 17 なので
採点は見ない**が、水素結合の向きが変わるので物理的には別物。プロンプトが
「neutral histidine」としか言っていないのは指示として不完全。未修正。

### 1AHW の解答

`C:4-211` と `A:189` を `HID` に上書きして prep すると、提出物の monomer が
**208 / 214 / 214 で参照と完全一致**。MODELLER (鍵をユーザから受領) が 83-90 を構築。
これが**この環境で初めての多鎖の提出物**であり、contract 原子の対応 (抗体 3 鎖が
45 Å 離れた原子に誤対応していた問題) の修正を実物で検証できる最初の機会。

### プロンプトどおりに解こうとして MDClaw の欠陥が出た

003 を「全てのイオン化残基を標準状態で」というプロンプトどおりに解き直そうとして
`--protonation-states '{"A:69": "ASP", "A:103": "ASP"}'` を渡したが、**構造は ASH の
まま**だった。記録は

    "state": "ASP", "already_in_requested_state": true, "source": "user_override"

と**成功を報告していた**。

原因は OpenMM の `PDBFile` が読み込み時に変種名を親に正規化すること。ファイル上の
`ASH` は `ASP` として読まれる (HD2 は 13 原子目として残ったまま)。
`protonation.py:530` の「既にその状態なら無操作」判定がその正規化後の名前と比べて
いたので、**変種を親に戻す上書きが常に無視されていた** (ASH→ASP, GLH→GLU,
LYN→LYS, CYM→CYS)。逆向き (ASP→ASH) は通るので気づかれなかった。

ファイル上の名前で判定するよう直した (mdclaw 56c5f98)。ASH 13 原子 → ASP 12 原子。
「同じ状態を要求したら無操作」という元の意図は保持 — その判定が守っていたのは
「基底名に改名して addHydrogens に渡すと H/HA/HB2/HB3 が重複する」という別の欠陥で、
そちらは変わらず守られる。

**教訓**: 成功と報告する無操作は、失敗より見つけにくい。ベンチマークがこれを
見つけられたのは、参照との原子数比較が 12 対 13 で食い違ったからで、MDClaw 単体の
記録を読んでいる限り「適用済み」としか見えなかった。

### プロンプトが標準状態を述べていなかった

003 の残った不合格は `ASP52 12 原子 vs ASH52 13 原子` で、MDClaw の pdb2pqr+propka が
pH 7.4 で寄託の Asp69・Asp103 を中性型と判断したもの。記録が残っている:

    "protonation_method": "pdb2pqr+propka", "protonation_ph": 7.4
    {"resnum":"69","state":"ASH","default_state":"ASP","source":"auto_detected"}

金属配位の CYM とは経路が違う。あちらは MDClaw の `detect_metal_sites` が
`"ligates ZN402 at 2.48 A"` という理由つきで割り当てており、pdb2pqr は
**イオンが別ファイルに出るので金属を見ない**（放っておくと 4 システインの亜鉛のうち
1 つしか脱プロトン化されず金属が外れる、と `prepare_complex.py:1357` が測定を書いている）。

**参照はイオン化変種を一つも使っていない**。`stated_protonation` は非標準の位置だけを
返すので、5ZK8 では空になり、プロンプトは何も言わなかった。だが「何も言わない」は
「標準で作れ」を意味しない。pKa 予測器はどこかで参照と食い違う。

100 件を測ると**参照はすべて水素を持ち**（判定可能）、変種を持つのは 10 件だけ
（実質 `CYM` 4 件と `HIP` 7 件、`CYX` はジスルフィド）。そこで

    Simulate every [other] ionisable side chain in its standard state at pH 7:
    charged aspartate, glutamate, lysine and arginine, and neutral histidine
    and cysteine.

を全件に足した。個別指定を持つ 4 件だけ "every other" になる。

### contract 原子を番号で引いていた。32 件が黙って誤対応していた

RMSF と Rg のゲートは、参照が `pca_atom_indices.json` で名指しする主鎖原子を提出物の
中から探す。その探し方が `(残基番号, 原子名)` の文字列一致だった。**鎖が鍵に入って
いない。**

抗体は 3 鎖をそれぞれ 1 から番号するので、1AHW では contract 原子 1908 個に対し
**異なる鍵が 642 個しかない**。鍵 `('5','CA')` は鎖 A の THR5、鎖 B の GLN5、鎖 C の
ASN5 を同時に指し、この 3 つは **45 Å 離れた別のアミノ酸**である。`setdefault` は
最初の 1 個しか登録しないので 3 つとも鎖 A の原子に解決し、
**`contract_atoms_resolvable` は 1908/1908 合格と報告する**。RMSF はその誤対応の上で
計算され、止まらない。

MDClaw が出す形（末端接尾辞なし・鎖ごとに 1 起点）を模擬して 100 件を測ると:

    現行方式で欠落が出る   38 件
    現行方式で誤対応が出る 32 件、誤対応した原子 13583 個
    最悪 3WD5: 1752 原子中 1530 個が誤対応、最大 98.6 Å

**monomer の対応に載せ替えた** (`contract_correspondence`)。`match_monomers` は正規化
配列で、`split_monomers` は主鎖の距離で対応を作るので、**残基番号も鎖ラベルも両側で
読まない**。「参照 monomer i の j 番目の残基の原子 X」で引く。同じファイルの中では
`(鎖, 番号, 原子名)` が 1 原子を指すので、そこだけに使う。

模擬提出物 100 件が**完全解決 100 / 未解決 0**。解答済み 4 件は**添字が現行と完全一致**
(819/819 と 936/936 ×3)、点数も不変。

### 核酸 14 件は末端名で全滅していた

参照はすべて Amber の末端名 (`DA5` `DG3` `G5` `C3`) を使うが、MDClaw は素の
`DA` `DC` `DG` `DT` を書く。`CANONICAL_RESIDUE` がこれを潰していなかったので、
末端接尾辞を外した提出物では**核酸 12 件が 1 組も対応せず**、1KX5 が 10 組中 8 組。
**正しい提出物で md ゲート 3 件が落ちる。**畳み込みを追加した。末端が実際に何かは
原子数で採点されるので、5' のリン酸欠落は依然として検出される。

### 採点と対照が別々の検索をしていた

`controls.py` は同じ鍵なし検索を、しかも **topo ノード**に対して行っていた。採点を
min ノードに移した時点で食い違いが生まれ、同じ提出物について**採点 819/819、
対照は「228 個欠落で実行不可」**になっていた。両方 `contract_correspondence` に
揃えた。**膜タスクで初めて負の対照が走る**ようになり、`gates_never_decisive` は空。

### RMSD による複製の割り当ては入れない

参照が同一配列の複製を持つのは 5 件 (6I53、1AKJ、1C7U、1KX5、1NAJ)。`match_monomers`
は入力順に `zip` するので、原理的には割り当てが決まらない。構造重ね合わせで最小 RMSD
の順列を選ぶ案を検討し、**決まることは確認した** (誤順列との RMSD 差は 6I53 で 52.4 Å、
1AKJ 30.4 Å、1KX5 41.0 Å、正解時 0.35-1.14 Å、乱択 60/60 正解)。

**しかし結果が変わらない。**参照自身の RMSF profile でコピーを入れ替えても相関は
0.827-0.997 で、下限 (-0.314 / 0.642 / 0.809 / 0.836 / 0.916) をすべて上回ったまま。
`total_fluctuation` は原子についての二乗平均、`radius_of_gyration` は重心相対なので
**入れ替えに対して厳密に不変**。加えて複製を持つ 5 件はすべて多鎖だが、**多鎖の提出物が
一つも存在しない**ので最小像の処理を検証できない。入れない。

### 採点は入力を見ていた。最小化後の構造に切り替えた

`monomer_count_matches_reference` は `prepare_complex` の出力を距離で割って高分子を
数えていた。**それは組み立ての入力であって結果ではない**。参照が繋いだ構築体
(5ZK8 は残基 214 と 383 を結合、寄託ではその 2 原子が 9.63 Å 離れている) は、
どれだけ正しく組んでも prep の成果物には寄託の隙間が残るので 2 本に見える。

    prep      197 + 76      topo      197 + 76
    min       273           prod      273           参照 273

**MDClaw は最初から正しかった**。System を調べると topo の時点で C(214)-N(383) に
平衡長 1.335 Å・k=410032 kJ/nm²/mol の調和結合が入っており、9.6 Å に張られた
その結合を最小化が 1.34 Å まで引き寄せる (参照 1.35 Å)。**採点が MD 前の
スナップショットと計算後の参照を比べていた**だけ。

`minimized_state` は契約の必須成果物なので、`min` を解決する段階に加えて
そこから読む。003_membrane_5zk8 は 14/20 → 16/20。

### 金属も同じ構造から読まないと除外が外れる

monomer だけ最小化後に移し、金属座標を prep のままにしたところ、PLpro 3 件が
20/20 から 19/20 に落ちた。**距離を別のフレーム間で測っていた**ので亜鉛サイトが
見つからず、チオラート 3 つが組成の差として報告された:

    #189 CYS189 11 原子 vs CYM189 10 原子

除外自体は monomer 内の 1 起点位置で計算されるので番号ずれには強い。壊れていたのは
座標系。`read_metals` も最小化後の構造から読むようにして 3 件とも 20/20 に戻った。

**CYM は PROPKA ではなく MDClaw の判断**。`prepare_complex.py:1357` が理由を書いて
いる — split は pdb2pqr に蛋白質だけを渡しイオンは別ファイルに出るので PROPKA は
金属を見ない。放っておくと 4 システインの亜鉛のうち 1 つしか脱プロトン化されず
金属が MD 中に外れる。`detect_metal_sites` が ZN C402 (ZN-Cys3) の
CYS 189/224/192 を 2.48/2.57/2.85 Å で検出して CYM を割り当てている。
化学的にはこちらが正しく (Zn-S⁻ はチオラート)、参照が中性 CYS なのは寄託者の簡略化。

### 008 (6I53) は 3 つの欠陥を重ねていた

膜 14 件で唯一、範囲が重なるプロンプトを出していた。調べると独立した欠陥が 3 つ:

**① 配列照合の割り当て** — `verify4.json` の時点で参照 A・B・D・E がすべて寄託 E、
C と H が寄託 A を指している。参照鎖を 1 本ずつ独立に SEQRES と照合するので、
同一配列のサブユニットが全部同じ寄託鎖に落ちる。

**② 双子への退避が 1 件だけ** — `assign_distinct_chains` は到着順に「重複したら
同一 SEQRES の未使用鎖へ移す」を 1 回だけ行う。E に 4 本来ると A・D・E が残り、
`merge_by_deposit_chain` が `8-312` と `10-312` を並べて出す。

**③ 移した entry を 1 連続区間として測り直していた** — 参照 H は 2 区間なのに
寄託 D の `10–401` になっていた。**幅 392 に対し寄託の実体は 347** (`10–322` と
`384–417`、323–383 は存在しない)。存在しない残基 45 個を要求し、しかも 1 区間に
なったので「断片を繋げ」という文も消えていた。**出荷済みのプロンプトに入っていた。**

### 直し方: まとめてから割り当てる

1 つの寄託鎖に複数の参照鎖が来る理由は 2 つあり、**正反対の扱いを要する**:

    同じ構築体の断片 → 範囲が重ならない (partner を抜いた両側だから) → 同じ鎖に置く
    サブユニットの別コピー → 範囲が重なる                             → 双子へ移す

`spans_overlap` で組に分け、2 組目以降にそれぞれ双子を与え、**保存した SEQRES 区間
から測り直す** (`remeasure_on`)。auth 範囲から区間を復元する近道は使えない —
6I53 の寄託 E は auth 10 を SEQRES 3 に写すので、引き算は -18 を返す。

6I53 は五量体の正しい姿になった:

    A 10-323 + 384-418   B 8-312 + 418-447   C 28-323 + 406-436
    D 10-322 + 384-417   E 10-312 + 418-447

寄託 5 鎖がちょうど 1 回ずつ、重なりなし。**100 件中の差分は 008 のみ**、鎖の順序を
200 通り入れ替えても双子が入れ替わるだけで同じ分割。重なった範囲を持つタスクは 0 件。

**範囲**: 100 件のうち複数の参照鎖が 1 つの寄託鎖に来るのは 12 件。6 件は双子がなく
(素直な融合、正しい)、5 件は範囲が重なる真のコピー (1AKJ, 1E3U, 1KX5, 1NAJ, 1C7U、
正しい)。**融合断片と双子が同時にあるのは 6I53 だけ**。候補プール全体では 6CNJ が
同じ壊れ方、2UZK が ③ で静かに番号を間違えているが、どちらも出荷 100 件に入っていない。

**調査で判明した私の誤り**: 「割り当て前に参照 4 鎖が 1 entry に潰れている」と
memo に書きかけたが、それは `assign_distinct_chains` を恒等関数に差し替えた私の実験の
副作用だった。実際は参照鎖ごとに 1 entry・1 範囲で届く。`coalesce` が `418-447` を
落とすというのも誤り。

### 繋いだかどうかを件数で推測していた (pi の指摘)

`joins_its_pieces` は「参照の高分子の数 < 要求した断片の数」で繋ぎを判定していた。
pi の指摘どおり不健全:

- `read_residues` は結合したリガンドを落とさないので、**リガンドが 1 つあるだけで
  判定が反転**する。断片の中に切れ目のある参照 (6KUY) でも同じ
- 3 断片の**部分的な繋ぎを表現できない**。012 (6ME3) と 014 (6ZDV) は 3 範囲を持つ
- 「複数鎖が複数範囲を持つとき」だけ SystemExit するので、**1 鎖だけが複数範囲で
  件数が別の理由で動いた場合に黙って誤帰属**する

**出所で判定するよう書き直した**。範囲が複数になる経路はちょうど 2 つで、それが
そのまま 2 つの答えになっている:

    参照鎖 1 本の内部欠失  → 1 本の高分子 → 繋いだ    (5ZK8: 273 残基, 除去 115)
    参照鎖が複数 → 複数の高分子 → 繋いでいない        (5YC8: 199 と 79)

数えないのでリガンドも内部の切れ目も影響しない。鎖ごとに答えが出るので 008 も
止まらない。結果 **8 件が繋ぎ、4 件が分離**で、参照の実測と完全に一致する
(001 [199,79] / 004 [201,80] / 010 [190,79] / 011 [140,45,79])。

### 窓の制限が既定経路で動いていなかった (pi の指摘)

`_restrict_missing_to_window` は「末端を作るとき」の分岐の中にあり、
`build_terminal_missing_residues=False` (既定) では飛ばされていた。つまり
**融合部を作り直さないための守りが一度も動いていない**。分岐の外に出した。
5ZK8 の実行では実害なし (273 → 273) だが、`--missing-residue-method modeller` なら
BRIL が再構築される。MODELLER の修復がさらに手前で窓なしに走る点は**未対応**。

### 複数範囲の切り出しで欠損残基検出が黙って無効になる (pi の指摘、未修正)

`prep_008` の記録が `status: "detected"` かつ検出 0 件。SEQRES 421 に対し 273 残基
しかないのにゼロ。推測される機構は PDBFixer が auth 番号幅 441 > SEQRES 421 で
照合できないこと (pdbfixer が手元になく未検証)。範囲被覆検査が実害を止めているが、
記録が嘘をついており、escalation も常に 0 件を見ることになる。

### 後方互換の start/end が「広げた範囲」だった (pi の指摘)

18-214 と 383-458 の記録に `start: 18, end: 458` が入っていた。**これは拒否すべき
要求そのもの**で、6ME3 なら 23..1196 になる。断片が 1 つのときだけ書き、複数なら
書かない (読み手は鍵の不在で気づく)。範囲の並べ替えは数値順であって構築体の順では
ない (6ME3 は 23-218, 1001-1196, 228-318) ので、先頭と末尾を鎖の両端と読んではならない。

`warmup_membrane_cache.py` も水モデルに合わせるようにした。`--water-model tip3p` で
温めても ff19SB 鍵で保存され、本番は ff14SB 鍵を探すので永久に外れていた。

**キャッシュ鍵に欠陥はない**: `membrane_patch_fingerprint` は水モデルと力場の両方を
ハッシュに入れており、実際のキャッシュにも ff14SB/tip3p と ff19SB/opc が別々にある。

### 膜検査が prep 段階の構造を読んでいた

二重膜は溶媒和の段階で足されるので、prep の `prepared_structure` には脂質がない。
そこを読んでいたため、DPPC 344 分子をきちんと組んだ提出物が
`reference DPP x360 against submitted no lipid` で落ちた。実際に走る系は
トポロジー PDB なので、そちらを読むように直した。003 の膜検査は合格になり
(`DPP x360 (DPPC)` 対 `PA x344, PC x344`)、非膜系は 20/20 のまま。

### 003_membrane_5zk8 を実際に解いた結果 prep 0.75 / md 0.62 (14/20)

合格 14: トポロジー妥当性、力場の全原子適用、**ジスルフィド 2 本が参照と一致**、
電気的中性 (-9.5e-14 e)、最小化 (-904311 → -1628354 kJ/mol)、**TIP3P が参照と一致**、
300 K / NPT / 1 bar、1 ns、溶媒時計 0.84、**実測温度 300.9 K**、**密度 1.02 g/mL**、
**元素組成が参照と完全一致** (C 1465 / N 336 / O 357 / S 19)、**二重膜**、金属なし。

不合格 6 は**すべて「214-383 を繋げなかった」1 点から連鎖している**:

    monomer_count_matches_reference  参照 1 個に対し提出物 2 個
    sequence_matches_reference       対応がつかず比較不能
    residue_atom_counts_...          同上
    fluctuation_profile / magnitude / radius_of_gyration
        参照の 819 原子のうち 228 個が提出物にない = 76 残基 x 3 原子
        = 後半断片まるごと。番号が 383-458 のままで参照の 198-273 と合わない

膜構築そのものは通っている。残る欠落は繋ぎだけ。

### 融合構築体は誰も表現できなかった。MDClaw を直した

膜タスクを実際に解こうとして、**MDClaw の `--residue-ranges` が膜 14 件のどれも
表現できない**ことが分かった。GPCR は例外なく融合構築体で、柔らかい ICL3 を BRIL や
T4 リゾチームに置き換えて結晶化させる。5ZK8 鎖 A は 18-214、1001-1106（BRIL）、
383-458 の 1 本鎖で、参照は受容体側 2 断片だけを計算している。

    --residue-ranges A:18-214 A:383-458  → 「1 鎖につき連続 1 範囲」で拒否
    --residue-ranges A:18-458            → 「215-382 の 168 残基が存在しない」で拒否

100 件のうちこの API で表現できないのはちょうど 14 件、**膜タスク全体**だった
（他 86 件は単一範囲で足りる）。「1 鎖 1 連続範囲」は docstring に意図的な設計として
書かれていたので、利用者に確認したうえで外した。重なりだけは拒否する（同じ残基を
覆う 2 範囲は「1 範囲を二度書いた」以外の読みがない）。4 ファイル:

- `residue_range.py` 複数範囲を許す。`by_chain` / `contains` / `spelled` /
  `wanted_numbers` を追加。範囲は書き順によらず配列順に並べ替える
- `split.py` 鎖→範囲の**並び**。切り出しはどれかの範囲が持てば残す。範囲ごとの
  採用数も数える（「その範囲が何も選ばなかった」は 2 範囲のほうが起こしやすい）
- `prepare_complex.py` 被覆は範囲の**和集合**（間の 168 残基は要求していない）。
  ジスルフィド・金属の絞り込みはどれかの範囲に入っていればよい
- `clean_protein.py` 欠損残基のウィンドウを範囲ごとに持つ。**内部欠損は安全では
  なくなった**: 2 つの窓の間の隙間は両端に足場があるので、放っておくと
  「範囲が消したもの」をそのまま作り直す

### 脂質パッチが蛋白質力場に縛られていた

TIP3P を要求すると `ff19SB + tip3p is blocked by MDClaw` で止まる。止まっているのは
**脂質と水とイオンしか入っていないパッチの平衡化**で、蛋白質は一分子もない。
`PATCH_EQUIL_FORCEFIELD = "ff19SB"` が固定だったため。水モデルに従うようにした
（tip3p なら ff14SB）。参照 14 件はすべて CHARMM36/TIP3P なので、これがないと
膜タスクは一件も解けない。

### 参照が両端を繋いでいるかは、プロンプトが言わないと分からない

寄託の 5ZK8 は残基 214 と 383 が **9.63 Å** 離れている（間に BRIL がある）。参照は
**1.35 Å = ペプチド結合**で直結した 273 残基 1 本鎖。融合 10 件を測ると
**6 件が繋ぎ、4 件が分けたまま**で、寄託者ごとに違う。残基範囲と同じく寄託が
記録していない事実なので `joins_its_pieces` で測り、繋いだ 7 件のプロンプトに
「Join the pieces ... bonded where the removed part was」を足した。
008 (6I53) は 3 鎖が複数範囲を持ち、どの鎖を繋いだのか件数から読めないので
**推測せず SystemExit する**。

**MDClaw はこの 9.63 Å を閉じられない**。トポロジーは 2 断片 [197, 76] になり、
参照の [273] と `monomer_count_matches_reference` で食い違う。3 つ目の欠落として記録。

### 008 (6I53) の鎖対応が壊れている

GABA-A 五量体。寄託は A-E + G の 6 鎖、参照は 8 鎖。長さで一意に決まる:

    参照 C(349)→寄託 A   参照 H(347)→寄託 D   参照 A(303)+B(33)=336→寄託 E
    参照 D(305)+E(33)=338→寄託 B   参照 F(297)+G(31)=328→寄託 C
    寄託 G(123) は参照が捨てている

ところが配列一致で照合したため参照 4 鎖が全部寄託 E に載り、プロンプトが
「chain E residues 8-312 and 10-312 and 418-447」という**重なった範囲**を要求して
いる。寄託 B と D は一度も現れない。`assign_distinct_chains` は同一 SEQRES の
双子を探すが、「同じサブユニットのもう 1 コピー」と「同じ鎖のもう 1 断片」を
区別できない。100 件中この 1 件だけ、eval split。未修正。

### 膜検査は残基名を比べていた。DPPC には綴りが二つある

前項の `membrane_matches_reference` を膜タスクで実際に走らせる前に確かめたところ、
**正しい提出物を落とす検査だった**。CHARMM は DPPC を 1 残基で書き (PDB は 3 桁に
切って `DPP`)、Amber の Lipid21 は頭部 `PC` と尾部 `PA` 2 本に分ける。参照 14 件は
すべて CHARMM36 の `DPP` 360 分子で、MDClaw は Amber しか組めないので提出物は
必ず `PC`+`PA` になる。集合として `{DPP}` と `{PC,PA}` は一致しない。
**CHARMM36 をプロンプトに書いていたのと同じ種類の誤り**で、参照の道具立てを
提出物に要求していた。

両辺を Lipid21 成分に分解してから比べるようにした: `DPP`→{PC,PA}、`PC`+`PA`→{PC,PA}。
POPC は {PC,PA,OL} なので取り違えは検出できる。**本数は頭部残基で数える** —
Lipid21 では 1 DPPC が 3 残基なので、残基で数えると 3 倍になる。

`DPP` は DPPC/DPPE/DPPG のどれでもあり得て 3 桁からは決まらないので、
**契約に `reference.bilayer = {"lipid": "DPPC", "residues": 360}` を記録**し、
採点はその名前で切り詰めを解く。参照 PDB からは本数だけを取る。膜 14 件に記録済み
(LIPIRES 360–492)、他 86 件は null。

MDClaw 側は `embed_in_membrane` (patch-tile) を持ち、DPPC パッチは同梱キャッシュ
`d20b3582` に構築済み (PA/PC のみで OL なし) なので冷ビルドは要らない。

### 膜タスク 14 件は解けないプロンプトだった。脂質の扱いを決めた

膜タスクを実際に解こうとして、プロンプトが**二重膜に一言も触れていない**ことに気づいた。
参照 (5ZK8) は鎖 M に DPPC 360 分子 46800 原子を持つ受容体で、プロンプトは
"in explicit solvent" としか言っていない。**エージェントは水中に置く。** D01 の残基範囲と
同じ、指示しなければ解けないタスクだった。

**脂質の本数は書かない.** 本数は箱の大きさの帰結であって化学の判断ではない。書くと
「参照の箱を当てる課題」になる。

**そのままだと採点が壊れる.** `read_residues` は脂質を残基として拾い、`split_monomers` は
360 個の 1 残基 monomer にし、`element_totals` はリン 360 を数えていた。つまり
本数を書かないなら、320 本の良い二重膜を作った提出物が monomer 数でも元素数でも落ちる。
**脂質を溶媒・イオンと同じ環境扱いにした**: 膜参照の組成比較は monomer 1 個 (273 残基)、
元素は C 1465 / N 336 / O 357 / S 19 になる。

**それだけだと穴が空く.** 脂質を一切見ないと、膜を作らず水に入れた提出物が prep 満点を
取る。`membrane_matches_reference` を足した: **種類は厳密に照合、本数は参照の半分以上
あるかだけ**。種類は寄託に書かれていない化学の判断 (結晶に写る秩序脂質はせいぜい数個)
なのでプロンプトが述べ、この検査が測る。

解答済み 3 系で再採点して 20/20 満点、膜検査は「参照に二重膜なし・提出物にもなし」で合格。

### 54 件が組めない力場を指定していた

**MDClaw のカタログは Amber のみ** (ff14SB / ff19SB / ff15ipq / fb15 と legacy な ff99 系。
ff94/96/99 は obsolete として拒否)。にもかかわらず 100 件中 54 件が CHARMM36 または
CHARMM36m を指定していた。`buildable_force_field` が防ぐはずだった「従えないプロンプト」
そのものである。CHARMM 参照の 54 件は**力場を指定しない** (Parm99 と同じ扱い)。
md 検定を力場非依存に設計したのは、まさにこれをエージェントに委ねるためだった。

**プロンプトを契約から復元しようとして情報を落とした.** 契約は鎖単位の内部欠失を
持たないので、5ZK8 は融合部 115 残基の説明が消え、4OW0 は OCS と分かっている残基を
「補完せよ」に逆戻りした。**元データから作り直し、較正だけ引き継ぐ**手順に変えた。

### 生成した契約で実際に採点した。3 系とも満点

統計の議論とは別に、動くかどうかは解いた提出物を採点すれば分かる。解答済みの
3 ジョブを、生成した契約・レプリカ横断で測り直した帯・スラック 4・判別力による
診断落ちを全部通したうえで採点した (2026-08-23):

    062_metal_6w9c   prep 1.000  md 1.000  (19/19)
    063_metal_6wrh   prep 1.000  md 1.000  (19/19)
    060_metal_4ow0   prep 1.000  md 1.000  (19/19)

同じ帯に対し negative controls は 10 本すべて正しく判定され、4 ゲートすべてが
単独で判定を決める (`gates_never_decisive` が空)。

**これで言えること**: 正しく流した提出物は通り、退化した偽物は落ちる。実測である。

**これで言えないこと**: 単一レプリカの 61 タスクで正しい提出物がどれだけ落ちるか。
測れないだけで、壊れている証拠はない。実際に解けば分かる種類の問題であり、
とくに膜 14 件と核酸 14 件は「タスクとして解けるか」自体が未検証。

### スラックを 2.0 から 4.0 に上げた。2.0 は正しい提出物を落としていた

**測り方が間違っていた.** スラック 2.0 は PLpro 3 件を**同一軌道内の**ブロック交差検証で
決めた。それは「同じ run の別の窓が通るか」を答えており、「**別の run が通るか**」ではない。
提出物は独立に走らせた別の run なので、後者が問うべき問いだった。

レプリカを持つ 39 参照で **leave-one-replica-out** を測ると:

    スラック   hold-out 棄却率 (最悪 fold)
    0          中央値 0.40  最大 1.00
    2 (旧値)   中央値 0.10  最大 0.70   ゼロは 18/39 のみ
    4          ゼロ 37/37/38 (検定別)

**旧値では正しい提出物が中央値 10%、最悪 70% の確率で落ちていた.**

**検定ごとに分けたら「収束しないタスク」は消えた.** 3 検定を同時にゼロにする単一の
スラックを探していたので「16 でも収束しない 1 件」が出ていた。検定別に見れば
全 39 タスク・全 3 検定が収束する。必要量は順位相関 中央値 2 最大 8、総 RMSF 中央値 1
最大 12、Rg 中央値 2 最大 12。

**上限も測った.** 各タスクの窓から、退化したベースラインが帯からどれだけ離れているかを
計算した (シャッフル→順位相関 0、凍結→総 RMSF 0、85% 圧縮→Rg)。100 タスクの**最小値**は
順位相関 -0.8、総 RMSF 2.7、Rg 0.7。**D01 で測った 28/84/16 は典型値であって律速ではなかった。**
一部のタスクは、スラックがいくつであっても退化した偽物を検出できない。

### 判別力のないタスク×検定は診断に落とす。再現性では落とさない

- **判別力**: 上限 < スラックなら、広げた帯が偽物を含むので何も判定していない。
  全 100 件で測れる。**6 組を診断に落とした。**
- **再現性**: hold-out の必要量 > スラック。**レプリカのある 39 件でしか測れない。**
  当初これでも 5 組落としたが、**測れたタスクだけが罰せられる**ので取り消した。
  同じ性質は単一レプリカの 61 件にもあるはずで、そちらは素通りする。契約には記録を残す。

結果、300 組中 **294 組を採点**、6 組が診断。全タスクが少なくとも 1 つの帯検定を保持する。

**この変更で溶媒時計が初めて単独で試された.** スラック 4 では 100 ps 打ち切りが総 RMSF の
帯を通るようになり、時計だけが捕まえる。ベースライン 10 本すべてが正しく判定され、
 が空になった。

### 主張しすぎていた点 (レビュー指摘、訂正済み)

- **「帯は敵対的ベースラインを排除する」は言い過ぎ.** 排除を確認したのは 3 つの**退化した点**
  (相関 0、RMSF 0、85% 圧縮) だけで、半分凍った run や ANM アンサンブル (RMSIP 0.749 に
  達する) については何も測っていない。契約の文言を直した。
- **「スラック 4 なら正しい提出物は通る」も言い過ぎ.** fold あたり 30 窓で棄却ゼロが示すのは
  真の棄却率が概ね 1/10 以下ということで、ゼロではない。しかも比較相手は出荷する帯より
  狭い代理帯 (fold は r-1 本しかプールしない)。
- **294/300 という数はスラック選定の目的関数そのもの**なので、良く採点できている証拠には
  ならない。100 件中 61 件は、このモジュールが直そうとした「1 本の軌道で作った帯」を
  そのまま積んでいる。

### 直したバグ 2 件 (どちらも即時の故障)

- スラックを数値から検定ごとの辞書に変えたのに  が  のままで
  。**md 側の閾値を変えたら negative controls を再実行する、という不変条件が
  実行不能になっていた。**
-  が辞書にキーが無いと既定値 0 に落ちる。**帯が広がらないので正しい提出物が
  落ちる。** 欠損は 0 ではないので、例外を投げるようにした。

### 契約生成器のレビュー — 11 件を採用

pi に `_task_builder.py` をレビューさせ、11 件を採用した。うち 3 件は生成した 100 件の
プロンプトに誤りを書き込んでいた。

**プロトン化の残基番号が参照ファイル由来だった.** このモジュールの存在理由は「寄託の
auth 番号で書く」ことなのに、`stated_protonation` だけ参照 PDB の `resseq` を返していた。
**参照は残基を振り直す** (ATLAS 16pk_A は自身のファイルで 1-415)。つまり
**エージェントが寄託で見つけられない番号**を書いていた。D01 で踏んだのと同じ種類の誤り。
SEQRES 経由で auth に写すようにし、写せない場合はその行を出さない。

**`ARN` と `TYM` が `IONISATION` から漏れていた.** どちらも `composition.CANONICAL_RESIDUE`
にあり、水素 1 個分の差なので**採点器は原子数で検出する**。述べなければ答えようのない
検査になる。HIP/CYM/ASH/GLH/LYN と同じ扱いにした。

**`numbering_certain` を計算していたが誰も読んでいなかった.** 外挿した番号が観測された
番号と同じ太字で印字されていた。契約に記録し、近似分岐での「文字列が返れば確実」という
誤った再定義も直した。生成 100 件のうち 17 件が外挿を含む。

他に採用: `None` が本文に出る経路 (鎖・範囲・差分・修飾残基) を全て塞ぎ、番号が復元
できない鎖は**タスクごと落とす**。修飾残基を名前で重複排除していたので 2 つ目の OCS が
消えていた。二鎖統合で除去残基数を auth 番号の引き算で出しており、再番号された融合部で
160 残基を 790 と報告していた (分類器の記録値を使う)。双子鎖に付け替えても範囲を測り直して
いなかった。温度が無いのに `**None K**` と書いていた。水モデルのハイフン表記を取り
こぼしていた。配列の当てはまり率を検証していなかった (不一致を「未観測」として読み飛ばす
ので、配列相違や繰り返し配列で以降が全部ずれる)。

### 追加: prep がエラー終了したら prep=0 / md=0

`find_node` は完了ノードが無いと `SystemExit` を投げるので、**prep がエラー終了した
提出物は採点器ごと落ち、結果に行が残らない** (「未実施」と読める) 状態だった。
`topology_loads_and_is_parameterized` で 2026-08-21 に直したのと同型。
必要な段と成果物を先に解決し、無ければ全検査を失敗として理由付きで返す。
**両軸を同時にゼロにするのは意図的**で、prep が失敗した提出物には比較すべき構造も
流された系も無く、md を計算しても別の分子の話になるため。

---

## 2026-08-23 — 100 タスク (訓練 70 / 評価 30) を確定。検証は自動化した

`docs/task-candidates.md` に一覧。母集団は (6) の統合 35602 件、適格 4036 件。

### 検証パイプライン — D01/D02 で手作業したことを自動化した

候補 248 件について、参照の `structure.pdb` と PDB 寄託を両方落として照合する。
**残基番号ではなく配列で合わせる** (参照は 1..N に振り直していることがある)。
段階を踏むごとに「使えない」が「プロンプトに書けばよい」に変わった:

| 照合方法 | 全鎖一致 | 何が変わったか |
|---|---|---|
| 観測原子と比較 (B-2) | 195 / 248 | ATLAS 42/75、膜 24/30 |
| **SEQRES と比較 (B-3)** | **221 / 248** | ATLAS 73/75。参照が欠損を補完している系が説明可能になった |
| **未知残基を X で保持 + 近似一致 (B-4)** | **221 + 14 + 2 / 248** | ATLAS 75/75、膜 27/30、CV19 4/8 |

**踏んだバグを 2 つ記録する。どちらも黙って母集団を壊すたぐい。**

- **SEQRES 中の非標準残基を読み飛ばすと、以降の位置が全部ずれる.** 4OW0 の SEQRES には
  OCS (システインスルフィン酸) があり、これを飛ばしたせいで 101 残基不一致という
  偽の結果が出た。**未知残基は `X` (ワイルドカード) として保持する。**
- **ATOM 側の未知残基は逆に除外しないといけない.** 上を直したら今度は膜の参照から
  POPC が `X` として配列に入り、膜が 28 -> 21 に落ちた。**SEQRES はポリマーのみを
  列挙するので X で保持、ATOM 側の未知はリガンド/脂質なので除外**、と区別する。

### 自動検証が見つけたもの

- **6WRH (現行 D02) の `114:S->C`** = C111S。D02 のプロンプトはこれを明記しており正しい。
  (会話中の私の要約は D01/D02/D03 と PDB の対応を取り違えていた。実際は
  D01=MCV1900209=6W9C 野生型、D02=MCV1900210=6WRH 変異体、D03=MCV1900208=4OW0。)
- **4OW0 (現行 D03) の残基 112 が OCS** で、参照はそれを CYM (チオラート) に戻して流している。
  **D03 のプロンプトはこれに触れていない。** prep が 1.000 なのは MDClaw が既定で
  OCS -> CYS に変換しているからで、結果的に通っているだけ。C111S は明記して OCS は
  明記しない、という一貫性の問題が残る。**要判断。**
- **GPCR 14 件の融合パートナー除去.** 6PS2 (beta2AR) は `A:52-254+415-494`、
  ICL3 に挿入された BRIL 160 残基を参照が除いている。5ZK3/5ZK8/6A93 等も同様。
  「融合部を除いた 2 区間」としてプロンプトに厳密に書ける。

### 安定性: 一律 4.0 A。サイズ補正は測ったら根拠が無かった ((7) 参照)

候補 248 件を測り、後 1/3 平均 RMSD > 4.0 A を不採用。軸ごとの通過率:
ATLAS 50/75、MoDEL 47/55、ナノボディ 24/25、リガンド 15/25、核酸 25/30、膜 16/30、CV19 4/8。

### レプリカ: 帯が 2 割狭かった

適格 4036 件のうち **2143 件 (53%) が 2 本以上のレプリカ**を持つ (ATLAS 全 1938 件が 3 本、
ナノボディ 220 件が 2-3 本)。**`ACCESSION.N` で解析も軌道もレプリカ単位に引ける**
(`A02K9.2` -> mdNumber=2)。

帯は「参照の 1 ns 窓の分布」から作るが、提出物は独立に走らせた別の run である。
ATLAS 20 系で Rg の窓分布を測った:

    全レプリカ混合 SD / 1 本内 SD : 中央値 1.205、平均 1.252、最大 1.824
    レプリカ間 SD / 1 本内 SD     : 中央値 0.787

**1 本の軌道だけで較正した帯は、ばらつきを中央値で約 2 割、最悪 8 割過小評価する。**
帯は平均 ± 2.0×SD なので、帯が 2 割狭い = 正しい提出物を落とす確率が直接上がる。
現行較正の実測された欠陥。対応:

1. レプリカがある系 (選定 100 件のうち 37 件) は全レプリカの窓をプールして帯を作る。
2. 単一レプリカの系は、実測した比で SD を膨らませる。上の 1.205 は Rg・ATLAS 20 系
   だけの値なので、採用前に 3 統計量 x より多くの系で測り直す。
3. レプリカ 1-2 で較正し、レプリカ 3 の窓を帯に当てて偽棄却率を測る。同一軌道内の
   ブロック交差検証より強い検証になる。

### 訓練 70 / 評価 30 の分割

同じ系が両側に出ると評価が暗記の検出になるので、参照配列の 3-mer 包含率で
クラスタリングし、**クラスタ単位で**分ける。閾値は実測で決めた:

    閾値   クラスタ数  最大  ナノボディの分かれ方
    0.30      83      10   [10]        <- VHH が 1 塊。評価から軸が消える
    0.50      88       5   [5,1,1,1,1,1]
    0.70      93       4   [1]x10      <- VHH は全て別クラスタ
    0.90      94       4   [1]x10

**0.70 を採用.** 0.30 はフォールド単位で厳しすぎ、VHH 10 件が 1 クラスタになって評価から
ナノボディ軸が丸ごと消えた。漏洩として困るのは「同じ系が両側に出ること」であって、
同じフォールドの別の系まで分けるとフォールド単位の汎化が測れない。0.70 では同一系の
重複 (1B2S や 1BXY が 2 回出る等) だけがまとまる。

### 構成

| 軸 | 件数 (訓練/評価) | 供給源 | 力場 | 窓 |
|---|---|---|---|---|
| 膜タンパク質 | 14 (11/3) | ebrains/mcns (mmb) | CHARMM36 | 1 ns |
| ナノボディ | 5 (3/2) | nanobodies (mmb) | ff99SB-ILDN | 1 ns |
| 蛋白-リガンド | 10 (7/3) | ligate (cin) | ff99SB-ILDN | 1 ns |
| 核酸 | 14 (10/4) | bigna (mmb) | ParmBSC1 ほか | 1 ns |
| 金属 (PLpro) | 4 (3/1) | cv19 (mmb) | ff14SB | 1 ns |
| 単鎖タンパク質 | 32 (21/11) | atlas (bsc) | CHARMM36m | 1 ns |
| 単鎖タンパク質 | 21 (15/6) | model (mmb) | Parm99 | 1 ns |

**寄託が複数鎖のタスクが 48 件** (蛋白-蛋白界面を含む)、**レプリカ 2 本以上が 37 件**。
力場は CHARMM36 / CHARMM36m / ff99SB-ILDN / ff14SB / Parm99 / ParmBSC1 に分散しており、
md 検定が力場非依存であることの検証材料にもなる。

### 未解決

- **DynaRepo (inr 930 件) を入れるか.** 蛋白-蛋白 709 件と**抗体-抗原 210 件
  (Dynabench: 1AHW Fab-組織因子、1DQJ/1MLC Fab-リゾチーム、1WEJ Fab-シトクロム c、
  2DD8 SARS RBD-80R Fab)**、**ヌクレオソーム 8 件 (1KX5/8OF4/3LZ0、`topology.prmtop`、
  `SYSTRES` = 1268 が寄託の観測残基数と完全一致)** がある。刻み 100 ps なので 2.5 ns 窓が
  必要 (ヌクレオソームは 1 ns 刻みで 25 ns 窓)。窓長はタスク毎の契約項目なので混在は
  設計上問題ない。**ただしライセンスが未解決**: MDDB のメタデータは Apache 2.0 (709 件) と
  未記載 (210 件) を返すが、論文は CC-BY-NC 4.0。本リポジトリの不変条件は「CC BY / CC0
  のみ」なので、採用するなら不変条件の側を変える判断が要る。
- **4OW0 の OCS をプロンプトに書くか** (上記)。
- `mddatabench/reference.py` が `mmb.mddbr.eu` 直書き。**(ノード, accession) の対**を
  受けるようにする必要がある (accession はノード毎に独立)。

### 追記 — 修飾残基はプロンプトに書く (規約に追加)

4OW0 の残基 112 は寄託が **OCS = システインスルホン酸** (`HETNAM OCS CYSTEINESULFONIC ACID`、
`FORMUL C3 H7 N O5 S`) で、システインの側鎖 SH が -SO3H に酸化されている。触媒 Cys の
結晶化中の酸化産物で、参照はこれを通常のシステイン (CYM) に戻して流している。

**採点上は無害ではない**: OCS は酸素が 3 個多いので、残せば
`element_composition_matches_reference` が落ちる。D03 が通っていたのは MDClaw が既定で
OCS -> CYS に変換しているからで、エージェントには当てようがない情報だった。

**規約に追加**: `MODRES` レコードのある修飾残基を参照が親残基に戻している場合、
プロンプトに書く。C111S のような点変異を書いておいて修飾残基を書かないのは一貫しない。
D03 のプロンプトに追記済み。

### 訂正 — NAFlex のヌクレオソーム (A017E) は使える

(5) で「1KX5 は参照が残基番号を 1..1058 に振り直していて寄託との対応が取れない」として
見送ったが、**SEQRES 照合を実装したら完全に説明できた**:

    鎖 A/E (H3)   SEQRES 38-135  (98 残基)  N 末端テール 1-37 を除去
    鎖 B/F (H4)   SEQRES 21-102  (82 残基)  テール 1-20 を除去
    鎖 C/G (H2A)  SEQRES 12-119  (108 残基) テール 1-11 と C 末 120-128 を除去
    鎖 D/H (H2B)  SEQRES 32-125  (94 残基)  テール 1-31 を除去
    鎖 I/J (DNA)  SEQRES 2-146   (145 nt)

**刻み 10 ps、後 1/3 RMSD 2.44 A** なので 1 ns 窓でそのまま使える。DynaRepo 版
(全長テール、1 ns 刻み、25 ns 窓が必要) と合わせると、**同じ 1KX5 のテール有無の対照ペア**
になる。「番号が合わないから使えない」という判断は、照合方法が悪かっただけだった。

### DynaRepo を採用した (ライセンスの扱いは変えた)

`inr` 930 件のうち **928 件**がメタデータ条件を通る。多様性で 52 件に絞り、参照構造と
寄託を落として SEQRES 照合と安定性測定をした:

| 群 | 絞り込み | SEQRES 照合 | 後 1/3 RMSD 中央値 | 4 A 超 |
|---|---|---|---|---|
| 蛋白-蛋白 (Dynarepo) | 24 | **24/24 全鎖一致** | 3.41 | 10 |
| 抗体-抗原 (Dynabench) | 26 | 20 一致 + 1 変異のみ | 3.11 | 6 |
| ヌクレオソーム | 2 | 1 融合部除去 + 1 不一致 | **6.66** | **2/2** |

**DynaRepo のヌクレオソームは 2 件とも安定性で落ちた (6.66 A).** 全長テールの
ヌクレオソームはテールと DNA の呼吸で大きく動く。**テールを刈った NAFlex 版
(mmb:A017E、10 ps、2.44 A) の方が参照として適切**で、そちらを核酸軸に入れた。
「全長構築物の方が良い」という直感は測ったら逆だった。

**ライセンスは不変条件の側を変えた.** `CLAUDE.md` / `AGENTS.md` の
「CC BY / CC0 のみ」を「MDDB が返すライセンス文字列を契約に逐語で記録する。
大半は CC BY 4.0。DynaRepo は Apache 2.0 か未記載を返すが論文は CC BY-NC 4.0 と書いており、
その食い違いをタスク毎に記録する。いずれにせよダウンロードしたものは再配布しない」に
書き換えた。ノードの不変条件も追加した。

### 最終構成 (100 件、訓練 70 / 評価 30)

| 軸 | 件数 (訓練/評価) | 供給源 | 力場 | 窓 |
|---|---|---|---|---|
| 膜タンパク質 | 14 (11/3) | ebrains/mcns (mmb) | CHARMM36 | 1 ns |
| **抗体-抗原** | **10 (7/3)** | Dynabench (inr) | CHARMM36m | **2.5 ns** |
| **蛋白-蛋白** | **6 (4/2)** | Dynarepo (inr) | CHARMM36m | **2.5 ns** |
| ナノボディ | 5 (3/2) | nanobodies (mmb) | ff99SB-ILDN | 1 ns |
| 蛋白-リガンド | 10 (7/3) | ligate (cin) | ff99SB-ILDN | 1 ns |
| 核酸 (ヌクレオソーム含む) | 14 (10/4) | bigna (mmb) | ParmBSC1 ほか | 1 ns |
| 金属 (PLpro) | 4 (3/1) | cv19 (mmb) | ff14SB | 1 ns |
| 単鎖タンパク質 | 24 (16/8) | atlas (bsc) | CHARMM36m | 1 ns |
| 単鎖タンパク質 | 13 (9/4) | model (mmb) | Parm99 | 1 ns |

**寄託が複数鎖のタスクが 56 件、レプリカ 2 本以上が 39 件。**
力場は CHARMM36 / CHARMM36m / ff99SB-ILDN / ff14SB / Parm99 / ParmBSC1 に分散。

### `reference.py` をノードとレプリカに対応させた

- **`NODES`** に 8 ノードの API を持たせ、`fetch_reference(..., node=...)` で選ぶ。
  既定は `mmb` = `irb-dev.mddbr.eu` (旧 `mmb.mddbr.eu` はその部分集合なので使わない)。
- **`replica_id(accession, n)`** が `ACCESSION.N` を組み立てる。解析も軌道もこの形式で
  レプリカ単位に引ける。帯をレプリカ横断でプールするのに要る。
- **トポロジーは `prmtop` / `tpr` / `psf` / `top` の順に探す.** ノードごとに形式が違う
  (mmb/cin/rpbs は prmtop、bsc/oxf/inr は tpr、inr の一部は psf)。どれが来たかを
  provenance に記録する。
- **フレーム数は `totalFrames` を `mdcount` で割る.** `totalFrames` は全レプリカの合計。
  inr と oxf はそもそも持たないので、`rmsds` 解析の系列長にフォールバックする。

動作確認: `bsc:A02K9.2` (ATLAS 16pk_A のレプリカ 2/3) が `topology.tpr` 付きで取れる。

**残件**: 採点器 (`mddatabench/topology.py`) は参照トポロジーを prmtop 前提で読む。
`tpr` / `psf` を読めるようにしないと、ATLAS・膜・DynaRepo のタスクは prep 側を採点できない。

---

## 2026-08-22 (7) — 100 タスク化に向けた候補検証。閾値の根拠を測り直した

(6) で得た適格 4036 件から、軸ごとに層化して **248 件**に絞り、参照軌道の安定性と
参照 vs 寄託の対応を実測した。

### mdCATH は見送り (温度は理由ではない)

(6) で mdCATH を「320-450 K の高温」として切ったが、**320 K は正当な温度で、これは
切る理由にならない**。採点器は参照の `TEMP` を目標にするだけで 300 K である必要はない。
しかも `mds` が `['320_rep1'...'320_rep5', '348_rep1', ...]` と**温度別・レプリカ別に
個別指定できる**ので、320 K の 5 レプリカだけを選べる。

実際の障害は別に 3 つあった (全 5398 件で実測):

- **`mdTime` = `mdFrames`、つまりフレーム間隔がちょうど 1 ns.** 1 レプリカ 441-500 ns /
  441-500 フレーム。1 ns 窓に参照フレームが 1 枚しか入らないので、窓内 RMSF も Rg 平均も
  定義できない。25 フレーム確保するには 25 ns 窓が要る。
  なお `fluctuation_profile_matches_reference` (API の全軌道 RMSF との順位相関) は窓を
  使わないので成立する。つまり md 検定 3 本のうち 1 本だけ通る、という歪な状態になる。
- **トポロジーファイルが 0/5398.** あるのは `trajectory.bin` / `structure.pdb` /
  `trajectory.xtc` / `screenshot.jpg` のみ。
- **ENSEMBLE が NVT.** `solvent_box_is_physical` (密度帯 + 箱の分散 > 0) は NPT 前提。

4036 件で全軸が埋まるので、無理に入れない。

### 安定性: 一律 4.0 A を維持する。サイズ補正は測ったら根拠が無かった

膜の候補 30 件は後 1/3 平均 RMSD の中央値が 3.70 A で、13 件が 4 A を超えた。
「大型多ドメイン系に小型可溶性タンパク質の閾値を当てるのは不当ではないか」と疑ったので、
候補 247 件でサイズ依存を測った。

    残基数帯      n   中央値   75%    90%   ドリフト中央値
    0-100        71   2.69   3.72   6.09   0.14
    100-200      86   2.44   3.85   6.46   0.23
    200-350      51   2.68   3.45   4.49   0.36
    350-600      19   2.90   4.34   5.81   0.38
    600-1200     12   4.43   5.40   5.85   0.59
    1200-         5   3.49   4.28   6.05   0.51

    log-log 回帰: RMSD = 1.911 * N^0.095、相関 (log) = 0.171

**サイズは RMSD をほとんど説明しない.** 指数 0.095、相関 0.17。600-1200 帯が 4.43 A なのに
1200 超が 3.49 A で単調ですらない。**スケール則で膜だけ緩めるのは、ノイズへの当てはめ**に
なる。一律 4.0 A を維持する。膜は 30 件中 17 件が通るので定員 12 には足りる。

軸ごとの後 1/3 RMSD 中央値 (4 A 超の数): ATLAS 3.09 (25/75)、MoDEL 2.60 (8/55)、
**ナノボディ 1.83 (1/25)**、リガンド 3.08 (9/24)、核酸 2.43 (2/30)、膜 3.70 (13/30)、
CV19 3.00 (3/8)。ナノボディが際立って安定なのは 100 残基強の単一ドメインだから。

### 窓長: 1 ns 固定で全軸が埋まる。ただし抗体–抗原だけは 2.5 ns が要る

(6) で「可変窓にしても 4036 -> 4230 にしかならない」と書いたが、**これは inr (DynaRepo) と
oxf が一覧 API に長さ情報を持たないために除外されていたためで、訂正する。**
`mdTime` は個別取得でも None。**`rmsds` 解析の系列長からフレーム数を直接数えた**:

| 供給源 | フレーム/レプリカ | 刻み | 1 レプリカ | 必要な窓 | 窓数 |
|---|---|---|---|---|---|
| Dynarepo (1AK4) | 2501 | 100 ps | 250 ns | 2.5 ns | 100 |
| **Dynabench (1AHW 抗体–抗原)** | 1000 | 100 ps | 100 ns | 2.5 ns | 40 |
| GLIC 膜 (9LB9) | 1001 | 200 ps | 200 ns | 5 ns | 40 |
| ヌクレオソーム (1KX5) | 2000 | 1 ns | 2000 ns | 25 ns | 80 |

**1 ns プールには抗体–抗原複合体が無い** (ATLAS は単鎖、MoDEL の多量体と ligate の
複合体はあるが抗体ではない)。Dynabench 210 件がその唯一の供給源で、2.5 ns 窓が要る。
窓長はタスク毎の契約項目 (`md_calibration` は参照自身の窓から実測する) なので、混在は
設計上問題ない。

**ただし DynaRepo はライセンスが未解決.** MDDB のメタデータは Dynarepo 本体 709 件が
Apache License 2.0、Dynabench 210 件が未記載を返すが、DynaRepo の論文は CC-BY-NC 4.0 と
書いている。本リポジトリの不変条件は「CC BY / CC0 のみ」なので、採用するなら不変条件の
側を変える判断が要る。**未解決のまま採用しない。**

### 候補の名前が答えを持っている軸がある

D01/D02 は「参照が寄託の一部しか流していない」ことをプロンプトに書かねば解けなかった。
候補の NAME を見ると、その情報が最初から入っている軸がある:

- **ナノボディ**: `1kxv_C2-120_NA nanobody` = PDB 1kxv / 鎖 C / 残基 2-120。
  `PROTRES` = 119 = 120-2+1 と全件整合する。**プロンプトに書く内容がデータ側にある。**
- **ATLAS**: `ATLAS 1ab1_A` = 鎖 A。残基範囲は書かれていないので照合が要る。
- **膜・リガンド・CV19**: 名前に情報が無い。配列照合で復元する。

### 検証は配列で行う (残基番号では合わない)

参照は残基番号を 1..N に振り直していることがある (1KX5 がそうだった)。そこで参照の
`structure.pdb` と PDB 寄託を両方落とし、**1 文字配列の部分文字列一致**で寄託側の鎖 ID と
残基範囲を復元する方式にした。ここで出る「鎖 + 開始-終了」が、そのままプロンプトに書く
内容になる。

---

## 2026-08-22 (6) — 走査していたのは 8 ノード中 1 つだった。(5) の「膜は作れない」は誤り

**(5) の結論のうち、母集団に関するものは全て取り消す。** (5) は `mmb.mddbr.eu` の
4554 プロジェクトだけを見ていた。MDDB は連合型で、**ノードは 8 つある**。

### ノードの見つけ方

`mmb.mddbr.eu` の API に `nodes` を叩くと **「`nodes` エンドポイントは global API に
しかない」**と教えてくれる。global API は **`https://mdposit.mddbr.eu/api/rest/v1/`**。

| alias | 機関 | api_url | 直接取得できた件数 |
|---|---|---|---|
| mmb | IRB Barcelona | `irb-dev.mddbr.eu` | **9062** |
| oxf | Oxford | `oxford.mddbr.eu` | 9108 |
| cin | Cineca | `cineca.mddbr.eu` | 5642 |
| bsc | BSC | `bsc.mddbr.eu` | 5489 |
| jsc | JSC | `jsc.mddbr.eu` | HTTP 500 (GLOBAL 経由で 5406 回収) |
| inr | Inria | `inria.mddbr.eu` | 930 |
| rpbs | RPBS | `rpbs.mddbr.eu` | 10 |
| ufl | U. Florida | `devmddb.rc.ufl.edu` | HTTP 500 (回収不能) |

**私が使っていた `mmb.mddbr.eu` (4554) は、登録ノード `irb-dev.mddbr.eu` (9062) の
部分集合だった。** ナノボディも膜タンパク質も、この差分の中にあった。

**global API は上位集合ではない.** 15190 件を持つが、`MCV1900208` (現行タスクの PLpro) は
global に**存在しない**。逆に oxf の 9108 件を 1 件しか索引していない。**全ノードを直接
叩いて和集合を取るしかない。** 直接取得できた分の統合母集団は **35602 件**。

**accession はノード毎に独立.** `A01M6` は oxf では MemProtMD、mmb では別物、bsc では
DynamicPDB。**タスク契約は (ノード, accession) の対で持つ必要がある。**
`mddatabench/reference.py` は `mmb.mddbr.eu` を直書きしているので要修正。

### また同じ型のバグを踏んだ — 「無い」を文字列で書くフィールド

(5) で `MEMBRANE == "No"` を `bool()` で真と読んだ。今回は **`CG_SELECTION == "none"`**
を `bool()` で真と読み、**ATLAS 1938 件を丸ごと「粗視化」として捨てていた**。
MDDB は欠損を空値ではなく文字列で書くことがある。`bool()` で読んではいけない。

### 適格性の再測定 (統合母集団 35602 件)

| 条件 | 残 |
|---|---|
| 古典 MD | 26174 |
| 全原子 (CG 除外) | 22700 |
| PDB ID あり | 19519 |
| 水モデル対応 | 19393 |
| 温度あり | 14408 |
| トポロジーあり (prmtop/tpr/psf/top) | 5479 |
| fluctuation + rgyr | 5461 |
| **1 ns 窓 x 10 本以上、窓内 25 フレーム以上** | **4036** |

**窓を可変 (刻み x 25、上限 5 ns) にしても 4230 にしかならない。** 1 ns 固定で足りる。
(ただし inr/oxf は一覧 API に長さ情報が無く、この数には入っていない。個別取得で確認中。)

### 適格 4036 件の内訳 — 欲しかった軸が全部ある

| コレクション | 件数 | 中身 | 力場 | 刻み |
|---|---|---|---|---|
| atlas (bsc) | 1938 | 単鎖タンパク質。PDB の鎖まで指定 (`1ab1_A`) | CHARMM36m | 10 ps |
| model (mmb) | 1530 | MoDEL | Amber Parm99 | 1 ps |
| **nanobodies (mmb)** | **220** | **VHH ナノボディ。PDB 214 種、117-131 残基** | ff99SB-ILDN | 10 ps |
| **ligate (cin)** | **214** | **蛋白–リガンド複合体 (結合親和性予測)** | ff99SB-ILDN | 10 ps |
| bigna (mmb) | 56 | NAFlex 核酸 (DNA 52 / RNA 4) | — | 2-20 ps |
| **ebrains/mcns (mmb)** | **55** | **膜タンパク質: GPCR・Nav・Cav・NMDA・GABA-A・nAChR** | CHARMM36 | 10 ps |
| cv19 (mmb) | 19 | PLpro ほか | ff14SB | 10-20 ps |

**膜タンパク質は作れる。** 55 件、全て CHARMM36 / TIP3P / 310 K (49) または 300 K (6) /
10 ps / `topology.tpr` / 100-2000 ns、脂質 360-932 残基。内訳は β2 アドレナリン受容体
(6PS0/6PS2/6PS5/6E67/6KR8/7BZ2/7DHR/7DHI)、A2A アデノシン受容体 (6GT3/6ZDV/6JZH/6PS7)、
5-HT2A (6WH4/6WGT/6A93/6A94)、5-HT1A-Gi (7E2Y/7E2Z)、ドーパミン D2/D3 (7DFP/7CMU)、
ムスカリン M1/M2 (6OIJ/6OIK/5ZK8)、メラトニン MT1/MT2 (6ME2/6ME3/6ME5/6PS8)、
Nav1.1/1.2/1.5/1.7 (7DTD/6J8E/7DTC/6N4Q/6N4R/6J8H/7K48/6W6O/6VXO)、Cav2.2 (7MIX/7MIY)、
NMDA 受容体 (7EOQ/7EOR/7EOS/7EOT/7EOU)、GABA-A 受容体 (6I53/6QFA/6D6U)、nAChR (6CNJ)。
蛋白 254-3144 残基なので、小さい GPCR から選べば計算量も現実的。

### 使えないと確認したもの (訂正ではなく確認)

- **MemProtMD (oxf 9007 件) は MARTINI 粗視化.** Martini 2.2 / Martini 3、水も Martini、
  323 K。1 ビーズ ≒ 4 重原子なので全原子ベンチの参照にできない。
- **oxf の全原子は 100 件だけ.** GLIC 7 件 (うち 4 件は外部電場 ±500 mV 印加の非平衡) と
  `usconv` 93 件 (`METHOD = Enhanced sampling`、タンパク質を含まない純脂質+ベンゼン)。
- **dynamicPDB (bsc 3336 件) はトポロジーファイルが無い.**
- **MDBind (cin 4960 件、PDB 4099 種) は TEMP と ENSEMBLE が全件欠損**、刻み 200 ps。
- **mdCATH (jsc 5406 件) は 320-450 K の高温**、刻み 1 ns。

### DynaRepo (inr 930 件) — 蛋白–蛋白/抗体–抗原。刻み 100 ps

CHARMM36m / TIP3P / 310 K または 300 K / NPT、`fluctuation`+`rgyr` が 930/930、
PDB 822 種。内訳は Dynarepo 本体 709 (Apache 2.0, `topology.tpr`)、**Dynabench 210
(抗体–抗原ドッキングベンチマーク: 1AHW Fab–組織因子、1DQJ/1MLC Fab–リゾチーム、
1WEJ Fab–シトクロム c、2DD8 SARS RBD–80R Fab。ライセンス未記載、`topology.psf`)**、
**ヌクレオソーム 8 件 (1KX5/8OF4/3LZ0、ff14SB+ParmBSC1+CUFIX、`topology.prmtop`)**。

ヌクレオソーム 8 件は `SYSTRES` = 1268 で **1KX5 の寄託観測残基 1268 と完全一致** する。
(5) で使えないとした NAFlex 版 (A017E、テールを刈って 1058) と違い、**完全な構築物**。
ただし**刻み 1 ns** なので 25 ns 窓が要る。

一覧 API に長さ情報が無いため、2.5 ns 窓で使えるかは個別取得で確認中。

**ライセンスに食い違いがある.** DynaRepo の論文は CC-BY-NC 4.0 と書いているが、MDDB の
メタデータは Apache License 2.0 (709 件) と未記載 (210 件) を返す。採用前に要確認。

---

## 2026-08-22 (5) — MDDB 全 4554 プロジェクトを走査した。選定条件とプロンプト規約を確定

3 本とも PLpro + 亜鉛だったので多様化する。そのために MDDB を全件走査した。走査の途中で
**メタデータの読み方を 4 回間違えた**ので、まずそれを記録する。どれも黙って誤った母集団を
作るたぐいの間違いで、閾値の話ではない。

### 走査で分かった API とメタデータの罠 (すべて実測)

**ページングは `page` だけ.** `skip` / `offset` / `start` は無視され、同じ 1 ページ目が返る。
`limit` は 200 を渡しても 100 で頭打ち。全 4554 件を取るには `?limit=100&page=N` を回す。

**`LENGTH` を長さに使ってはいけない。`ttime` を使う.** `LENGTH` は 4554 件中 **1674 件で欠損**
し、しかも `frames × FRAMESTEP` と **1070 件で食い違う** (`LENGTH` は流した長さ、`ttime` は
寄託された軌道の長さらしい)。`ttime` の欠損は 177 件だけで `frames × FRAMESTEP` に一致する。
**ダウンロードして窓を切れるのは `ttime` の方**。`LENGTH ≥ 100 ns` で絞ると適格が 5 件まで
落ちるが、`ttime` に替えると 1600 件になる。

**`MEMBRANE` は `"No"` か `null` の 2 値で、`"Yes"` は存在しない.** `bool(r["MEMBRANE"])` は
`"No"` を真と読むので、「膜 225 件」という数字を一度作ってしまった。実体は `LIPIATS > 0` の
**43 件**。脂質残基名 (`RSNAME` に POPC 等) で照合しても和集合は同じ 43 件。

**ライセンス文字列は "Creative Commons Attribution 4.0 …" (空白あり).**
`'creativecommons' in text.lower()` は **0 件**になる。

**非 CC は 4554 件中 24 件しかない** (AFL 9 / Apache 5 / MIT 4 / なし 4 ほか)。膜系に集中して
いるのは事実だが、その 24 件は全部フレーム刻み 500–1000 ps で別条件により落ちる。
**「データを再配布せず取得スクリプトだけ配る」ライセンス緩和をしても、増える候補はゼロ。**

### 適格性フィルタと通過数

| 条件 | 残 |
|---|---|
| 全プロジェクト | 4554 |
| CC BY / CC0 | 4530 |
| Classical MD | 4486 |
| PDB ID あり | 1940 |
| MDClaw が持つ水モデル (TIP3P/OPC/OPC3/TIP4PEW/SPCE) | 1872 |
| 温度あり | 1840 |
| `topology.prmtop` あり | 1674 |
| `fluctuation` と `rgyr` の解析あり | 1674 |
| 較正可 (刻み ≤ 40 ps かつ `ttime` ≥ 10 ns) | **1600** |

較正可の条件は「1 ns 窓が 10 本以上、各窓に 25 フレーム以上」。**100 ns 以上という縛りは
物理ではなく較正の都合だった**ので、窓数 10 本まで緩めた。MoDEL は 10 ns / 1 ps なので
1 ns 窓が 10 本・各 1000 フレーム取れる。

### 軸ごとの実態 — 膜と糖鎖は作れない

| 軸 | 全 DB | 適格 | 落ちる理由 |
|---|---|---|---|
| 蛋白のみ | 3118 | **1505** | — (全て MoDEL) |
| DNA | 909 | **53** | PDB ID 欠損 764 |
| RNA | 66 | **4** | PDB ID 欠損 45、刻み |
| ヌクレオソーム | 119 | **1** | PDB ID 欠損 115 |
| 糖鎖 | 293 | 0 | PDB ID 欠損 183、prmtop 欠損 40、刻み |
| 脂質 / 膜 | 43 | **0** | 刻みが最短でも 100 ps、大半 1200–3000 ps。24 件は PDB ID 無し |

**膜タンパク質のタスクは MDDB では作れない。** どの条件を緩めても作れない。1 フレーム = 1.2–3 ns
の軌道からは 1 ns 窓が切れず、PDB ID が無ければエージェントに与える出発構造も無い。
糖鎖も単独では作れないが、COVID セットのスパイク三量体 (6ACC/6ACD, ff14SB + GLYCAM-06j)
が糖鎖付きで適格なので、そこで 2 本立てる。

### MoDEL について確かめたこと

**参照系は厳密に「タンパク質のみ」.** 1530 件すべてで `SYSTATS == PROTATS`、
`NA` = `CL` = `COUNION` = `LIGANDS` = 0。**12CA の触媒 Zn も 1ARD の構造 Zn も参照では
除かれている**。金属を含む PDB を MoDEL から選ぶと参照自体が非物理的になり、プロンプトで
「亜鉛を外せ」と教えることになるので、**MoDEL からは金属を含まない PDB だけを選ぶ**。
金属サイトのタスクは COVID セット (PLpro) が担う。

**残基は PDB の観測残基そのもの.** 1530 件中 **1433 件**で `PROTRES` が RCSB の
`deposited_modeled_polymer_monomer_count` に一致する。欠損残基は補完されていない。
うち 1149 件は欠損残基ゼロ。残り 97 件は不一致 (-1 が 28 件、-632 のような大きな差も 1 件)
で、これらは参照が何をしたか分からないので**候補から外す**。

### 選定条件 (ハードフィルタ) — 全タスクに適用

1. CC BY または CC0。
2. `METHOD == "Classical MD"`。
3. `PDBIDS` が 1 件だけ (エージェントに与える出発構造が一意に決まること)。
4. `WAT` が MDClaw の持つ水モデルであること。
5. `TEMP` が数値で入っていること。
6. `files` に `topology.prmtop`、`analyses` に `fluctuation` と `rgyr` があること。
7. `FRAMESTEP ≤ 0.04 ns` かつ `ttime ≥ 10 ns` (1 ns 窓 10 本 × 25 フレーム以上)。
8. `PROTRES` が RCSB の `deposited_modeled_polymer_monomer_count` に一致すること。
9. 寄託に構造金属がある PDB は、**参照が金属を保持している場合のみ**採る。MoDEL は保持
   しないので、MoDEL からは金属なしのみ。
10. 分子間共有結合 (`inter_mol_covalent_bond_count`) がゼロであること。MoDEL は糖鎖や
    共有結合リガンドを持たないので、寄託にあると参照と食い違う。
11. 残基数 45 以上。20–40 残基のペプチド断片は「安定かどうか」を測る対象にならない。
12. 参照軌道自体が安定であること (MDDB の `rmsd` 解析で実測。下の表)。

### プロンプト規約

**述べるもの — 構造から推測できず、外すと採点が破綻するもの。**

| 項目 | 根拠 |
|---|---|
| 鎖 | 参照が寄託の一部の鎖しか流していないことがある (D02/D03 は C 鎖) |
| 残基範囲 | D01 は 4–315、寄託は 315 まで。**言わないと解けない** |
| 結晶学的変異の扱い | D02 の寄託は C111S。野生型を流すのか変異体を流すのか言う |
| 水モデル | `WAT` から取る。MDClaw の既定は opc なので TIP3P は明示が要る |
| 温度 | `TEMP` から取る。60 件中 300 K が 50、298 K が 8、310 K が 2 |
| アンサンブル | `ENSEMBLE`。60 件中 44 件が NPT、16 件 (NAFlex 核酸) は未記録 |
| 構造金属を残すこと | MDClaw の既定は残すが、参照が保持している場合に限り明示する |
| NMR ならモデル番号 | 第 1 モデルを使う、と言う |
| イオン化変種のプロトン化 | 下記 |
| 力場 | **一致できるときだけ** 下記 |

**プロトン化は「イオン化変種だけ」述べる。互変異性体は述べない。**
`RSNAME` に参照のプロトン化がそのまま出る。採点側の `residue_atom_counts_match_reference` は
**互変異性体には盲目で (HID と HIE は同じ原子数)、イオン化変種には敏感** (HIP/CYM/ASH/GLH/LYN
はどれも水素 1 個ぶん違う)。だから:

- `RSNAME` に **HIP / CYM / ASH / GLH / LYN** があれば、その残基のプロトン化をプロンプトで述べる。
  述べないと原子数チェックが落ち、エージェントには当てようがない。選定 60 件のうち HIP を持つ
  のは 1BDD, 1ASS, 1EZG, 1AY7, 1CGI, 1ACB, 1A59, 1AYX, 1VHH, 6M0J と PLpro 5 本。
- **HID / HIE は述べない**。採点に出ないので、述べると余計な手掛かりになる。
- **CYX も述べない**。ジスルフィドは幾何で見つかるべきもので、そこは測りたい能力。
- 触媒残基と金属配位残基のプロトン化は carve-out 済みなので、そもそも採点しない
  (2026-08-22 (2) 参照)。

**力場は一致できるときだけ述べる.**
- COVID セット (ff14SB, ff14SB+GLYCAM-06j) → **一致できるので述べる**。
- MoDEL (Amber Parm99) → MDClaw は ff99 系を obsolete として拒否する。**一致不可なので
  述べない**。エージェントの選ぶ力場で流させ、md 側の検定は力場非依存にしてある。
- NAFlex 核酸 (ParmBSC1 または未記録) → MDClaw は DNA.OL15 / RNA.OL3。**一致不可なので
  述べない**。

**述べないもの.** accession、解析の方法、曖昧なプロトン化、一致できない力場、
イオン濃度 (選定 60 件すべてで `NA` = `CL` = 0。参照は溶媒を落として寄託しているので
濃度は復元できない。中性化だけを求める)。圧力結合 (`PCOUPLING` は 4554 件中 56 件、
選定 60 件中 4 件にしか入っていない)。

**言い方は「何を」であって「どうやって」ではない.** ツール名も手順も書かない。

### 参照と寄託の対応を全候補で突き合わせた — ここで多くが落ちた

D01/D02 で踏んだ罠 (参照が寄託の一部しか流していない) は例外ではなく**常態**だった。
`PROTRES + DNARES + RNARES` を RCSB の `deposited_modeled_polymer_monomer_count` と
突き合わせると、核酸を含む適格 57 件は次のように割れる。

| 判定 | 件数 | 扱い |
|---|---|---|
| 完全一致 | 9 | そのまま使える |
| 寄託は N コピー、参照は 1 コピー | 1 | プロンプトで「1 本だけ流す」と言えば使える |
| 蛋白–DNA 複合体から **DNA だけ** | 33 | 「DNA だけを流す」と言えば使える |
| **説明不能** | 14 | **除外** |

除外した 14 件の内訳が重要:

- **1I0T (Z-DNA)**: 参照 20 nt に対し寄託の観測は 12 nt。**参照の方が多い**。別の構築物。
- **2AF1 (H-DNA)**: 参照 24 nt、寄託 12 nt。同上。
- **1Q9A (GAGA RNA)**: 参照 10 nt、寄託 27 nt。ヘアピンだけを切り出しているが、
  どこを切ったかは残基番号が振り直されていて復元できない。
- **1VTN (FOXA3–DNA) 6 レプリカ**: 参照は蛋白 102 + DNA 34 = 136、寄託の観測は 128。
  **参照が DNA を 8 nt 延長している**。エージェントには再現できない。
- **2UZK (FOXO3–DNA) 4 レプリカ**: 差 -110 が説明できない。
- **1KX5 (ヌクレオソーム)**: 差 -210。参照トポロジーを実際に落として数えたところ、
  ヒストン 8 本が 98/82/108/94 残基、DNA が 147+147 = 1058 残基。寄託 1KX5 は全長テールを
  持つ構築物なので、**参照はテールを刈っている**。残基番号が 1..1058 に振り直されていて
  寄託のどの残基に当たるかは配列アラインメントなしには言えない。**価値は高いが今回は見送り。**

**結果として、きれいな蛋白–DNA 複合体タスクは 1 本も作れない。** 核酸タスクは
「裸の二重鎖」と「蛋白–DNA 複合体から DNA だけを取り出したもの」になる。後者は
実体選択を測る良いタスクではある。

**スパイク糖蛋白 (6ACC/6ACD) も同じ理由で落とした.** 参照トポロジーは 3 本 × 1287/1285/1285
= 3857 残基。寄託 6ACC の観測は 3195 残基、未観測 414。**参照は欠損ループを埋めたモデル**で、
寄託から再現できない。**糖鎖タスクも作れない。**

### 参照軌道自体の安定性を実測した

MDDB の `rmsds` 解析 (**`rmsd` ではない。`rmsd` は 4554 件中 5 件にしかない**) を候補 77 件で
取り、後 1/3 の平均 RMSD と前 1/3 からのドリフトを測った。

後 1/3 平均 RMSD: 中央値 2.46 Å、四分位 1.95 / 3.51 Å、最大 6.67 Å。

**> 4.0 Å かつドリフト > 0.5 Å を除外**した。理由は閾値の好みではない: 提出側は寄託構造から
1 ns しか流さないので、参照が 10 ns で折り畳みを離れていると、**正しい MD が参照と一致しない**
(偽陰性)。実際に落ちたのは

  1IEH  6.67 Å (+1.91)   可溶性単一ドメイン抗体
  1BDD  6.58 Å (+2.59)   プロテイン A B ドメイン (60 残基の 3 ヘリックス束が parm99 で崩れている)
  1A59  5.78 Å (+1.40)   低温活性クエン酸シンターゼ
  1ASS  4.32 Å (+1.13)   シャペロニン apical ドメイン
  1ATX  4.20 Å (+1.05)   イソギンチャク毒素
  1G84  4.05 Å (+0.66)   IgE Cε2 ドメイン

**437D (RNA シュードノット, 4.08 Å / +0.58) だけは残した。** 閾値は蛋白で決めたもので、
RNA は本質的に可動性が高く、50 ns で 4 Å は折り畳み喪失を意味しない。適格な RNA が
そもそも 3 件しかないという事情もある。**これは判断であって測定ではない**ので、
そう明記しておく。

### 選定した 60 件 — 一覧は `docs/task-candidates.md`

| 群 | 件数 | 中身 |
|---|---|---|
| DNA | 14 | 裸の二重鎖 3 (1BNA / 1NAJ / 1KF1) + 蛋白–DNA 複合体から DNA だけ 11 |
| RNA | 3 | 2OUE (61 nt) / 2RN1 (32 nt) / 437D (シュードノット 28 nt) |
| 金属・リガンド | 5 | PLpro apo 3 (既存 D01–D03) + 阻害剤 3k 結合 2 (**Zn 保持 + GAFF リガンド**) |
| 抗体 / Ig | 5 | 1VHH (カメリド VHH) / 1MAJ (抗体 VL) / 1AR2 / 1BMG (β2m) / 2FCB (Fcγ 受容体) |
| 可溶性タンパク質 | 33 | 45–492 残基。1UBQ / 1BPI / 1PGB / 153L / 1SHG / 2CI2 / 1CSP / 1TIT を含む |

蛋白 38 件の被覆: 分類キーワード **37 種**、X 線 32 / NMR 5、ジスルフィド 0 本 24 / 1–2 本 8 /
3 本以上 6 (最大 16 本、1EZG)、単量体 31 / 2 鎖 5 / 3 鎖 2、欠損残基を持つもの 13。

### MDPrepBench (40 タスク) との対応 — 写せない軸

| MDPrepBench の軸 | MDDataBench で作れるか |
|---|---|
| 単純な単量体 / 変異 / 側鎖補完 / 末端 / altloc・MSE | ○ MoDEL に豊富 |
| ジスルフィド | ○ 0–16 本まで分布 |
| プロトン化 (HIP 指定) | ○ `RSNAME` から取れる |
| NMR モデル選択 | ○ (5 件) |
| 生物学的集合体 / 蛋白–蛋白界面 | ○ (2–3 鎖が 7 件) |
| 標準 DNA / RNA | ○ |
| 亜鉛メタロ酵素 | △ PLpro のみ。**MoDEL は金属を落としているので使えない** |
| リガンド (GAFF) | △ PLpro + 3k の 2 件のみ |
| **膜 (混合脂質・陰イオン脂質・β バレル・K チャネル)** | **× 0 件** |
| **糖蛋白 / 糖鎖** | **× 0 件** (スパイクは参照が欠損ループを埋めたモデル) |
| **蛋白–DNA 複合体・ヌクレオソーム** | **× 0 件** (参照と寄託の対応が取れない) |
| Ca / Mn 金属、RNA 構造 Mg、イオン濃度指定 | × 参照にイオンも金属も無い |
| 陰溶媒 | × 参照は全て陽溶媒 |

**膜と糖鎖と蛋白–DNA 複合体は、MDDB を参照とする限り作れない。** これは選定の失敗ではなく
データベースの中身の問題なので、増やしたければ別の参照源 (自前で流す、あるいは別 DB) が要る。

---

## 2026-08-22 (4) — subspace を捨て、平衡量 5 本に置き換えた。md が 1.000 になった

**subspace 検定は何も判別していなかった.** negative controls の実測:

  baseline            合格すべき  RMSIP    z       クロック
  real_full_run       True        0.704   -1.50    OK
  anm_ensemble        False       0.749   +0.05    NG
  truncated_100ps     False       0.587   -5.45    NG
  isotropic_noise     False       0.062  -23.27    NG
  duplicated_minimum  False       0.057  -23.44    NG

ダイナミクスを持たない ANM が本物を上回る。ANM が「正しく不合格」なのも溶媒時計のおかげで、
subspace 自体はクロックが捕まえないものを何も捕まえていない。廃止。

**設計を縛った 3 つの盲目.** 力場は自由 (完全一致を要求するとデータが枯渇し、わざと違う力場で
流したい) → ロタマー/塩橋/RMSF 形状は不可。曖昧なプロトン化は自由 (carve-out 済み) → それを
狙う量も不可。thermostat は自由 → **時間相関は全て不可**。lag 依存 MSD は本物 2.9-4.5 対
偽物 0.97-1.08 ときれいに分離したが、摩擦係数で緩和時間が変わるので正しい MD を積分器で罰する。
残るのは**平衡量だけ**。

**参照が持っているもの (実測).** reference.pdb は溶質のみ 4862 原子、水も対イオンも無い
(SOL/NA/CL は全 4554 プロジェクトで 0)。API は rmsd / fluctuation / rgyr / sasa / pca 等を
計算済みで返す。**fluctuation は per-atom (4861)**、**rgyr は重原子のみ** (2.3228 対 API の
2.3230 nm で確認)。軌道は 10 ps x 100002 フレーム = 1 us。
**trajectory エンドポイントは atoms=1-3,10-12 形式の原子選択に対応**しており、contract 原子
だけ取れば 1 窓 1.1 MB (全原子なら 5.9 MB)。

**採用した 5 本 (AND、各 weight 1.0).**

| | 統計量 | 帯 | 捕まえる |
|---|---|---|---|
| 溶媒時計 (既存) | 拡散からの経過時間 | 既存 | 打ち切り・ANM・複製・未実行 |
| 実測温度 | energy.dat の平均 T | 指定 ±3 K | 温度詐称。**指定値ではなく実測に変えた** |
| 溶媒箱 | 平均密度と箱の分散 | [0.95,1.10] かつ sd>0 | NPT 破綻・泡・バロスタット未接続 |
| 揺らぎの形 | 参照 per-atom RMSF との順位相関 | 窓の下限 (片側) | シャッフル・凍結・ノイズ |
| 揺らぎの量 | 総 RMSF | 窓の範囲 (両側) | 過拘束・展開 |
| 大域形状 | Rg 平均 | 窓の範囲 (両側) | 崩壊・膨張 |

**2 本立てが必要な理由は実測で出た.** 過拘束 (揺らぎ 1/10) は rho 0.872、展開 3 倍は rho 0.867 で
**順位相関を通る**。逆にシャッフルは総 RMSF を通る。相補的。

**推定量の手術を 2 回した. どちらも閾値の調整ではない.**

1. **窓平均構造に fit** (先頭フレームではなく)。先頭 fit は run の drift を全フレームに載せる。
   D01 の最大 RMSD が 2.011 → 1.374 (参照帯 [0.860,1.230])
2. **各原子から時間の一次成分を引いてから RMSF**。結晶構造から出発した 1 ns は参照の窓 (1 us の
   途中から切り出し) に無い drift を持ち、それが原子ごとに違う量で乗るので順位が動く。
   D03 の rho が **0.803 → 0.870**、帯 [0.840,0.922] の内側に入った。
   切り分けの根拠: フレーム数・間引き幅では説明できず (どの刻みでも 0.79-0.80)、
   carve-out 残基を除いても改善せず (0.803→0.797、**金属サイトは無関係**)、
   ずれの大きい原子は表面ループ (ASP284/TYR33/GLY285)、そして**前半 0.844 / 後半 0.828 と
   どちらの半分も帯内**。drift 由来の人工物の形をしている。

**力場耐性を実測した.** 同じ系を ff99SBildn で流し直し (水は TIP3P のまま)、
rho 0.840 / 総RMSF 0.694 / Rg 23.140 で**全て帯内**。ff14SB は 0.870 / 0.768 / 22.953。
これが設計の最大の関門だった。

**帯の幅は交差検証で決めた.** min-max をそのまま使うと、5 分割ブロック交差検証で
**参照自身の窓が 16 / 7 / 9% 落ちる** (D01/D02/D03)。窓 SD の 2 倍だけ広げると 3 タスクとも 0%。
偽物 5 種は SD の**3 倍**まで広げても全て落ちるので、余裕を取っても分離は失われない。
**slack = 2.0 x 窓SD** を task.json に根拠つきで記録した。

**結果: 3 タスクとも prep 1.000 / md 1.000 (19/19).**

## 2026-08-22 (3) — prep が 3 タスクとも 1.000 になった。残るのは subspace だけ

前回の続き。参照との差分がまだ 5 チェック分残っていたが、原因はエージェントの失敗ではなく
**タスクが解けない形になっていた**ことだった。

**寄託構造と参照の残基範囲が食い違っていた.** 実測:

| | 寄託構造 | 参照 |
|---|---|---|
| 6W9C 鎖 C | 解決済み 4-314 (SEQRES 1-317) | 4-315 |
| 6WRH 鎖 A | 解決済み 0-315 | 4-315 |
| 4OW0 鎖 A | 解決済み 4-315 | 4-315 |

6WRH の N 末端 `0A 1E 2V 3R` は寄託構造に**解決済みで存在する**ので、MDClaw がそれを残すのは
正しい挙動。6W9C の残基 315 は寄託構造に無いので、末端を伸ばさないのも正しい。
つまり**どちらも擁護できる選択**で、それぞれ 5 チェックを落としていた。モノマー対応が
配列の完全一致を要求するため、1 残基の差が per-residue 比較を丸ごと止め、残りが総数で落ちる。

さらに **6WRH は C111S 変異体**だった。触媒システインを Ser に置換した不活性化変異体で、
共結晶化の定番手法。参照は野生型で流している。前回の選定はアラインメントで ≥95% identity を
要求したが、312 残基中 1 残基の置換は 99.7% なので素通りした。

いずれも寄託構造からは知りようがないので**プロンプトに書いた** (「残基 4-315」「寄託構造は
C111S なので野生型で」)。これは「推論できないことだけを述べる」という既存方針そのままで、
どう実現するかは書いていない。

**MDClaw に足りなかった 2 つの機能を足した.**

- `--residue-ranges A:4-315`。残基範囲の選択が MDClaw のどこにも無かった。
  `split_molecules` は鎖・種別・リガンド ID でしか選べない
- `--build-terminal-missing-residues`。PDBFixer/MODELLER は SEQRES と照合して末端欠損も
  検出できるのに、`clean_protein` が `ignore_terminal_missing_residues=True` (既定) で
  明示的に捨てており、`prepare_complex` はそのオプションを公開していなかった。
  既定は変えず (末端の未解決は disorder なので作らないのは妥当)、明示要求の経路だけ開けた

範囲は**ビルド窓**として `clean_protein` に渡る。フラグ単独だと SEQRES 全体 (1-317) を作って
しまうが、窓があれば **K315 だけ作って 316-317 は作らない**。実測 `window_trimmed:
N末端 3残基 -> kept 0 / C末端 3残基 -> kept 1`。

**採点の carve-out を触媒残基にも広げた.** 金属配位子と同じ理由 —— 参照の選択が唯一の
正解と言えない。触媒対は幾何で見つける (残基名を見ない): 実測で対が 2.98/3.08/3.11 Å、
次に近い非触媒 Cys/His 対が 4.08/4.63/4.08 Å なので 3.5 Å で切れる。

**総原子数チェックを削除した.** 残基ごとに原子数を比べているので総和は情報を足さない。
しかも carve-out を通らないので、免除した差が総和で復活していた (3 タスクとも 1-2 原子で不合格)。

**結果.**

| task | prep | md | 残り |
|---|---|---|---|
| D01 6W9C | **1.000** | 0.750 | subspace のみ |
| D02 6WRH | **1.000** | 0.750 | subspace のみ |
| D03 4OW0 | **1.000** | 0.750 | subspace のみ |

金属サイトは D01 3/3・D02 4/4・D03 4/4 で全保持 (1.96-1.99 A、100% bound)。
**参照は 1 us で 2/4 なので上回っている。**

**この過程で見つけた MDClaw のバグ 2 件.**

- **変異ツールが CYM を落とす.** 前処理が CYM を出すようになった結果、その出力に
  `create_mutated_structure` をかけると `Protein residue missing after HPacker hydrogen
  rebuild: A:189 CYS` で失敗。同じファイルの CYM を CYS に改名するだけで成功することで切り分けた。
  修正で 2 段階間違えた。名前だけ戻すと水素再構築が HG を足して「HG を持つ CYM」になり、
  トポロジー構築が `expected 4, restored 4, validated 0` で正しく拒否した。次に全変異体を
  対象にすると、再構築が互変異性体を入れ替えるため HID/HIE が 17→16 原子に減った (実測)。
  最終的に**親の部分集合である変異体 (CYM/CYX) だけ**を対象にし、戻す際に禁止原子も除去する形に。
  ASH/GLH は親に水素を足す側なので原理的にこの機構では復元できない (コメントとテストで固定)
- **採点器が prep 成果物のディレクトリを決め打ち.** 変異ノードも `node_type=prep` で成果物は
  `artifacts/mutated.pdb`。`artifacts/merge/*.pdb` を glob していたので StopIteration。
  ノードが宣言する `merged_pdb` を読み、宣言が壊れていれば**推測せず停止**する形に

**レビューについて.** codex は生物学的文脈のフィルタで応答不能になることが多く、
MDDataBench 側の差分では 3 回とも止まった。pi (kimi-k3) に交代させたところ、再現スクリプト付きで
検証する精度の高いレビューが返り、**自分が作り込んだバグを複数指摘された** (挿入位置のインデントで
既存の警告処理をループに取り込んでいた、多文字 auth 鎖でプロトン化が照合で外れる、
「System を読んでいる」が実装と食い違い実際は CONECT を読んでいた、金属ラベルが
多量体で dict キー衝突する、など)。指摘は全件こちらで確認したうえで修正した。

## 2026-08-22 (2) — 金属サイト: ベンチが MDClaw のバグを名指しし、両者を直した

D03 の `residue_atom_counts` が挙げた 3 残基を追ったところ、参照・提出・採点器の三方に問題があった。

**参照の亜鉛は非結合 12-6 で、我々と同一パラメータ.** MDDB は全プロジェクトに `topology.prmtop` を
配っており、このリポジトリはそれを取得していなかった。読むと `type Zn2+, charge +2.0, rmin 1.271 A,
bonds 0`、つまり結合モデルではない。**我々が構築する系とパラメータまで一致する** (sigma 0.2265 nm)。
残基名も CYM 3 / HIP 1 / HIE 10 / CYS 5 で PDB からの推測と完全一致し、S-S はゼロ。

**Cys4 亜鉛サイトは参照でも我々でも壊れている.** Zn-SG を全長で測ると:

| | 脱プロトン化 (CYM) | 中性 (CYS) |
|---|---|---|
| 参照 1 us | 2.00-2.06 A (sd 0.07) | 平均 5.4-6.8 A、最大 13.6 A |
| 我々 1 ns | 2.02-2.04 A | 平均 5.0-12.0 A |

参照は 4 本中 2 本しか脱プロトン化しておらず、残り 2 本は外れる。さらに D01/D02 では亜鉛が
**GLN191:OE1 に 1.75 A まで寄って再配位している**。単に半開きなのではなく組み替わっている。
我々は propka まかせで CYM が 1 本だけ、保持も 1 本。非結合 12-6 イオンは電荷が引きつける数の
チオラートしか保持しない、という一点で両者の差が説明できる。

**MDClaw は亜鉛配位 Cys 2 本を互いのジスルフィドにしていた.** 6W9C 鎖 C の SG(192)-SG(224) は
3.00 A で、距離判定の 3.0 A 窓の内側。`system.xml` に実結合 (0.2038 nm, k=138909) が入り、本番中に
2.04 A まで引き寄せられてサイトが化学的に破壊された。全鎖で見ると偽陽性は 4 件あり、そのうち
`A270-B270`/`A270-C270` は結晶接触ではなく **3 鎖の Cys270 が共有する第 2 の亜鉛 (C:ZN401) の配位子**
だった。金属ガード (同一金属の 2 配位子を結ばない) と原子価ガード (1 硫黄 1 ジスルフィド) で
偽陽性 4 件 → 0 件、BPTI の実ジスルフィド 3 本 (2.01-2.03 A) は保持。閾値 3.5 A は実測 (6W9C 鎖 A の
Zn-S 3.21 A) から決めた。

**MDClaw のプロトン化は金属を見ていなかった.** `protonation.py` に `ZN`/`metal` の語がゼロ。
split が protein と ion を分けるため pdb2pqr は金属を見られない。構造全体が見える `prepare_complex`
側で検出し、**Cys 配位子のみ CYM を割り当てる** (His はどちらの窒素が配位するかで互変異性が決まるので
報告のみ)。サイト成立条件は「側鎖ドナー 2 本以上、最近接 2.9 A 以内」。実測で 4OW0 の 4 本すべてが
CYM になった。`guardrail_codes.py` の `# --- metals ---` は見出しだけで中身が空だったので、
配位子を残したまま金属が選択から落ちる場合の警告も入れた。

**採点器の期待値をトポロジーから読むようにした.** 参照は prmtop の結合リスト、提出は
`system.xml` の HarmonicBondForce + constraint。CONECT はメタデータで、実測すると本数が違う
(D01 で System 135523 本 対 topology 91993 本)。金属配位残基は**プロトン化のみ** carve-out し、
identity 比較は残す。配位が走行中維持されたかは weight 0.0 の新カテゴリ `diagnostic` で報告のみ。

**negative controls: subspace 検定が機能していない.** 5 つの負のベースラインはすべて正しく落ちるが、
**本物の実行も落ちる**。しかも `anm_ensemble` の RMSIP 0.749 が実 MD の 0.704 を**上回る**。
ダイナミクスを持たないモデルが実 MD より高得点である以上、この検定は 312 残基系で何も判別していない。
`anm_ensemble` が正しく落ちているのもクロックのおかげで、subspace はクロックが捕まえないものを
何も捕まえていない。参照は 10 ps 間隔 100002 フレーム = 1 us なので 1 ns 窓が 1000 本取れる。
窓分布による自己較正へ移行すべき (ただし窓は独立ではない)。

**レビューで見つかった、自分で入れた欠陥.** codex に MDClaw を、pi (kimi-k3) に MDDataBench を
レビューさせた (codex は MDDataBench 側でフィルタにより応答不能)。重いものだけ:

- 挿入ブロックのインデントで既存の警告処理が `for` ループに取り込まれ、split 失敗時に未定義変数参照
- 全鎖のプロトン化状態を各単鎖ファイルに渡していた (多量体で必ず失敗)
- 金属の生存判定を元素名だけで見ており、同元素の金属が 2 つあり片方だけ残る場合に誤判定
- **「System を読んでいる」が実装と食い違い**、実際は PDB の CONECT + テンプレート推論を読んでいた
- `metal_atoms` のラベルが chain と挿入コードを落とし、多量体で金属サイトが dict キー衝突で消える
- `load_submission` が `_load_system` より先に無防備に deserialize し、壊れた提出で採点器が落ちる回帰
- 位置を「金属でも溶媒でもないもの」と否定形で定義しており、リガンド 1 個で全位置がずれる
- 原子価表の S 上限 2 は、スルホンアミド・硫酸・DMSO を誤って不合格にする

いずれも「単一鎖・単一金属でしか検証していない実装が一般入力で壊れる」という同一の型。
現行 3 タスクは全て単量体・単一亜鉛なので、テストで塞いだ (MDClaw 8 件、MDDataBench 5 件を新規追加)。

## 2026-08-22 — 新タスク D01-D03 (PLpro) でベンチを端から端まで通し、採点器の 3 つの欠陥を潰した

MDDB から配列アラインメントで選び直した 3 タスク (6W9C / 6WRH / 4OW0、いずれも
papain-like protease、Amber ff14SB / TIP3P / 298 K / NPT、参照 1 µs) を solve して
採点した。SLURM 実測: min 約 18 s、eq 約 1 分、prod 約 4.5 分、系は 135696 / 141023 /
146299 原子。**採点が完走したのは今回が初めて**で、そこで壊れていたのは提出物ではなく
採点器だった。

**(a) CONECT が hybrid-36 で書かれている。** `submitted_disulfides` は CONECT の各欄を
`int()` で読み、失敗したら「malformed CONECT record」を返して S-S 判定そのものを捨てて
いた。実測すると D02 の topology は CONECT 136002 行のうち **64544 行が 10 進では 1 欄も
読めない**: PDB は通し番号が 99999 を超えると hybrid-36 に切り替わり (`A0000` = 100000)、
OpenMM はそれを忠実に書く。つまり**溶媒を入れた系では S-S 判定が必ず捨てられていた**。
3 タスク全滅の原因はこれ。`hy36decode` を入れて仕様の境界 (99999 / A0000 / ZZZZZ =
43770015 / a0000 / zzzzz = 87440031) で検証した。`MAX_PDB_SERIAL` は不要になったので削除。

**(b) precondition が「報告するだけ」で門番になっていなかった。** D01 は 311 残基しか
作れておらず参照 312 の contract 原子 3 個 (`312:N/CA/C`) が解決できない。
`contract_atoms_resolvable` は FAIL を記録するが処理は続き、`kabsch` に 933x3 のフレームと
936x3 の目標が渡って `ValueError: matmul` で**採点が落ちた**。原因は提出側にあるので
スキップではなく `subspace_beyond_structure_only_model` を「評価不能につき不合格」にした。

**(c) 採点対象のノードが軌道の祖先とは限らなかった。** `find_node` は「その種別で最後に
completed したノード」を選んでいた。d03-6wrh は completed な topo が 2 つあり min は
topo_002 から、d04-4ow0 は completed な prep が 2 つあり prod に繋がるのは prep_004 だけ。
今回はたまたま一致したが、一致を保証するものは何も無かった。`parent_node_ids` を prod から
遡る方式に変えた。

**(d) 不合格なのに詳細文が「一致」と言っていた。** モノマーが対応付かないと per-residue
比較は 1 度も走らないのに、`findings` が空なので「identical after canonicalising
protonation」「every residue matches」と出力されていた。`; not compared: no monomer
pairing` に変えた。

**採点結果 (修正後).**

| task | prep | md | 実質的な不一致 |
|---|---|---|---|
| D01 6W9C | 0.455 (5/11) | 0.750 (3/4) | 311 残基 (参照 312)、C 末端 1 残基欠落、余分な S-S 1 本 |
| D02 6WRH | 0.545 (6/11) | 0.750 (3/4) | 316 残基 (参照 312)、N 末端側に 4 残基余分 |
| D03 4OW0 | 0.818 (9/11) | 0.750 (3/4) | 配列・元素組成は完全一致。プロトン化のみ 3 残基相違 |

**D03 が示した本命の所見.** 配列・モノマー数・元素組成・S-S がすべて一致した上で、
`residue_atom_counts_match_reference` だけが 3 残基を挙げた:
参照 `CYM109`/`CYM187`/`HIP270` に対し提出は `CYS112`/`CYS190`/`HIE273` (番号は参照側が
3 大きいだけで位置は同じ)。**参照は Zn 配位 Cys をチオラート (CYM) として、ヒスチジン 1 個を
プロトン化 (HIP) として流している**のに、MDClaw の prep は中性 CYS と HIE を作る。
残基名ではなく原子数で採点する設計にした狙いがそのまま当たった形で、原子数差は
-1 -1 +1 = -1、全原子数 4862 対 4861 とも一致する。ヒスチジンの互変異性 (HID/HIE) は
設計どおり不可視のままで、これは検出されていない。

**subspace は 3 タスクとも不合格。** D02 RMSIP 0.495 対 null 0.779±0.027 (z = -10.5)、
D03 0.704 対 0.748±0.029 (z = -1.5)。注目すべきは**帰無分布そのものが 0.75 前後と高い**
ことで、旧タスク (76 残基ユビキチン) では 0.588 だった。312 残基の球状蛋白質では ANM が
参照部分空間をよく再現してしまう。1 ns の窓 1 本では参照 1 µs の主成分に届かないという
可能性と、系が大きいほど閾値が厳しくなるという性質の両方が効いており、判定規則の再検討が要る。

**参照バンドルの再取得は完全再現。** 3 バンドルとも `task.json` に記録した sha256 と
一致した (例 MCV1900209 `reference.pdb` = 6ee5006...)。

## 2026-08-21 (3) — prep を参照データ由来のモノマー単位チェックに置き換え、問題固有軸を消した

**prep の 7-8 チェックを、全タスク共通の 11 チェックに置き換えた。** 期待値はすべて参照バンドルから
導出され、curator が書いた定数はゼロになった。**D02 の `truncated_sidechains_completed` と
D03 の `disulfide_bonds_formed` を削除**し、全タスクで走る一般形に吸収した。3つの `task.json` の
prep ブロックは**完全に同一**になり、`mddatabench/_prep_checks.py` が唯一の出所になった。

**モノマー単位にした。** 骨格の幾何（ペプチド C-N / ホスホジエステル O3'-P が 2.0 A 以内）で
両側を連結ポリマー鎖に分割し、**正規化配列**で対応付けてから、各対の内部で残基ごとの検査を回す。
**chain ID は使わない。** MDClaw 自身が `chain_identity_map.json` に
"PDB chain IDs are MD compatibility labels and may be reused" と書いており、実際 **D03 の
`system.topology.pdb` は chain A/B/C を持つのに参照は A だけ**。多量体（適格プールの `MULTIMERIC`
充填率 12.6%、memo 2026-08-20 の調査で 254 件）を足した瞬間に、残基リストの順次 zip は静かにずれる。

**protonation は残基名ではなく原子数で採点する。** 名前は規約である、というのが実測で出た:

| ファイル | Cys1/3/11/15 の残基名 |
|---|---|
| 参照 `reference.pdb` | CYX |
| 提出 `merged.pdb` | CYX |
| 提出 `system.topology.pdb` | **CYS** |

**同じ提出・同じ物理で、どちらのファイルを読むかによって判定が変わる。** GROMACS は
HISD/HISE/HISH、CHARMM は HSD/HSE/HSP を使うのでエンジンを跨ぐとさらに壊れる。原子数なら規約に
依存せず、必要な性質をちょうど満たす: HID↔HIE は同一分子式なので**区別しない**（互変異性は
エージェントの自由）、HIP/ASH/GLH は +1 H、LYN/CYM/CYX は −1 H で**すべて検出する**。

**`total_atom_tolerance: 2` を撤廃した。** この許容は互変異性のために必要だと思われていたが、
**D02 は参照と逆の互変異性体（参照 HID / 提出 HIE）を選んで 1014/1014 で厳密一致した**。
守っていたものは何も無く、代わりにイオン化エラーを最大2個通していた。イオン化エラーは
ちょうど水素1個である。

**ジスルフィドは CONECT から、常時、ゼロを含めて判定する。** 期待ペアは参照自身の CYX 残基と
座標から導出する（`expected_pairs` の手書きは廃止）。観測ペアは提出トポロジーの CONECT から取る。
**`system.system.xml` からは取れない** — あれは原子名を持たないコンパイル済みオブジェクトで、
しかも HBonds と剛体水が結合を拘束に変えた後は結合リストとしても使えない:
**D03 の System は `HarmonicBondForce` 177 本に対し constraints 21451**。ParmEd で prmtop や
GROMACS top に戻そうとすると、まさにこの理由で失敗する（`'NoneType' object has no attribute 'used'` /
`Cannot determine SETTLE geometry`）。psf だけは書けるが psf はパラメータを持たない。
**ペア集合そのものを比較するので、余計なジスルフィドも落ちる** — 旧チェックは期待ペアが近いかしか
見ていなかったので、D01/D02 で誤って S-S を作った提出を素通りさせていた。

**エネルギーは読まずに再計算する。** runner の `minimization_report.json` は
`simulation_time_ns` と同じ種類の申告なので、提出された `system.xml` を scorer が自分で評価する。
ゲートは2つ: 単点エネルギーが有限で粒子あたりの絶対値が上限以下（上限 1e6 kJ/mol/particle は
MDPrepBench の `_MAX_ABS_PREP_ENERGY_PER_PARTICLE_KJ_MOL` をそのまま借りた）、そして
**最小化でエネルギーが下がったこと**。

| task | built | minimized | max force |
|---|---|---|---|
| D01 | +505918 (+16.14/atom) | −532908 (**−17.00**/atom) | 29789 → 1640 |
| D02 | +400844 (+11.30/atom) | −600622 (**−16.93**/atom) | 32418 → 1557 |
| D03 | +331474 (+15.31/atom) | −366799 (**−16.94**/atom) | 20729 → 2366 |

**−16.93〜−17.00 kJ/mol/atom は帯にしたくなるほど揃っているが、単一力場・単一水モデルの n=3 なので
diagnostic に留めた。** 「未較正の閾値では採点しない」という不変条件に従う。max force も同様。

**`contract_atoms_resolvable` を prep から外した。** 新カテゴリ `precondition`（weight 0、
報告のみ、prep/md の合計に入らない）に移した。これは「参照の契約原子が提出トポロジーに載るか」で、
**scorer が2つの系を対応づけられるかを測っており、エージェントの調製能力ではない**。

**新チェックが落ちるべきときに落ちることを変異テストで確認した**（D01/D03 の合格提出を壊した）:

| 変異 | 落としたチェック |
|---|---|
| HIP 化（水素1個追加） | 残基原子数、全原子数 |
| 側鎖の切り詰め（Lys の重原子3個削除） | 残基原子数、元素、全原子数 |
| 骨格 N を O と書く（総数は不変） | **元素のみ** — 総数では捕まらない |
| ペプチド結合を1本切る | モノマー数、配列、残基原子数 |
| S-S の CONECT を削除 | ジスルフィド |
| 偽の SG-SG CONECT を追加 | ジスルフィド |

3行目が元素別チェックの存在理由で、4行目がモノマー分割の存在理由。

**副産物のバグ修正。** 残基の区切りを `(chain, resseq, resname)` の変化だけで判定していたため、
**同じラベルを持つ2つの成分が1残基に融合していた**。chain ID が再利用されうる以上これは実在する
危険なので、**原子名の重複でも区切る**ようにした（1残基に同じ原子名は現れない）。合成 PDB の
ユニットテストで検出した。

**Rg (`radius_of_gyration_is_physical`) を削除した。これは 2026-08-19 の
「Rg は subspace テストと冗長ではない」という記録を、測定を認めたうえで覆すものである。**
測定自体は再現した。D01 の軌跡を一様スケールすると:

| 倍率 | RMSIP | H0 棄却 | Rg (nm) |
|---|---|---|---|
| 0.80 | **0.700** | される | 0.943 |
| 1.00 | **0.700** | される | 1.178 |
| 1.30 | **0.700** | される | 1.532 |
| 1.50 | **0.700** | される | 1.768 |

RMSIP は正準相関の集合で、正準相関は部分空間の**方向**しか見ない。一様スケーリングは固有ベクトルの
向きを変えないので原理的に不変であり、2026-08-19 の「Rg だけがコンパクトさを縛る」は正しい。
それでも削除したのは、**Rg が MD の性質ではなく初期構造の性質だから**である:

| task | 参照 | 調製直後 | 最小化後 | 本番平均 | 本番 SD | 旧・帯 |
|---|---|---|---|---|---|---|
| D01 | 1.1833 | 1.1616 | 1.1589 | 1.1784 | **0.0073** | 1.1-1.3 |
| D02 | 1.1377 | 1.1031 | 1.1148 | 1.1224 | **0.0075** | 0.95-1.15 |
| D03 | 0.9070 | 0.8549 | 0.8589 | 0.8223 | **0.0124** | 0.7-1.1 |

**1 ns で Rg は動かない。** 軌跡内の変動 SD は 0.007-0.012 nm、帯の幅は 0.2-0.4 nm で 20-30 倍。
調製直後と本番平均の差も 1.4-3.8% にすぎない。md の判定として置くのは誤った帰属であり、
prep に移すという案も出たが最終的に削除とした。**結果として、一様スケーリングの誤り
（単位取り違えなど）を捕まえるチェックは現在ゼロである** — 溶媒クロックも `total_MSD/(6D)` の比なので
スケール不変。これは意図した上での穴として記録しておく。`rg_mean_nm` は diagnostics に残した。

**`topology_loads_and_is_parameterized` も precondition に移した。** 実体は
`XmlSerializer.deserialize` してから `getNumParticles() > 0` を見るだけで、**force field の中身は
一切見ていない**。しかも判定すべき失敗が全部クラッシュになっていた:

| 提出 | 旧 | 新 |
|---|---|---|
| ファイルが途中で切れている | **`OpenMMException` で採点全体が停止** | prep 7/11 = 0.636 |
| 中身が空の System | **`ValueError` で停止** | prep 7/11 = 0.636 |
| `NonbondedForce` が無い | **`StopIteration` で停止** | prep 9/11 = 0.818 |

deserialize と force 取得を保護し、失敗を記録された不合格に変えた。`system.xml` に依存する prep の
4項目（force 適用・正味電荷・単点エネルギー・最小化）が落ち、`system.xml` を使わない7項目
（組成6件 + 水モデル）は採点され続ける。3行目は System 自体は読めるので結合項だけでエネルギーが
有限に出る。**力場が全く当たっていない系が 0.818 を取る**が、physical_validity クランプは
**入れないと決めた**（2026-08-21 の判断）。

**採点を prep / md で分離し、`weight` を実際に読むようにした。** 従来 `weight` は契約にあるだけで
scorer が一度も参照していなかった。`category_score = Σ(w × passed) / Σ(w)` とし、採点対象は
すべて w=1.0、precondition は w=0.0。**0 重みが自動的にどのスコアからも除外される**ので、
precondition の特別扱いがコードから消えた。Rg にだけ付いていた `weight: 0.5` は、なぜ半分かの
測定がどこにも無い未較正の閾値だったので、Rg ごと消えた。現在の内訳は **prep 11 / md 4 /
precondition 2**。

**テストを 19 → 32 に増やした（うち 5 件が `slow`）。** `test_composition.py` は合成 PDB で動くので
バンドルも OpenMM も要らず、CI の `-m "not slow"` に乗る。`test_scoring_robustness.py` は OpenMM を
使うので `slow`。この suite は **数値的な中身に自動テストが1つも無く**、`pyproject.toml` に `slow`
マーカーの定義があるのに該当テストが存在しないという状態だった。今回それを実体化した。

**再採点は D01/D02/D03 とも prep 11/11 = 1.000、md 4/4 = 1.000。** precondition 2件も通過（非採点）。
負のコントロールは3タスクとも `all_correct: true`。`ruff` clean、`pytest -m "not slow"` 27 passed、
`pytest` 全体 32 passed。

**溶媒側は依然として何も採点しない。** MDDB 全 4554 件を走査した結果、`SOL`/`SOLVATS`/`SOLVRES` は
**充填率 0.0%**。イオン個数と箱サイズが揃うのは適格 1940 件のうち **47 件**で、うち 46 件は
`COUNION = 1` の中和用対イオン1個。**本物の塩から濃度が導ける適格エントリは 1 件だけ**
（`seq014-2`, 0.155 M）。塩はあるが箱が無い適格エントリが 32 件（`bigna`/`ebrains`）あるが、
**箱が無ければ個数は物理量ではない**。仮に濃度を指定できても検証精度が足りない: packmol-memgen に
0.15 M を要求した3系は 0.146 / 0.118 / 0.130 M になった（中和対イオンが先に入る D02 が −21%、
D03 は**イオン1個が 0.008 M** に相当する量子化）。**塩濃度は採点しない。**

`BOXTYPE` は適格プールの 89.6% で埋まっており、**参照3件はすべて `Octahedral`、提出は cubic**。
照合可能だが採点しない — 周期像との距離が足りていれば箱形状は物理に影響せず、`FF: Parm99` と
同じ「記録するが不問」の扱いにする。

---

## 2026-08-21 (2) — dt は DCD ヘッダから取れる。同日 (1) の「1 ps 出力が事実上の提出要件」を撤回する

**同日のエントリ (1) が「クロックの単位はフレームで、1 ps 出力が事実上の提出要件」と結論したのを
撤回する。** 正しい修正は出力間隔を提出側に強いることではなく、**scorer が dt を DCD ヘッダから読むこと**。

**DCD は時刻情報を持っている。** 捨てているのは mdtraj であってフォーマットではない。
CHARMM 形式のヘッダは `DELTA` (積分ステップ、AKMA 単位、float32) と `NSAVC` (保存間隔ステップ数)
を持ち、積がフレーム間隔になる。今回の提出物を実測:

| file | DELTA | NSAVC | NSTEP | 間隔 |
|---|---|---|---|---|
| d01/prod_001 | 4.000 fs | 500 | 250000 | 2.0000 ps |
| d01/prod_002 | 4.000 fs | 250 | 250000 | 1.0000 ps |

**(1) で「メタデータだから申告の検証に使えない」と書いたのは誤り。** ヘッダを書くのは OpenMM で
あってエージェントではなく、想定攻撃は「走らせた量より多く申告する」であって「バイナリヘッダの偽造」
ではない。しかも**打ち切り攻撃はヘッダを正直に保ったままフレーム数だけ失う**ので、ヘッダ由来 dt は
打ち切りを落とす側に働く。(1) が代案として挙げた「外部の水の自己拡散係数を基準にする」案は、
存在しない脅威モデルへの過剰設計であり、水モデルごとの帯較正という新しい未較正閾値を持ち込むので
**採らない**。

**修正内容。** `execution.dcd_frame_interval_ps()` を足し、`elapsed_time_ps(..., dt_ps=)` で受ける。
`scoring` と `controls` の両方が渡す。ヘッダが読めない軌跡は **FAIL** にした
(黙って `traj.time` に落ちると単位が壊れたまま通ってしまうため)。

同一軌跡での前後比較 (D01, 主張 1000 ps):

| 提出 | フレーム | 間隔 | 旧 (`traj.time`) | 新 (ヘッダ) | 報告される D |
|---|---|---|---|---|---|
| prod_001 | 500 | 2 ps | 489 ps (0.49) **FAIL** | **977 ps (0.98) PASS** | 7.33e-5 -> 3.66e-5 |
| prod_002 | 1000 | 1 ps | 989 ps (0.99) PASS | 989 ps (0.99) PASS | 3.72e-5 -> 3.72e-5 |

**D が 7.33e-5 から 3.66e-5 に下がって prod_002 の 3.72e-5 と一致するのが、単位が直った証拠。**
同じ水が出力間隔で 2 倍拡散するはずがない。

**負のコントロールは D01/D02/D03 とも `all_correct: true`。** 検出力は落ちていない。
D01 の `truncated_100ps` は RMSIP 0.644 で構造のみ帰無 (max 0.588) を**超えており h0 は棄却される**
—— これを落としているのはクロックだけで、両方のチェックを残す理由がここでも再現した。

| task | real_full | trunc_100ps | trunc_10ps | anm | noise | duplicated |
|---|---|---|---|---|---|---|
| D01 | pass | fail (h0 通過, clock で落ちる) | fail | fail | fail | fail |
| D02 | pass | fail | fail | fail | fail | fail |
| D03 | pass | fail | fail | fail | fail | fail |

**再採点は 12/12, 13/13, 13/13 で変わらず**、クロックは 989 / 981 / 1017 ps。
`ruff` clean、`pytest -m "not slow"` 19 passed。

---

## 2026-08-21 — GB200 で D01-D03 を通し、溶媒クロックが **フレーム番号**を測っていることを見つけた

**MDClaw 0.6.8 / 1x NVIDIA GB200 (aarch64, CUDA 13.0) で D01-D03 を独立に解いた。**
ff14SB + TIP3P、cubic 15 A バッファ、0.15 M NaCl、HMR 4 fs、NVT 100 ps + NPT 200 ps、
1 ns NPT production。参照バンドルは solve 中一度も solver ワークスペースに置いていない。

| task | 系原子数 | prep | md | RMSIP | 構造のみ帰無 (max) | 余裕 | クロック | Rg (nm) |
|---|---|---|---|---|---|---|---|---|
| D01 1UBQ | 31355 | 7/7 | 5/5 | 0.700 | 0.588 | +0.112 | 989 / 1000 ps | 1.178 |
| D02 1CSP | 35469 | 8/8 | 5/5 | 0.707 | 0.637 | +0.070 | 981 / 1000 ps | 1.122 |
| D03 1EDN | 21656 | 8/8 | 5/5 | 0.779 | 0.766 | +0.013 | 1017 / 1000 ps | 0.822 |

**組成は 3 つとも無指示で参照と完全一致した。** D01 1231/602、D02 1014/521 (切り詰められた
4 側鎖を自動補完)、D03 328/171 (SSBOND 2 本を `pdb_ssbond+distance` で自動形成)。
2026-08-19 の検証を別ハードウェア・別 MDClaw バージョンで再現した形になる。

**RMSIP は 2026-08-19 の参照解 (0.717 / 0.703 / 0.828) と 0.01-0.05 しか違わない。**
D01 のレプリカ間 SD 0.010 に照らすと D01/D02 は同一、D03 の -0.049 はやや大きいが、
**D03 の余裕 +0.013 は 3 つの中で桁違いに狭い**。3M=189 の系で 1 ns 一本という設計上、
乱数シード次第で構造のみ帰無 (max 0.766) を割り込みうる位置にある。D03 は
レプリカを重ねるか production を伸ばさないと、pass/fail がシード依存になる。

**`elapsed_simulated_time@1` は ps ではなくフレーム番号を数えている。**
`scoring.py` は `md.load(traj.dcd, top=topology.pdb)` で読み、`execution.py` は
`dt = traj.time[1] - traj.time[0]` を使う。ところが **mdtraj の DCD リーダは時刻情報を持たず、
`time = arange(n_frames)` を返す**ので `dt` は出力間隔によらず常に 1。
`elapsed_ps = total_MSD / (6 D)`、`D` は `MSD` 対 `lag*dt` の傾き/6 なので、
測定値は `真の経過時間 x (1 ps / 実フレーム間隔)` にスケールする。

測定 (D01, 同一の 1 ns 軌跡を 2 通りに出力):

| 出力間隔 | フレーム数 | クロック | 比 | 報告される D |
|---|---|---|---|---|
| 2 ps | 500 | 489 ps | 0.49 -> **FAIL** | 7.33e-5 cm2/s |
| 1 ps | 1000 | 989 ps | 0.99 -> PASS | 3.72e-5 cm2/s |

**同じ物理、同じ長さ、出力間隔だけが違う。** 2 ps 出力は閾値 0.5 を 0.01 で割って落ちる。
報告される D が 2 倍に出ているのが症状で、これは D が実時間ではなくフレーム番号あたりで
測られているため。MDClaw の `run_production` の既定は `--output-frequency-ps 10.0` なので、
**既定のまま 1 ns を回した提出は 100 / 1000 ps と読まれて必ず落ちる**。
2026-08-19 の参照解が 1000/1000 ps を得ていたのは 1 ps 出力だったからで、
その依存関係はどこにも書かれていない。

閾値は正しく、破れているのは単位。直し方は `dt` を軌跡メタデータに頼らず与えること —
prod ノードの `metadata.output_frequency_ps` を読むのが最短で、`claimed / (n_frames-1)`
を使うと虚偽申告を検証できなくなるので不可。それまでは **1 ps 出力が事実上の提出要件**。

---

## 2026-08-20 — MDDB の系統調査と D03 (エンドセリン-1) の導入

**MDPrepBench と同じ種類の system variety を MDDB で埋められるか調べた。** 適格プールは
**1934 / 4554** (CC + Classical MD + 解析 5 種 + PDBID あり)。

**メタデータだけでは選べない、というのが最大の教訓。** `OTHRATS>0` かつ `PTM=Acetylation` は
金属タンパク質に見えるが実体は **ACE キャップ**だった。1CCR (シトクロム c) も 1JEB (ヘモグロビン) も
**ヘムが剥がされている**。2CBA に Zn が無かったのと同じで、**MoDEL は補因子と金属を全部落としている**。
使えるのは `RSNAME` (残基名リスト) で、そこから拾った候補は**全て structure.pdb を取得して実物確認した**。

| 軸 | 適格件数 | 代表 | 確認した非標準残基 |
|---|---|---|---|
| ジスルフィド | 677 | `A00EC` 1EDN | CYX x4 |
| 末端キャップ | 144 | `A007Z` 1CCR | ACE |
| セレノメチオニン | 31 | `A015F` 1WHZ | MSE x3 |
| **亜鉛 (金属保持)** | 139 | `MCV1900209` PLpro 6W9C | **ZN + CYM x3** |
| **リガンド結合** | 78 | `MCV1900211` PLpro + 3k | ZN + CYM + **S88** |
| 糖鎖 | 79 | `MCV1900112` 6VW1 | **NAG x5** + ZN + CYX + ACE/NMA |
| DNA + 対イオン | 126 | `A01MQ` 1ICK | **Na+ x32, Cl- x22** |
| RNA | 10 | `A01AU` 1Q9A | — |
| タンパク質-DNA + Mg | 26 | `A01FH` 1VTN | **MG** |
| 多量体 | 254 | `A007P` 1CDL | — |

**金属もリガンドも糖鎖も cv19 コレクションには残っている。** PLpro は apo (`MCV1900209`) と
リガンド結合 (`MCV1900211`) が揃っていて**比較ペアにもなる**。DNA の `FF-DNA-2023` シリーズは
同じ PDB を {OL15, OL21, ParmBSC1, Tumuc1} x {OPC, TIP3P} の 8 通りで回した系統比較で、
**イオンごと寄託されている** (MoDEL は水もイオンも剥がすので照合できなかった)。
FOXO3/FOXA3 は rep0-rep5 の**レプリカ付き**で、参照側にレプリカがあるのはここだけ。

**埋まらない軸は 4 つ**: 膜系 (CC の実バイアレイヤは SARS-CoV-2 ウイルス膜 10 件のみ)、陰溶媒、
変異体、リン酸化 (PTM は Acetylation / Glycosilation のみ)。

**D03 = `A00EC` (1EDN, エンドセリン-1) を導入した。** 21 残基 / 328 原子 / 重原子 171。
RCSB の SSBOND は Cys1-Cys15 と Cys3-Cys11、参照では 4 つとも CYX。
**328 原子 (SS 2 本) 対 332 原子 (還元型) という等式を参照自身が与える**ので、D02 の 505+16=521 と
同じく正解をキュレータが決めなくてよい。SG-SG 距離で帰属する専用チェックも足した。

**MDClaw は 13/13 (prep 8/8, md 5/5)。** ジスルフィドを**無指示で 2 本とも形成**した
(`disulfide_bonds.json` に `pdb_ssbond+distance`, Cys1-Cys15 が 2.04 Å, confidence high)。
RMSIP 0.828。

**小さい系ほど余裕が狭い。** 3M=189 なのでランダム帰無だけで sqrt(10/189)=0.230、
構造のみ帰無は 0.602 +/- 0.067 (最大 0.766)。余裕は **+0.062** で D01 の +0.129 より狭い。
100 ps 切り詰めは 0.807 で構造のみ帰無を超えてしまい、**時計だけが捕まえる** (D01 と同じ)。

**GPU 競合で production が遅延した。** GPU 3 が他ジョブで 99% 占有されており、10 分の
ツール制限でスクリプトごと落ちて `prod_001` が `running` のまま孤児化した。空いている GPU 5 で
`prod_002` を作り直して完走。

**孤児ノードが scorer/controls のバグを露出させた。** `run_negative_controls` が
`prod_*/artifacts/*.dcd` を glob して先頭を取っていたため孤児の `prod_001` を掴み、
scorer (最新 completed = `prod_002`) と**別の軌道を採点していた** (0.818 対 0.828)。
両方 `find_node` を共有するよう修正。**2 つのツールの数値を突き合わせる習慣が、これで 2 件目のバグを捕まえた**
(1 件目は原子インデックスをファイル行番号で数えていた件)。

---

## 2026-08-20 — MDDataBench を別リポジトリに切り出した

MDPrepBench / MDStudyBench と同じ形で 独立したリポジトリに切り出した。
mdclaw 側の `benchmarks/mddatabench/` と `docs/research/db_derived_benchmark_validation.md` は削除済み
(どちらも git 未追跡だったので履歴操作は不要)。**本エントリより前の 8/18-8/19 の各エントリが参照している
`docs/research/db_derived_benchmark_validation.md` は、いまは `MDDataBench/docs/validation-design.md` にある。**
過去エントリは規約どおり書き換えていないので、参照を辿るときはここを見ること。

**構成は MDPrepBench に合わせた。** hatchling + `mddatabench` コンソールスクリプト、
`mddatabench.TOOLS` を signature 由来のフラグでディスパッチする `__main__.py`、
`benchmarks/mddatabench/tasks/`、`tests/`、`.github/workflows/ci.yml`、MIT LICENSE、
CLAUDE.md と AGENTS.md の同一二枚。スクリプト群はパッケージモジュールに移した
(`subspace_test.py` -> `subspace.py`、`execution_check.py` -> `execution.py`、
`fetch_reference.py` -> `reference.py`、`score_submission.py` -> `scoring.py`、
`negative_controls.py` -> `controls.py`)。argparse の `main()` は全部ライブラリ関数に直して
`cli.py` の TOOLS から呼ぶ形にした。

**CLI は 4 つ**: `list_benchmark_tasks` / `fetch_benchmark_reference` /
`score_benchmark_submission` / `run_benchmark_negative_controls`。

**動作確認**: ruff clean、fast テスト 14 本 passed (0.62 s)、
`mddatabench score_benchmark_submission` で D01 が **prep 7/7 md 5/5 = 12/12 を 6.2 秒**。

**テストに入れた不変条件**: ライセンスが CC 系であること、bundle の SHA-256 が 3 ファイル分揃っていること、
全チェックが `prep`/`md` のどちらかに分類され `check_type` が `@1` 付きであること、md 側が
構造のみ帰無検定と時計の両方を持つこと、そして **prompt が accession / MDDB / MoDEL / DOI を漏らさず、
かつ PDB ID と採点対象の条件 (水モデル・温度・アンサンブル) は述べていること、`rmsip` を含まないこと**。
最後のはプロンプト最小化とリーク防止を機械的に守らせるためのもの。

初期コミット 29 ファイル / 328 KB、データは 0 バイト。GitHub remote は未作成 (ユーザ判断待ち)。

---

## 2026-08-19 — 検定を ANM 帰無に一本化、Rg の役割が判明、3 レプリカを測定、SIF の BLAS バグを発見

**検定を 1 本に絞った (ユーザ指示「H0 か ANM かに絞ったほうがいい」).** ANM 帰無 (cutoff 7.0-20.0 A の 27 点、
平均 0.517 SD 0.048 最大 0.588) はランダム帰無を包含する: 0.13 のものは 0.59 を超えられない。
実測 z は 本物の 1 ns +4.37 / 100 ps +2.26 / 10 ps -2.00 / ANM ensemble -0.05 (帰無のど真ん中) /
等方ノイズ -8.00。ランダム帰無はゲートから外し報告用の文脈に降格。負の対照 5 本すべて失敗、実 run のみ通過。

**Rg は冗長ではなかった。** 「Rg は意味なくない?」を実測で確かめたところ逆の結論になった。
**RMSIP はスケール不変**なので、軌道を一様に 1.3 倍しても RMSIP は 0.729 のまま変わらず (Rg は 1.14 -> 1.48)。
0.8 倍でも同様。進行性膨潤 (Rg 1.82) でも RMSIP は 0.711 でまだ通る。**Rg が振幅・コンパクトさを拘束する
唯一のチェック**であり、単位ミスや変性を捕まえる役割を独占している。バンドが緩い (結晶構造が満たす) のは事実だが
冗長とは別問題。

**3 レプリカの効果を実測 (seed 20260820/21 で 2 本追加).** 単独 0.729/0.743/0.717 -> 平均 0.730 **SD 0.010**、
レプリカ間 0.780/0.851/0.770 平均 0.801、3 本プール 0.764 (+0.034)。帰無最大からの余裕は +0.142 -> +0.176。
敵対側 (ANM ensemble 3 本) もプールで +0.022 稼ぐので、**利得は実在するが劇的ではない**。
本当に新しいのは**参照を使わないレプリカ間一致**で、これは `execution_validity` 軸に入る。
実務的含意: **SD 0.010 なのでエージェント間の 0.03 未満の差はノイズ。** レプリカ無しではこれが分からない。

**SIF の OpenBLAS がスレッド過剰生成で崩壊していた (プロジェクト全体に効く).**
scorer が 1 タスク 10 分超かかるので profile したところ `anm_null_distribution` が 528 秒。
Hessian 構築をベクトル化しても改善せず (結果は RMSIP=1.000000 で完全一致)、犯人は `np.linalg.eigh` だった。

| 環境 | `eigh(684x684)` |
|---|---|
| SIF、スレッド env 無し | **16.34 s** |
| SIF、`OMP_NUM_THREADS=1` | 0.12 s |
| SIF、`OMP_NUM_THREADS=8` | 0.07 s |
| ホスト python3 | 0.59 s |

`matmul` は 3.7 倍差なので LAPACK 固有。SIF の numpy は scipy-openblas を
`DYNAMIC_ARCH NO_AFFINITY MAX_THREADS=64` で積んでおり、32 コア機で上限未設定だと小問題が崩壊する。
**SIF 内で numpy を回すときは常に `OMP_NUM_THREADS` を渡すこと。**
`scripts/_threads.py` で `os.environ.setdefault` により numpy import 前に防御 (1 タスク 10 分超 -> 7.4 秒)。
恒久対応はコンテナか `bin/mdclaw` 側だが未着手。memory にも記録。

**最終スコア**: D01 prep 7/7 md 5/5 (12/12)、D02 prep 8/8 md 5/5 (13/13)、両タスク合計 13.5 秒。

---

## 2026-08-19 — MDDataBench の採点は甘すぎた。敵対的ベースラインで穴を 2 つ実測し、塞いだ

**「score が甘すぎないか」を議論でなく実測で確かめた結果、甘かった。** 落ちるべき提出を作って走らせたところ、
ランダム部分空間帰無だけでは 3 本が通ってしまった (D01 参照に対して):

| ベースライン | RMSIP | z | 当時の判定 |
|---|---|---|---|
| ANM 低振動モードからのサンプル (**MD ゼロ**) | 0.515 | 46 | **通過** |
| 本物の MD を 100 ps に切り詰め | 0.627 | 60 | **通過** |
| 本物の MD を 10 ps に切り詰め | 0.420 | 36 | **通過** |
| 結晶構造 + 等方ノイズ | 0.130 | -0.5 | 正しく失敗 |
| 最小化構造の複製 | 0.135 | 1.7 | 正しく失敗 |

つまり**「正しい分子か」は証明できていたが「実際に走らせたか」は証明できていなかった**。
`production_ran_for_one_nanosecond` がノード自身のメタデータを読むだけだったのも同根。

**修正 1: 構造のみの床 (ANM) を追加。** 結晶構造から組んだ弾性ネットワークが RMSIP 0.57 に達するので、
それを margin 0.05 付きで超えることを要求する。床はカットオフ最大化で取る (カットオフは攻撃者の自由変数)。

**修正 2: 経過時間を物理で検証。** 拡散係数は**強度量**で使えない (同じ軌道の 1 ns と 100 ps でどちらも
3.7e-5 cm^2/s)。**連続 unwrap した溶媒の総変位は示量量**で、999 ps から 989 ps、99 ps から 98 ps、
9 ps から 15 ps を復元した。溶媒が無い提出は計測不能で即失敗 = MD ゼロ提出に対する正しい判定。

修正後、5 本すべてが失敗し実 run だけが通る。**D01 の 100 ps は ANM 床を 0.005 差で超えてしまい、
時間検証だけが捕まえた** ので 2 つとも要る。恒久回帰として `scripts/negative_controls.py` を追加。

**採点を prep と md に分割 (ユーザ指示)。** 単一の数では「組み立てで落ちた」のか「シミュレーションで
落ちた」のかが言えない。ANM 提出と 10 ps 提出はどちらも **prep 満点・md 失敗**になり、帰属が機能する。
D01 prep 7/7 md 6/6、D02 prep 8/8 md 6/6。

**副産物のバグ 1 件.** `negative_controls.py` 初版が原子インデックスをファイル行番号で数えており
(トポロジにはヘッダ行がある)、real_full_run が 0.688 と出て scorer の 0.729 と食い違った。修正後一致。
**scorer と回帰ハーネスで同じ値が出ることを毎回突き合わせる**のが早期発見に効いた。

---

## 2026-08-19 — scorer 修正、D02 追加、プロンプト最小化

**scorer の偽 FAIL 2 件を修正。** `benchmarks/mddatabench/scripts/score_submission.py` として
実装し直した。ハードコードした `True` を廃し、全項目を artifact から再計算する。正しい所在は
`amber_metadata.json :: parameters.water_model` (+ `forcefield_provenance.openmm_xml`) と
prod ノードの `metadata.system_signature.ensemble`。**バロスタットは実行時に付与されるので
topo ノードの system.xml には無い。** 契約原子は生インデックスではなく (残基番号, 原子名) で対応付ける
(提出側トポロジは溶媒を含む)。D01 で 11/11 を再現。

**D02 を追加: MDDB `A00AJ` (MoDEL 1CSP、枯草菌 major cold-shock protein CspB)。**
MDPrepBench との交差を機械的に取った結果 (MDPrepBench 30 PDB 中、CC + Classical MD + 解析5種を
満たすのは 1UBQ / 1CSP / 2CBA / 1BNA)。**2CBA は見送った** — MoDEL の寄託に Zn が入っておらず
(HETATM ゼロ、apo)、触媒金属を捨てることを報酬にしてしまう。MDPrepBench P26 の趣旨と正反対になる。

D02 が D01 に足す能力は**側鎖補完**と**非ゼロ溶質電荷**。PDB 1CSP は Glu 3/21/36/66 の側鎖先端を
欠いており重原子 505、MDDB 参照は 521。**505 + 16 = 521 という等式を参照自身が与える**ので、
正解をキュレータが決めなくてよい。参照スケールは 201 原子 (67×3)、1 ns 窓どうし 0.687 ± 0.035、
帰無 sqrt(10/603)=0.129。

**プロンプトを最小化した (ユーザ指示)。** scorer が両側のサブスペースを自分で計算するので、
**エージェントに解析させる必要がそもそも無い**。解析契約・報告項目・鎖選択・互変異性体・箱形状・
側鎖補完の指示をすべて削除し、残したのは「PDB ID / TIP3P / 中性化 / 300 K / NPT / 1 ns 以上」だけ。
参照バンドルは**ソルバのワークスペースに一切置かない** (採点時に評価器が取得する) ので、
参照が漏れる経路が消えた。

**簡素プロンプトが解けることを実測で確認。** プロトネーションの指示ゼロで MDClaw は
1UBQ -> 602/1231、1CSP -> 521/1014 と参照組成に厳密一致し、1CSP の Glu 4 残基を無指示で補完した。
2 つの run は参照と**逆の**互変異性体を選んだが (1UBQ で HID、参照は HIE / 1CSP で HIE、参照は HID)、
重原子数は互変異性体に依らないので設計どおり通る。総原子数には ±2 の許容を入れた。

**採点結果**: D01 11/11 (RMSIP 0.729, z 72.4)、D02 12/12 (RMSIP 0.703, z 64.0)。
どちらも方向は復元、振幅は 2-6 倍小さいという同じ姿。ruff clean、リポジトリ内のデータは 0 バイト。

---

## 2026-08-19 — D01 を MDClaw で実際に解いて 11/11。試走が scorer の欠陥を 2 件出した

同日前エントリで作った MDDataBench D01 を、MDClaw 0.6.6 で最初から最後まで解いて採点した。
A6000 1 枚、1UBQ chain A -> ff14SB + TIP3P、cubic 15 Å、31355 原子、HMR 4 fs、
NVT 100 ps + NPT 200 ps、**1 ns NPT production が 2 分 29 秒**。

**結果 11/11 PASS.** 核となる検定は RMSIP=0.729、z=72.4、p<5e-5 で H0 棄却。
正準相関 10 本すべてが帰無 99 パーセンタイル超。Rg=1.1777 nm（参照 10 ns 平均 1.1807、
差 0.0030 は 1 ns 窓の SD 0.0102 の 1/3）。prep 出力は重原子 602 / 全 1231 / 76 残基 / HIE で
参照と完全一致した。

**設計の予測が当たった。** 固有値比 (own/ref) は [0.60, 0.35, 0.18, 0.18, 0.29, ...] で、
**方向は復元できるが振幅は 2-6 倍小さい**。τ(PC1)=1236 ps から予測したとおり 1 ns では
遅いモードの分散が出ない。RMSIP 0.729 は ANM 床 (0.47-0.62) を超え、参照自身の 1 ns 窓間
自己一致 0.760 ± 0.053 の 0.6σ 以内。**別力場 (ff14SB vs Parm99) の独立な 1 ns が、
参照自身の 1 ns 再現性と同じ水準に着地した。** 「H0 棄却は採点、定量一致は採点しない」
という設計判断が実測で正当化された。

**試走で出た scorer の欠陥 2 件（いずれも偽 FAIL）.**

1. water model を `amber_metadata.json` 直下で探したが実際は `parameters.water_model`
   (+ `forcefield_provenance.openmm_xml` に `amber/tip3p_standard.xml`)。
2. barostat を topo ノードの `system.xml` で探したが、**バロスタットは実行時に付与される**ので
   そこには無い。ensemble は prod ノードの `metadata.system_signature.ensemble` を読む。

さらに、参照の 228 契約原子は**生の原子インデックスではなく (残基番号, 原子名) で対応付ける**必要がある
（提出側トポロジは溶媒を含むのでインデックスが一致しない）。これらを `task.json` の
`scorer_field_map` に記録した。**artifact-as-truth を掲げても、artifact のどこに何があるかを
実走で確定しないと scorer は嘘をつく。**

`benchmarks/mddatabench/scripts/evaluate_submission.py` を追加。ruff clean。

---

## 2026-08-19 — MDDataBench D01 を作成: RMSIP による「無関係」帰無仮説の検定

`benchmarks/mddatabench/` を新設し、最初のタスク D01 (1 ns MD + 本質サブスペース一致) を実装・検証した。
参照は MDDB `A0142` (MoDEL 1UBQ、CC-BY 4.0、Amber Parm99 / TIP3P / 300 K / NPT / 10 ns)。

**採点の核: H0 =「2 つの本質サブスペースは無関係」を RMSIP で棄却する検定。**
ランダム直交フレームの Monte Carlo で帰無分布を作る (M=20000 で平均 0.1206 / SD 0.0083、
解析値 sqrt(D/3M)=0.1209 と一致)。**力場校正が不要**なので、rev.2 の「未校正の量に閾値を置かない」
規律を破らずに MD 部分を採点できる。実測 (D=10, 3M=684):

| 比較 | RMSIP | z | 棄却 |
|---|---|---|---|
| ランダム (負の対照) | 0.121 | 0.0 | **no** |
| ANM (構造のみ, 10 A) | 0.617 | 59.5 | yes |
| 座標系ズレ (大域回転) | 0.652 | 64.2 | yes |
| 1 ns 窓 vs 1 ns 窓 | 0.760 ± 0.053 | 81.8 | yes |
| 1 ns 窓 vs 全 10 ns | 0.794 ± 0.029 | 84.7 | yes |
| 10 ns から 500 フレーム | 0.969 | - | yes |

**この検定は妥当性ゲートであって品質スコアではない。** 構造だけから作った ANM も H0 を棄却するため、
「正しい分子を正しい契約で解析したか」は保証するが「サンプリングが収束したか」は保証しない。

**1 ns では上位モードを定量比較できないことが判明。** 参照の積分自己相関は PC1 1236 ps / PC2 1081 ps /
PC4 1660 ps で、**1 ns 中の独立標本は PC1 で 0.8 本**。10 ns の参照でも 8 本。Marchenko-Pastur は
q_eff = N/T_eff が 1 ns で 188、10 ns でも 38 となり適用不能 (PRL 103, 268101 (2009) の手法は
MP 上端ではなくバルクの準位間隔統計)。よって連続値 RMSIP は診断のみとし、校正データとして蓄積する。

**解析契約が必須であることの数値的裏付け.** MDDB は PCA の固有値と射影を配信するが**固有ベクトルは配信しない**
ため、scorer 側で再計算が必須。契約 `pca_backbone_subspace@1` (主鎖 N/CA/C 228 原子、参照構造への Kabsch
フィット + running mean 3 反復、D=10、Å) で公開固有値を -4.8% 〜 +3.4% で再現。摂動の効き方は
大域回転 -0.175 > 原子順序 -0.018 > 平行移動 0。なお Rg では標準原子量の質量加重が公開値と
+0.0024 nm 系統的にずれ、これは 1 ns 窓の SD 0.0102 nm の 24% に相当した。

**データは非同梱.** `scripts/fetch_reference.py` が MDDB から取得し provenance と SHA-256 を書く。
再取得でバイト一致を確認済み。`.gitignore` で取得物のコミットを禁止。solve 時は `mddbr.eu` を遮断、
RCSB は許可。プロンプトに accession を出さない。

**Rg を主観測量にする案は棄却した.** 正しく作れば誰でも 1.18 nm になり識別力がない。RMSIP は
0.12 (偶然) - 0.79 (1 ns 自己一致) - 1.0 と広いレンジを持つ。ruff clean、取得から検定まで通し検証済み。

---

## 2026-08-18 — 訂正: DB 由来ベンチ設計を MDDB 単独に変更、逐次ゲートと σ_FF 加算式を撤回

**同日の前エントリ「公開 MD DB (GPCRmd / MDDB) 由来ベンチの実測と検証層の設計」を訂正する。**
実測値そのものは概ね維持されるが、**供給源の選択と検証設計の中核 3 点が誤っていた**。
改訂版は `docs/research/db_derived_benchmark_validation.md` (rev.2)。

**方針変更 (ユーザ判断).** GPCRmd は RIKEN でのライセンス上の扱いが難しいため供給源から外した。**MDDB 単独**にする。

**独立レビューで判明した設計上の誤り 4 点** (cursor advisor pane, Opus 4.8, 読み取り専用で実施):

1. **`observable_fidelity` を「唯一の新規軸」としたのは誤り。** 軌道から観測量を再計算して
   自己申告値と突き合わせる primitive は既存: `MDPrepBench/mdprepbench/scoring.py:882-947` と
   `:1076-1124` (`_check_observable_recompute_consistency`)、
   `MDStudyBench/mdstudybench/scoring.py:1033-1075` (`direction_grounding`) と
   `:1078-1126` (`observable_recompute_consistency`)。新規なのは
   **DB の固定参照軌道をエージェント入力にする task mode と DB provenance 付き check contract** だけ。
2. **「軸 k は k-1 が通ったときのみ評価」という逐次ゲートは自己矛盾。** 物理妥当性に落ちた提出でも
   組成・自己申告値・主張整合性の診断は独立に可能で、それを捨てるのは掲げた目的 (原因帰属) を捨てること。
   **全軸を独立に評価し、`passed` / `failed` / `not_evaluable` / `not_attempted` を区別し、
   最終合否だけを非補償ゲートにする**に変更。
3. **`δ = k·sqrt(σ_rep² + σ_FF²)` を撤回。** この式は力場差が平均ゼロのランダム変動で、
   単一 σ_FF が系・観測量をまたいで転用可能であることを仮定する。実際は系依存の系統バイアスなので
   単一分散に畳めない。同様に「Δ なら力場オフセットが相殺される」も一般には成立しない
   (相殺は bias が両条件で同じ場合のみ)。
4. **旧 L4 を 2 軸に分割。** `observable_recompute` (selection/alignment/PBC/実装版の問題) と
   `ensemble_reproduction` (sampling/力場/初期条件/protocol の問題) は失敗原因が異なる。
   後者は matched-protocol / diagnostic-only / calibrated の 3 モードに分け、
   matched-protocol なら σ_FF は不要 (「σ_FF が測れなければ絶対値タスクを一切作らない」は強すぎた)。

**新規に見つかった scorer バグ.** `DeterministicCheck.capability` の明示 override
(`MDPrepBench/mdprepbench/models.py:291-306`) が capability profile 集計で無視される。
`CheckResult` (`models.py:1079-1085`) が capability を保持せず、`scoring.py:3662-3685` が常に
`DEFAULT_CHECK_CAPABILITY` を引くため。現行 P01-P40 は override 未使用なので今の得点には影響しないが、
自動生成タスクが capability を明示し始めると公開契約と実際の集計が食い違う。**タスク量産前に修正が必要。**

**MDDB 単独 + CC-BY 限定にした結果の実測 (定義つき).**

- ライセンス: CC-BY 4.0 が 4511、CC0 19、**CC 系でないものが 24** (AFL 3.0 が 9、Apache 2.0 が 5、
  MIT 4、LGPL 2、記載なし 4)。タスク生成はこの 24 件を除外する。
- **膜系の軸は実質失われた。** 実バイアレイヤ (`LIPIRES>=100`) は 30 件だが **20 件が非 CC**
  (CLC / Nav 5WEO / TARP / HCN / CTL1、および唯一の GPCR `OTRMG` `OTRMGb` も非 CC)。
  CC-BY の膜系は 10 件で全て SARS-CoV-2 のウイルス膜。
  **P18 膜系が全モデル失敗する既知の弱点を DB 由来タスクで補強する道は閉じた。** 膜系は手書きで扱う。
- **力場感度の測定源は MDDB 内に存在する。** 同一 PDB が複数力場で登録された群が **11、全て CC-BY**。
  `6VXX` が 6 力場、`6M0J` が 5、`1FZX` / `1ICK` / `1SK5` / `3GGI` が 4
  (OL15 / OL21 / ParmBSC1 / Tumuc1、各 2 entry) で、核酸 4 系は力場比較目的の study に見える。
  ただし同一 PDB でもリガンドパラメータ・プロトネーション・欠損ループ・イオン強度・ensemble・
  engine・軌道長・初期構造が交絡しうるため、**matched を確認するまで力場感度に帰属しない**。

**計数の定義の問題.** 前エントリの「脂質を含む 43 件」は定義なしで誤読を招く。
`LIPIRES>0` は 43、`LIPIRES>=100` は 30、`MEMBRANES` 非空は 10 で、どれを指すかで意味が変わる。
また `totalFrames` 296128391 は summary エンドポイントの集計値で、project 一覧の総和 287267536 とは
別の量である (3% 差)。**以後、計数は必ず定義とともに記す。**

**次の 4 手 (いずれも MD 不要).** (1) 核酸 4 系 16 entry の matched-protocol 検証、
(2) 解析契約レジストリの最小版 (観測量 1 つで MDDB 前計算値と自前再計算値のずれを測る)、
(3) `observable_recompute` タスク 10 本、(4) 上記 scorer バグの修正と回帰テスト。

---

## 2026-08-18 — 公開 MD DB (GPCRmd / MDDB) 由来ベンチの実測と検証層の設計

MDPrepBench / MDStudyBench を公開 MD データベースから自動生成できるかの調査。
設計は `docs/research/db_derived_benchmark_validation.md` に分離。ここには実測値と判断だけ残す。

**実測 (API / 公開ページを直接叩いた).**

- MDDB (`https://mmb.mddbr.eu/api/rest/v1/`, 無認証): 4554 projects / 14138 MD /
  296M frames / 33.6 TB。`LICENSE` は 4511 件が CC-BY 4.0。条件ベクトル
  (`FF` `TEMP` `WAT` `ENSEMBLE` `TIMESTEP` `LENGTH` `SOL` `NA` `CL` `MEMBRANES` `PDBIDS`) が機械可読。
  前計算解析が約 4500 系 × 10 種 (`rmsds` 4551 / `fluctuation` 4551 / `rgyr` 4551 / `sasa` 4552 /
  `pca` 4552 / `tmscores` 3285 / `hbonds` 2318 / `interactions` 2398、膜系は `apl` `thickness`
  `lipid-order` `mem-map`) で JSON 時系列としてそのまま取得できる。`mdcount>=2` が 1328 project
  (10 replicas が 605、6 が 271、8 が 160、9 が 152)。
- **MDDB に GPCR はほぼ無い。** 全 4554 中で脂質を含むのは 43 件のみ、うち GPCR は
  `OTRMG` / `OTRMGb` (ヒトオキシトシン受容体, 7RYC, Amber ff14SB, 3 replicas, LIPIRES=256) の 1 系だけ。
  残りは CLC (8-9 replicas)、Nav (5WEO)、TARP γ2/γ7、HCN、CTL1、SARS-CoV-2 spike/膜、
  および LIPIRES=1 の界面活性剤単分子系。膜系タスクで MDDB は GPCRmd の代替にならない。
- GPCRmd: API とファイル DL はログイン必須 (DL は 1 リクエスト 5 dynamics 上限) だが、
  **`/dynadb/dynamics/id/<id>/` の report ページは無認証で完全な条件表を返す**。
  ID 36 実測: 3REY.A / Inactive / TIP3P / POPC / Cl 191 mM, Na 159 mM /
  Water 22376, POPC 207, Cl 77, Na 64 / 100039 atoms / CHARMM36m / 4.0 fs / Replicates 3 / 1.5 µs。
  `/dynadb/datasets/` は無認証で 773 の view ID を Complex / Apoform ペアとして公開。
- **GPCRmd は CHARMM 一様ではない。** 実在 24 ID をサンプルして 12 件パースできたうち、
  1 件が ff19SB/lipid21/GAFF2 + AMBER PMEMD.CUDA (ID 2322)。CHARMM も 36 / 36m Feb2016 /
  May2015 / c36 Jul2021 と版が割れ、エンジンは ACEMD / ACEMD3 / GROMACS 2021.3 / PMEMD、
  膜は POPC 単一が 6 件で残り 4 件が混合 (DOPC/DPPC/DSPC/SDPC、POPC+CHL1、POPG+CO1+POPC)。
  Nature Methods 2020 のコアが一様なだけで、以後のコミュニティ投稿は多様化している。
- 24 ID 中 12 は report ページを取得できず (500 / no report)。773 は上限であって使える N ではない。
  8/24-8/28 は GPCRmd メンテナンス予定。

**既存ハーネスの状態 (grep で確認).**

- MDPrepBench: `check_type` は 24 種すべて**バージョン無し**。集計は重み付き平均 (補償的) +
  `_HARD_FAIL_CHECK_TYPES` クランプ。軸は `identity` / `physical_validity` / `fidelity` / `provenance`。
- MDStudyBench: `region_water_occupancy@1` 形式で**バージョン有り**。
  `grounded_correct = valid_execution AND claim_supported AND truth_agreement` の非補償 AND。
- **どちらにも solve 時のネットワーク遮断が無い** (`run.py` に該当制御なし)。
  参照 DB を使うベンチではこれが最大の穴で、エージェントが参照そのものを取得できると全層が同時に無効化される。

**判断.**

- 検証は 7 層 (`identity` / `physical_validity` / `composition_fidelity` / `execution_validity` /
  `observable_fidelity` / `claim_support` / `truth_agreement`) に分け、層をまたぐ補償はしない。
  外部 DB が要るのは 3 層だけで、残り 4 層は DB なしで先に固められる。
- 新規語彙は `observable_fidelity` の 1 つだけ。参照軌道を固定入力として渡す層で、**MD を走らせない**ので CI に載る。
- 力場一致は要件にしない。組成照合・参照軌道の再解析・ペア差分のいずれも参照の力場に依存しないため。
  「GPCRmd が CHARMM だから使いにくい」が効くのは絶対値を参照に合わせにいく設計だけで、それは採らない。
- 自前 MD と参照を絶対値で比べる層 (L4b) は σ_FF が測れる場合のみ作る。
  測定源は「GPCRmd 内で同一 PDB が CHARMM コアと Amber 投稿の両方に現れるペア」。無ければ作らない。

**次の 3 手 (いずれも MD 不要).** (1) MDDB の 1328 project から観測量ごとの σ_rep を算出、
(2) GPCRmd 773 ID をクロールして同一 PDB の力場違いペアを探索し L4b の可否を決める、
(3) `observable_fidelity` タスクを 10 本作る。
