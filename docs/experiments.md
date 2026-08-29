# Repeated agent experiments

The campaign runner measures independent attempts across three capability
conditions and any explicit harness/model cells:

| condition | agent can use |
|---|---|
| `cli_skill_sif` | MDClaw CLI, its installed skill, and the scientific SIF |
| `cli_sif` | MDClaw CLI and SIF; MDClaw skills and project context are disabled |
| `sif_only` | a scientific runtime SIF and a fixed portable output layout; no MDClaw |

The primary metric is `success_rate`: the mean of a strict binary score over
all attempts. An attempt is 1 only when every weighted deterministic check
passes. Preparation errors, MD errors, timeout, no Slurm submission, and
scorer errors therefore remain in the denominator as zero. `mean_check_score`,
`any_pass_at_k`, and `reliability_at_k` are reported as secondary diagnostics.
The summary includes a Wilson 95% interval for the per-attempt success rate.

## Image and source isolation

On Rikyu, the shared image is an old dependency image:

```
/data1/rkp00048/mdclaw-rikyu-arm64-cuda130-cufft121-fusefix-54798ff98538.sif
```

For `cli_skill_sif` and `cli_sif`, `sif`, `mdclaw_cli`, and
`mdclaw_source` are all required. `init_experiment` copies the named checkout
to `<experiment-dir>/frozen-source/mdclaw-<n>` and removes write permission
from every file and directory in it; the campaign runs against that copy. The
generated CLI wrapper fixes `CLAUDE_PLUGIN_ROOT` to the frozen copy, and a
`mdclaw_cli` that lives inside the checkout follows it in. MDClaw then binds
the frozen copy into the old SIF and prep/MD commands import it through
`PYTHONPATH`.

Freezing exists because the agent reaches MDClaw through those two variables.
Pointed at a live checkout, an attempt that decides MDClaw has a bug can edit
the package it is being measured against, and every later attempt in the
campaign inherits the edit; one did on 2026-08-25. The same aliasing runs the
other way, so the operator could not touch the checkout while a campaign ran.
`experiment.json` records each frozen source's origin, git revision, whether
the origin had uncommitted changes, and a SHA-256 over the copied tree, and
each attempt manifest repeats the revision and tree digest: the numbers name
the source they belong to. Note the copy is read-only, so removing an old
experiment directory needs `chmod -R u+w` first. `.git` is not copied.
The evaluator similarly binds the current MDDataBench checkout and sets
`PYTHONPATH` when scoring. Thus the image supplies scientific dependencies,
not the package implementation being evaluated.

For `sif_only`, use a separate `runtime_sif` that does not contain MDClaw. The
runner rejects the MDClaw SIF itself for this condition: merely hiding the host
CLI would not prevent an agent from invoking the package baked into the image.
Skill-enabled attempts explicitly load `mdclaw_source/skills` from this checkout
for each harness by default. A pi cell may instead set `"skill_source": "user"`
to use normal user-wide discovery, as the laboratory DeepSeek example does.
No-skill Codex attempts additionally use an empty per-attempt `HOME` while
preserving `CODEX_HOME` for authentication.

## Run a campaign

Start from [`examples/experiment-rikyu.json`](../examples/experiment-rikyu.json)
and enumerate every desired condition/harness/model cell. Model identifiers are
recorded exactly as supplied. To inspect pi's locally available model IDs
without copying credentials:

```bash
mddatabench model_inventory --harness pi --out model-inventory.json
```

On the laboratory PC cluster, use
[`examples/experiment-lab-deepseek.json`](../examples/experiment-lab-deepseek.json).
Its configured model is non-reasoning, so the cell has no `thinking` field.
It sets `skill_source` to `user`, matching the MDClaw skill installed under the
laboratory pi user's `~/.pi`; no checkout-local `--skill` flag is added.
The local endpoint has previously been sensitive to concurrent agents; begin
with `--max-agents 1 --limit 1` and set `PI_CMD_TIMEOUT_SECONDS=600` for the
command watchdog named by the local pi `shellPath`. Select the agent image with
the experiment JSON's top-level `sif` field and pass the same path to
`run_experiment --scorer-sif`.

The example fixes both the login-node agent/preparation budget and every MD
Slurm allocation at 20 minutes. The agent is launched under GNU `timeout`, which
also terminates leftover child processes. The transparent `sbatch` shim removes
an agent-provided `--time` and supplies the campaign's `md_time_limit` on the
command line, overriding any longer `#SBATCH --time` directive. The scorer has
its own 15-minute limit. These are recorded limits; observed wall times remain
separate metrics.

Both operational limits are also inserted verbatim into the main agent prompt,
so success does not depend on whether a model happens to inspect
`CAPABILITIES.md`. The prompt states that the limits do not relax any scientific
requirement and explicitly forbids shortening the requested minimum production
duration or changing the requested force field, solvent, ensemble, temperature,
or pressure to fit the budget.

Initialize immutable attempt manifests and isolated workspaces:

```bash
mddatabench init_experiment \
  --experiment-dir /data1/rkp00048/rku00161/runs/paper-campaign \
  --spec-file examples/experiment-rikyu.json \
  --dataset-dir benchmarks/mddatabench
```

The agent runs on the login node. Its `sbatch` calls pass through a transparent
shim that records the submitted job IDs. The evaluator attaches an
`afterany:<final-md-job>` scorer, so a failed MD job is still scored and cannot
silently disappear. The scorer is evaluator-owned and is not exposed to the
agent.

```bash
mddatabench run_experiment \
  --experiment-dir /data1/rkp00048/rku00161/runs/paper-campaign \
  --bundle-root /data1/rkp00048/rku00161/references \
  --scorer-sif /data1/rkp00048/mdclaw-rikyu-arm64-cuda130-cufft121-fusefix-54798ff98538.sif \
  --max-agents 3
```

`--limit 1` is useful for a first end-to-end attempt. Re-running the command
does not rerun a completed agent; it can repair an interrupted agent-to-scorer
handoff. Three concurrent agents are the Rikyu starting point: they parallelise
login-node preparation without opening an excessive number of CPU-heavy prep
processes. Once Slurm jobs have finished, rebuild all tables from per-attempt
`result.json` files:

```bash
mddatabench collect_experiment \
  --experiment-dir /data1/rkp00048/rku00161/runs/paper-campaign
```

Outputs under `summary/` are:

- `attempts.jsonl`: one complete record per terminal attempt;
- `summary.csv` and `summary.json`: success, partial-score, time, GPU, and token
  aggregates by condition, harness, model, and scientific axis;
- `failures.csv`: failure stage and code counts for later paper plots.

Token fields are nullable and include provenance because not every harness
reports usage. Slurm queue/runtime/GPU estimates come from `sacct`; per-node
wall times come from MDClaw node metadata. `collect_experiment` reports
incomplete attempt IDs and returns unsuccessful until every planned attempt has
a terminal result.
