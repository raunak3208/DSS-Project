import os, sys
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
for p in ("common", "processor", "controller"):
    sys.path.insert(0, os.path.join(ROOT, p))
os.environ.setdefault("LLM_PROVIDER", "heuristic")
