import os
import sys
from pathlib import Path

# The scorer imports numpy through a thread guard; keep tests cheap too.
os.environ.setdefault("OMP_NUM_THREADS", "2")
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
