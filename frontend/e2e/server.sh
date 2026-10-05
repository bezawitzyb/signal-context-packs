#!/bin/sh
# The e2e server: the real app in fake mode (LLM_FAKE + fixtures) with a throwaway SQLite database.
# No Anthropic, Apify or Neon. The run key and salt are random values made fresh for each test run
# (playwright.config.ts passes the key as E2E_RUN_KEY); no key is ever written in a file.
set -e
DIR="$(cd "$(dirname "$0")" && pwd)"
TMP="${TMPDIR:-/tmp}/signal-e2e"
rm -rf "$TMP" && mkdir -p "$TMP"
cd "$DIR/../../backend"
export DATABASE_URL="sqlite:///$TMP/e2e.db" LLM_FAKE=true USE_FIXTURES=true DATA_DIR="$TMP/data"
export RUN_KEY="$E2E_RUN_KEY"
export AUTHOR_HASH_SALT="$(openssl rand -hex 16)"
exec uv run uvicorn ctxpack.api.main:app --host 127.0.0.1 --port 8767 --workers 1
