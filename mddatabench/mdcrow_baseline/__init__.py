"""MDCrow baseline: run the public MDCrow agent on MDDataBench tasks.

MDCrow (Campbell et al., arXiv:2502.09565; github.com/ur-whitelab/MDCrow) is
run unchanged at a pinned commit. Three things are done around it, never in
its source tree:

- ``runner``: connects MDCrow to an OpenAI-compatible gateway (MDCrow accepts
  only the model-name prefixes of the providers it knows), sends OpenMM's
  ``CPU`` platform request to ``CUDA``, and installs ``recorder``.
- ``recorder``: observes ``openmm.app.Simulation`` and writes down what was
  actually simulated (the System, the states around minimisation, a state log
  with density and box volume). It changes no simulation input.
- ``convert``: maps MDCrow's files and the recorder's files onto the portable
  submission layout (``mddatabench/portable.py``). It reads and links; it
  never builds, repairs or fills in anything.

``campaign`` plans attempts, submits each as one Slurm GPU job inside the
attempt sandbox (``mddatabench/sandbox.py``), and chains the scorer.

``runner`` and ``recorder`` run inside MDCrow's own Python environment and
import nothing from ``mddatabench``. ``convert`` and ``campaign`` are stdlib
plus ``mddatabench``.
"""
