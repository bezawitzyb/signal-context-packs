#!/bin/sh
# Start the app locally: ONE uvicorn worker on $PORT (default 7860).
# The Dockerfile runs the same command on Render.
set -e
cd "$(dirname "$0")"

# Build the web app (served by FastAPI from frontend/dist). Skipped if npm is not installed.
# For live frontend editing instead: cd frontend && npm run dev (port 5173, /api proxied here).
if command -v npm >/dev/null 2>&1; then
  (cd frontend && { [ -d node_modules ] || npm ci --no-audit --no-fund; } && npm run build >/dev/null) \
    || echo "frontend build failed - serving the API only"
fi

cd backend
exec uv run uvicorn ctxpack.api.main:app --host 0.0.0.0 --port "${PORT:-7860}" --workers 1
