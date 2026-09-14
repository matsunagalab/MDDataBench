# Runbook: MDDataBench campaigns with other models, CLI + skills only

For an agent (or a person) who runs MDDataBench on RIKYU for a model other
than kimi-k3, in the `cli_skill_sif` condition only, so that the result lands
as one more bar next to kimi-k3 in `scripts/paper_figures.py` (fig6). Written
2026-09-14 after campaign v2, the 9/14 rerun and the launch of v3. Read the
"Never" list first.

## Never

- Never write under `/data1/rkp00048` (that project has ended).
- Never replace the shared image behind
  `/data1/rkp00079/mdclaw-rikyu-arm64-cuda130-cufft121-fusefix-6f171d2f0fa5.sif`
  and never run `pi update` while any campaign is running (v3 runs from
  2026-09-14 20:06 JST for about two days: `runs/kimi-k3-3cond-full-v3`,
  check `ps -p $(cat .../dispatcher.pid)`). A campaign compares conditions;
  its image and skill text must stay fixed for its whole duration.
- Never kill processes by pattern; kill by PID only, and only your own
  dispatcher (`dispatcher.pid` in the experiment dir).
- Never run heavy work on the login node while agents run there (test suites,
  rescoring, replays): agents do preparation and solvation on the login node
  and a loaded node turns into timeouts.
- `sbatch` needs `--account=rkp00079` and `--gpus=N` (the launcher exports
  `SBATCH_ACCOUNT`; the agents' jobs go through the harness's sbatch shim).

## What a campaign is made of

- **Harness**: `/data1/rkp00079/rku00161/MDDataBench` (main). The dispatcher
  runs the agents from this checkout (`PYTHONPATH=$PWD`), the scorer jobs bind
  it into the image. Pull only between campaigns.
- **Image**: the fixed path above; `apptainer inspect <path> | grep
  source.commit` says which mdclaw is baked in (b648068 since 9/14 09:26 JST).
  The spec's `sif_sha256` must equal the image's digest; the launcher trusts
  the spec, it does not hash the file. Current digest:
  `6ecc1ad9a4c6376448fa43fd1228f997939c15597f2d63478c62f016001a62bc`.
  The older specs under `runs/prep` still carry `ffe1bd9c…`; re-pin them.
- **Skills**: pi's package checkout
  `~/.pi/agent/git/github.com/matsunagalab/mdclaw` (`git -C ... log -1`; must
  hold `skills/md-prepare/SKILL.md`). `cli_skill_sif` with `skill_source:
  user` reads skills from there. On 9/11 the directory vanished mid-campaign
  (cause unknown); the harness now waits instead of launching without skills
  (`skills_missing_wait` event) and `campaign_status.py` prints
  `SKILLS_MISSING`. If it happens: `pi update git:github.com/matsunagalab/mdclaw@main`.
- **Dataset**: `benchmarks/mddatabench` in the harness checkout (98 tasks,
  prompts corrected 9/14 for the four glycosylated deposits).
- **References**: `/data1/rkp00079/rku00161/references` (`--bundle-root`).
- **Models**: `runs/prep/model-inventory.json` (`mddatabench model_inventory`):
  `rikyu/kimi-k3`, `rikyu/glm-5.2`, `rikyu/kimi-k2.6`, `rikyu/qwen3.6-35b`, all
  reasoning models on the rikyu gateway, used with `thinking: high` so far.

## Spec for one model, CLI + skills only

Copy `runs/prep/experiment-kimi-k3-3cond-full-v3.json` and change: one cell,
the model, the id. Everything else (1800 s, image mode, digest, task order)
stays. Example `runs/prep/experiment-glm-5.2-skill-full.json`:

```json
{
  "experiment_id": "glm-5.2-skill-full",
  "replicates": 3,
  "agent_timeout_seconds": 1800,
  "md_time_limit": "00:20:00",
  "sif": "/data1/rkp00079/mdclaw-rikyu-arm64-cuda130-cufft121-fusefix-6f171d2f0fa5.sif",
  "sif_sha256": "6ecc1ad9a4c6376448fa43fd1228f997939c15597f2d63478c62f016001a62bc",
  "source_mode": "image",
  "cells": [{"condition": "cli_skill_sif", "harness": "pi", "model": "rikyu/glm-5.2",
             "thinking": "high", "skill_source": "user"}],
  "runtime_sif": "/data1/rkp00079/rku00161/mddatabench-runtime-nomdclaw.sif",
  "slurm_notes": ["Request GPUs with --gpus=N; --gres=gpu:N and --gpus-per-node are rejected.",
                  "The Slurm account is preset through the environment; do not pass --account."],
  "_task_order": "hardest first: membrane, ligand, metal, complex, nucleic, nanobody, antibody, soluble_charmm, soluble_amber"
}
```

No `tasks` key means all 98. `thinking` is per cell; if a model rejects the
thinking flag, the pilot shows it in `agent.stderr.log` and the cell needs
`"thinking": null`.

## Pilot first, always

A new model can fail in ways the harness has never seen (tool-call format,
thinking flag, empty responses). Run a pilot before the full campaign:

```bash
cd /data1/rkp00079/rku00161/MDDataBench
export SBATCH_ACCOUNT=rkp00079 OPENMM_CPU_THREADS=8 OMP_NUM_THREADS=8 PI_CMD_TIMEOUT_SECONDS=600
# the gateway answers?  (the dispatcher probes too, but this is faster to read)
pi --print --model rikyu/glm-5.2 --no-skills --no-extensions --no-prompt-templates --no-context-files "Reply with the single word OK."
# a spec with "tasks": [six ids across axes], "replicates": 1
env PYTHONPATH=$PWD /usr/bin/python3 -m mddatabench init_experiment \
  --experiment-dir /data1/rkp00079/rku00161/runs/glm-5.2-skill-pilot \
  --spec-file /data1/rkp00079/rku00161/runs/prep/experiment-glm-5.2-skill-pilot.json \
  --dataset-dir benchmarks/mddatabench
```

Pilot task set that covers the axes and the known hard cases: `001_membrane_5yc8`,
`015_antibody_1ahw` (413k atoms), `023_antibody_3wd5`, `040_ligand_3n2u`,
`051_nucleic_1kx5`, `069_soluble_1aol` (glycan prompt), `092_soluble_1ah9`.
Read the transcripts (`agent.stdout.jsonl`) of the pilot, not only the pass
rate: does the model call `mdclaw` through `singularity exec` as instructed,
does it read the skills (`metrics.skill_reads` in `result.json`), does it end
its runs with a tool call or with prose?

## Launch

```bash
E=/data1/rkp00079/rku00161/runs/glm-5.2-skill-full
cat > $E/launch.sh <<'SH'
#!/bin/bash
export SBATCH_ACCOUNT=rkp00079
export OPENMM_CPU_THREADS=8 OMP_NUM_THREADS=8 OPENBLAS_NUM_THREADS=8 MKL_NUM_THREADS=8
export PI_CMD_TIMEOUT_SECONDS=600
cd /data1/rkp00079/rku00161/MDDataBench
exec env PYTHONPATH=$PWD /usr/bin/python3 -m mddatabench run_experiment \
  --experiment-dir /data1/rkp00079/rku00161/runs/glm-5.2-skill-full \
  --bundle-root /data1/rkp00079/rku00161/references \
  --scorer-sif /data1/rkp00079/mdclaw-rikyu-arm64-cuda130-cufft121-fusefix-6f171d2f0fa5.sif \
  --max-agents 6 --max-seconds-per-call 30
SH
chmod +x $E/launch.sh; cd $E && nohup ./launch.sh > run_experiment.log 2>&1 &
sleep 3; pgrep -f "run_experiment --experiment-dir $E" | head -1 > $E/dispatcher.pid
```

`--max-agents`: 6 when nothing else runs on the login node; 3 while another
campaign runs (v3 uses six agents; the node had a load of 135 on 144 cores on
9/14 evening from other users). `--max-seconds-per-call 30` is the pace
governor: it halves the agents allowed to run while the last six finished runs
paced slower than 30 s per model call and restores them under 21 s; in v2 the
pass rate was 92 % under 20 s/call, 64 % at 30-40 s, 0 of 11 above 40 s.
`launch.sh` is restart-safe: running it again skips finished attempts.

## Monitor

Every 30 minutes:

```bash
python3 /data1/rkp00079/rku00161/runs/prep/campaign_status.py $E
python3 /data1/rkp00079/rku00161/runs/prep/sweep_dead_jobs.py $E --cancel >> $E/dead_job_sweeps.log
ps -o pid,stat,etime -p $(cat $E/dispatcher.pid)
```

Lines to act on: `SKILLS_MISSING` (pi update, the agents are waiting),
`PACE` above 30 s/call for an hour (the gateway is slow; the governor is
already throttling; nothing else to do but note it), `RESETS` growing fast
(gateway incident), `agents_running=0` with attempts left and the dispatcher
alive (stall: read `run_experiment.log`), `LOGTAIL` with a traceback. Report
progress as passed/completed, in that order.

## What the harness already does about infrastructure

- Gateway errors, zero-output responses and runs that stop without a tool
  call before half their budget are reset and rerun, up to three times
  (`retired/<stamp>-<reason>/` keeps every run; `RESETS` counts them).
- Agent MD jobs carry `--kill-on-invalid-dep=yes`; never-runnable jobs are
  cancelled before the scorer is attached.
- Every result records `seconds_per_call` (wall seconds between model calls,
  tool time included), `agent_wall_seconds`, `phases`, `token_usage`.

## After the campaign

1. Rerun what infrastructure took: attempts with `failure_stage` infra, and
   timeouts that ran at more than 30 s per call, are candidates.
   `reset_attempts --experiment-dir $E --attempts a,b,c --reason <why>` (add
   `--force` only if the attempt had submitted MD jobs), then `launch.sh` again.
   Say in the memo which attempts were rerun and why.
2. If a scorer defect is found later, `rescore_attempt --attempt-dir A
   --bundle-root ... --sif ... --reason <why>` rescores a sealed attempt without
   rerunning the agent (old seal under `retired/`).
3. Figures: `scripts/paper_figures.py --out DIR --experiment kimi-k3=<v3 dir>
   --experiment glm-5.2=$E ...`; one `--experiment` per model; fig6 lines them
   up under CLI + skills. A single-condition experiment is fine.
4. Append a dated entry to `docs/memo.md` (newest first): what ran, the
   numbers, what was decided and why. Commit the memo and push only when the
   user asks.

## Known failure modes to recognise in transcripts

- `agent_no_submission` with exit `timeout`: the budget ran out before min was
  submitted. Large cells (400k+ atoms) plus a slow gateway; the pace line
  says which.
- `checks_failed` at 18/20 with "energy evaluation failed": a scorer defect
  (fixed 9/14); rescore, do not rerun.
- A final assistant message with `usage.output` 0 or prose without a tool
  call: a cut response from the gateway, not the model's decision; the
  harness reruns it.
- `tool_not_available` with a strange tool name (`'A'`): the model's own
  shell scripting mistake; usually recovered within the budget.
- `associated_ligands_require_selection`, `residue_range_chain_not_found`:
  refusals before the node begins; they cost time, not nodes.
