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
`init_experiment` also probes the runtime image from inside (`import mdclaw`
must fail there) and records a generated inventory: the Python version, the
versions of a fixed list of MD packages (`RUNTIME_PACKAGES`) and which of a
fixed list of executables (`RUNTIME_EXECUTABLES`) are on the image's PATH.
The attempt's `CAPABILITIES.md` lists that inventory as documentation, not
as a recommendation, together with the `singularity exec` form to run it. A
CLI condition can ask `mdclaw --list`; a bare runtime has no such index, and
minutes spent discovering an unknown image measure something other than the
agent's molecular dynamics. The inventory is generated, never hand-written,
so it cannot drift from the image; `"runtime_inventory": false` (top-level or
per cell) restores the bare `Runtime SIF:` line. Results with and without the
inventory are different conditions; the manifest records which one applied.
Skill-enabled attempts explicitly load `mdclaw_source/skills` from this checkout
for each harness by default. A pi cell may instead set `"skill_source": "user"`
to use normal user-wide discovery, as the laboratory DeepSeek example does.
No-skill Codex attempts additionally use an empty per-attempt `HOME` while
preserving `CODEX_HOME` for authentication.

## Image mode: skills and the SIF only

`"source_mode": "image"` (top-level or per cell) drops the checkout entirely.
No `mdclaw_source` or `mdclaw_cli` is accepted for such a cell, nothing is
frozen, and no `mdclaw` wrapper is written: the attempt has its skills (pi's
user-wide package from `pi install git:github.com/matsunagalab/mdclaw@main`
with `"skill_source": "user"`, or a `skills_dir`) and the image, and invokes
the image's own CLI as the MDClaw skill describes:

```bash
singularity exec --env PYTHONPATH= --env PYTHONHOME= <sif> mdclaw <tool> ...
```

`init_experiment` probes the image once (`python -c "import mdclaw"` inside
it) and records the module path, `mdclaw` version and the image SHA-256 in
`experiment.json` and every manifest; `hashes.sif` and
`revisions.mdclaw_image_sha256` replace the frozen tree digest as the identity
the numbers belong to. The workspace's `.mdclaw_cluster.json` is written in
`source_mode: image`, so compute jobs run the image's package too.

The image's Slurm tools call the *host's* clients. `init_experiment` therefore
discovers the host resources they need (`sbatch` and friends, the Slurm plugin
directory, `libmunge`, `/etc/slurm`, the munge socket, and passwd/group files
augmented with the invoking account and `SlurmUser`; see
`mddatabench/slurm_binds.py`) and records them as `container_binds`. Set
`container_binds` in the spec to override discovery. At launch the runner
exports them together with the attempt directory through `APPTAINER_BIND` /
`SINGULARITY_BIND`, and presets `MDCLAW_SLURM_PATH` inside the image to the
host search path, whose first entry is the attempt's `sbatch` shim. The agent
never names a bind.

The shim then runs *inside* the image. It rejects any job whose `PYTHONPATH`
is non-empty, whose image differs from the manifest, or whose binds shadow the
probed package directory, and rewrites the payload so the job aborts unless
`mdclaw.__file__` is the probed module. Because `sbatch` exports the
submitter's environment to the job, the shim also hands the worker a host
environment: image-only loader and interpreter variables (`LD_PRELOAD`,
`LD_LIBRARY_PATH`, `PYTHONPATH`, `PYTHONHOME`) and Apptainer bookkeeping are
dropped and `PATH` becomes the host search path. Measured 2026-09-09 on
Rikyu, a job submitted from inside the SIF without this failed with
`singularity: command not found` and logged an `ld.so` preload error for every
host process.

Login-node commands are not mediated by the shim. `agent_end` events in image
mode carry a `source_audit` with counts of `bin/mdclaw`, `PYTHONPATH=/` and
source-bind mentions in the transcript; a non-zero count marks an attempt for
inspection and changes no score. On Rikyu, `sbatch` refuses jobs without an
account: export `SBATCH_ACCOUNT=<project>` before `run_experiment`; the
evaluator scorer submits plain `sbatch` and relies on it as well.
[`examples/experiment-rikyu-image.json`](../examples/experiment-rikyu-image.json)
is a complete image-mode spec.

## Site scheduler notes

`slurm_notes` (top-level or per cell) is a list of sentences shown in every
condition's `CAPABILITIES.md` as `Slurm note: ...`. It is environment
documentation in the same sense as the runtime inventory: on Rikyu the
scheduler rejects `--gres=gpu:N` in favour of `--gpus=N`, and the account is
preset through `SBATCH_ACCOUNT`. MDClaw's `submit_job` already uses `--gpus`,
so without the note only `sif_only` agents paid to discover the rule
(measured 2026-09-10). The notes are recorded in each manifest.

## Chained production

MDClaw continues a production across nodes: `prod_002` has `prod_001` as its
parent and restarts from its state. Under a 20-minute job limit a membrane
system reaches 1 ns only that way. The scorer therefore grades the chain that
ends at the latest completed production node as one production: the
trajectories are concatenated oldest first, `simulation_time_ns` is summed,
the state logs are concatenated, and the frame interval is read from the
first segment. Segments must agree on temperature, pressure, timestep, HMR
and ensemble; a restart under different conditions is not a continuation, and
only the last node is graded (the report says which segments were dropped).
The lineage used for prep, topo and min selection is unchanged. Measured
2026-09-10: four otherwise correct attempts, graded as 0.4 ns from the last
segment alone, failed four checks; re-scored as 1.2 ns they pass.

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

The experiment directory must be outside the MDDataBench checkout.
`init_experiment` rejects the checkout itself and every path below it so attempt
workspaces cannot expose writable benchmark sources.

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
- `scoring_failures.csv`: all failed weighted checks, counted separately from
  execution failures. These are scoring symptoms, not inferred root causes.

Token fields are nullable and include provenance because not every harness
reports usage. Slurm queue/runtime/GPU estimates come from `sacct` for every
job in the submitted MD dependency chain, with job states retained; per-node
wall times come from MDClaw node metadata. `collect_experiment` reports
incomplete attempt IDs and returns unsuccessful until every planned attempt has
a terminal result.

Version-2 attempt records separate `scoring_failures` from
`execution_diagnostics` (node status, failure codes/messages, event and scheduler
evidence with source paths). Known completed production with failed checks is
classified as `evaluation`; unavailable execution evidence stays `unknown`.
Recovered/abandoned failed branches remain in the evidence but are not selected
as final failures when production completed. Multiple failed nodes are retained
without claiming a unique root cause. Explicit harness failures remain explicit.
The snapshot is sealed with the result so later workspace cleanup cannot erase
the diagnosis. No pass rule or check score is changed.

## Tokens, failures and recovery

Each attempt's transcript is reduced to one record per model call by
`mddatabench/transcript.py`: pi's assistant `message_end` (its
`message_start`/`message_update`/`turn_end`/`agent_end` repeat the same
usage), Claude Code's `assistant` events merged by message id with the
`result` event's session total taken as authoritative (per-message
`output_tokens` are partial streaming counts), and Codex's `turn.completed`
usage (one record per turn). Token fields follow the provider's own
accounting: `prompt_uncached` (charged as new computation), `cache_read`,
`cache_write`, `prompt_total` (their sum), `output`, and `reasoning` (the
reasoning share of `output` when reported). A call whose usage is all zero,
which is what pi records when a provider is not asked for usage, counts as
missing; `calls_without_usage` says how many. `provenance` is `transcript`,
`transcript_total` (Claude Code) or `unavailable`.

Rikyu reports usage only when pi asks for it in streaming mode: set
`"supportsUsageInStreaming": true` in the rikyu provider's `compat` block of
`~/.pi/agent/models.json` (done on 2026-09-09; campaigns before that have no
usage). Rikyu's prefix cache makes most of a multi-turn prompt `cache_read`,
and hits depend on server state, so report `prompt_total` and `output` as the
primary figures and `prompt_uncached` / `cache_hit_ratio` as effective-compute
diagnostics. Token counts are tokenizer-specific: compare conditions within a
model, not tokens across models. `tokens_per_success` is the cell's total
prompt and output tokens divided by its successes, so failed attempts' spend
is charged to the successes.

`skill_reads` counts tool calls that read a skill page (paths under the
attempt's skill roots, or any `/skills/` path or `SKILL.md`) and the characters
they returned, which is the transcript cost of the skill itself. `phases`
splits calls, seconds and prompt tokens by the stage each call worked on
(`skill_read`, `source`, `prep`, `solv`, `topo`, `min`, `eq`, `prod`,
`submission`, `probe`, `text`), labelled from the MDClaw tools named in its
commands; `timeline.jsonl` beside the result keeps the per-call series.

MDClaw results are recognised when a command's JSON reply is echoed into the
transcript; agents that pipe output through python or redirect it to a file
leave only the invocation. `execution_diagnostics.mdclaw_error_codes` counts
the `code` of every recognised `success: false` reply, and `error_codes.csv`
tabulates them by cell.

`mddatabench/recovery.py` turns three kinds of failure evidence into
episodes: a recognised tool failure, a DAG node whose status is `failed`
(MDClaw never mutates a failed node, so recovery is a new node), and a
Slurm job that ended in a non-completed state. Recovery is the same stage
succeeding later: a later successful result of the stage, a later completed
node of the same type, or a later completed job of the same stage. An
episode records the stage, kind, code, the calls, tokens and seconds spent
up to the recovery, the means observed in between (`diagnostic_tool` for
`trace_failure`/`inspect_job`/`explain_node`, `new_node`, `read_documentation`,
`argument_change` with the added flags, `resubmission`), and the outcome
(`recovered`, `abandoned`, or `timed_out` when the agent hit its wall limit).
These are observations, not causes: what was changed is listed so a person
can judge. `recovery.csv` aggregates episodes by cell, stage, kind and code;
the per-attempt `recovery` block also says whether the attempt was
`failure_free`. `failure_digest/<attempt>.md` collects, for every failed
attempt, the failure stage and code, failed checks, error codes, episodes,
phases and the last five tool calls.

Attempts sealed before schema version 3 gain these fields at
`collect_experiment` time from their transcripts (`recovery.provenance` is
`collect_time`); their `result.json` is not rewritten.

GPU seconds mean allocated GPU count times allocation elapsed seconds, not
measured device utilization. A complete total requires every expected job to
have valid accounting. Attempt metrics retain `gpu_seconds_known`, observed
and expected job counts, and coverage; summary tables analogously retain
`known_gpu_seconds`, observed/expected **attempt** counts and coverage. With
any missing value the complete total is null (blank in CSV); the known subtotal
is null if nothing was measured. Measured zero remains zero. Absent GPU counts
in empty accounting are unknown; a CPU allocation's populated AllocTRES without
GPU entries establishes zero. Old totals without completeness evidence are
only unverified known subtotals, never certified complete totals.

To diagnose sealed historical results without modifying them or invoking Slurm,
use a **new** output directory (not the original summary or an attempt directory):

```bash
mddatabench collect_experiment --experiment-dir <experiment> \
  --out-dir <new-corrected-summary> --refresh-diagnostics true
```

This mode reads available records, preserves all original pass/score fields,
and includes the original result SHA-256 and old classification in each derived
row. It does not reconcile unfinished scorers, rerun MD, rescore trajectories or
rewrite result.json. Missing evidence stays missing; existing version-2 sealed
diagnostics and accounting snapshots are retained.
