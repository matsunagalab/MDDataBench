"""Thread guard, applied before numpy is imported anywhere.

The container's OpenBLAS is built ``DYNAMIC_ARCH NO_AFFINITY MAX_THREADS=64``.
With no thread limit set it collapses on small LAPACK problems: measured
2026-08-19 on a 32-core host, ``eigh`` of the 684x684 covariance took 16.3 s
inside the image and 0.59 s outside it, and setting a limit brought it to
0.12 s.  Scoring one task went from over ten minutes to seconds.  Only set
when the caller has not chosen a value.
"""

import os

for _variable in ("OMP_NUM_THREADS", "OPENBLAS_NUM_THREADS", "MKL_NUM_THREADS"):
    os.environ.setdefault(_variable, "8")
