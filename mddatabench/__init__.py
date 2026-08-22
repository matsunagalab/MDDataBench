"""Benchmark for LLM-agent molecular dynamics, scored against a public database.

Task references come from MDDB (https://mddbr.eu/) under CC BY 4.0 rather than
from a curator. Data is fetched, never vendored: task contracts carry the
accession, the retrieval date, the licence, and the SHA-256 of the bundle.

- ``execution``: the diffusive clock that measures how much simulated time a
  trajectory actually contains, instead of trusting the runner's claim.
- ``dynamics``: the equilibrium estimators the md checks are built on.
- ``calibration``: measures each task's bands from the reference's own windows,
  pooled across its replicas.
- ``topology``: reads the chemistry both sides actually declare, in whichever
  format the MDDB node deposited.
- ``reference``: MDDB bundle retrieval and provenance.
- ``scoring``: deterministic per-check scoring, reported under ``prep`` and
  ``md`` separately so a failure is attributable.
- ``controls``: the adversarial baselines that must fail.
- ``cli``: the tool functions behind the ``mddatabench`` command.
"""

from mddatabench._common import __version__
from mddatabench.cli import (
    TOOLS,
    fetch_benchmark_reference,
    list_benchmark_tasks,
    run_benchmark_negative_controls,
    score_benchmark_submission,
)

__all__ = [
    "TOOLS",
    "__version__",
    "fetch_benchmark_reference",
    "list_benchmark_tasks",
    "run_benchmark_negative_controls",
    "score_benchmark_submission",
]
