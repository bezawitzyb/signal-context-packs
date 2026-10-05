"""Step 5.1 entry point: the same as `uv run python -m ctxpack.cli eval [--reuse] [--only ID] [--recheck]`.

Run from backend/: uv run python evals/run_eval.py --reuse
"""

import sys

from ctxpack.cli import app

if __name__ == "__main__":
    sys.argv[1:1] = ["eval"]
    app()
