# MDDataBench Agent Guide

This guide is mirrored as both `CLAUDE.md` and `AGENTS.md`. Keep the two copies
identical. Keep it short.

## Project Overview

MDDataBench is a standalone benchmark asking whether an agent can run a short
molecular dynamics simulation that reproduces a real deposited one. References
come from [MDDB](https://mddbr.eu/) under CC BY 4.0, not from a curator.
Scoring is deterministic and artifact-based; no LLM judge contributes. It was
extracted from [matsunagalab/mdclaw](https://github.com/matsunagalab/mdclaw),
alongside [MDPrepBench](https://github.com/matsunagalab/MDPrepBench) and
[MDStudyBench](https://github.com/matsunagalab/MDStudyBench).

## Where Things Live

- `mddatabench/`: the harness package. CLI entry `mddatabench` dispatches over
  `mddatabench.TOOLS`.
- `benchmarks/mddatabench/tasks/*/`: the dataset — `task.json` (contract,
  checks, reference provenance) and `prompt.md` (what the agent sees).
- `tests/`: the suite. Scoring tests need openmm/mdtraj/numpy and a fetched
  bundle, and are marked `slow`.
- `docs/`: design references and `memo.md`.

## Recording Work

`docs/memo.md` is the running record of benchmark work: what was run, the
numbers it produced, what was decided, and why. Append a dated entry whenever
you finish a piece of work or reach a conclusion that outlives the session.
Newest first. When a later finding contradicts an earlier entry, add the
correction and name what it overturns rather than editing the old entry away.

This matters more here than in most repositories: nearly every threshold in
this suite was set by a measurement, not by judgement, and several were set by
a measurement that overturned the obvious choice. A threshold whose measurement
is not written down cannot be defended or revised.

## Invariants

- **Data is fetched, never vendored.** Task contracts carry the accession, the
  retrieval date, the licence, and the bundle SHA-256. Nothing downloaded is
  committed.
- **Only openly licensed projects are eligible**, and the licence string MDDB
  returns is recorded verbatim in the task contract. Most are CC BY 4.0. The
  DynaRepo node returns Apache License 2.0 or no licence at all while its paper
  states CC BY-NC 4.0; that discrepancy is recorded per task. Nothing
  downloaded is redistributed either way.
- **MDDB is eight federated nodes, and accessions are node-local.** A task
  contract carries `(node, accession)`; `A01M6` is a different project on oxf,
  mmb and bsc. The node registry is served only by the global API
  (`mdposit.mddbr.eu`), which is not a superset of the nodes.
- **The reference is never staged into the solver workspace.** The evaluator
  fetches it at scoring time and computes every comparison itself.
- **Prompts state only what cannot be inferred** and say nothing about
  analysis. Never name the accession in a prompt.
- **Every axis is evaluated independently**; only the final verdict is gated.
  Checks are reported under `prep` and `md` separately so a failure is
  attributable.
- **Nothing is scored against an uncalibrated threshold.** Quantities whose
  force-field sensitivity has not been measured are recorded as diagnostics.
- **Adversarial baselines must fail.** Change an md-side threshold, re-run
  `run_benchmark_negative_controls`.

## Development

```bash
pip install -e .
ruff check mddatabench/ tests/
python -m pytest tests/ -q -m "not slow"
```

Running numpy work inside `mdclaw.sif` requires a thread limit; see the
"Running the scorer" section of the README.
