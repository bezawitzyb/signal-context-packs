#!/bin/sh
# Start the app locally: ONE uvicorn worker on $PORT (default 7860).
# The Dockerfile runs the same command on Render.
set -e
cd "$(dirname "$0")/backend"
exec uv run uvicorn ctxpack.api.main:app --host 0.0.0.0 --port "${PORT:-7860}" --workers 1
