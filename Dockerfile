# SIGNAL - Context Packs: one image for Render (guide B12).
# Build context = repo root. Secrets come ONLY from Render's environment;
# .dockerignore keeps .env out of the image.

# --- Stage 1: frontend (Step 4.1) --------------------------------------------
# React Router 8 needs Node >= 22.22; the build output (frontend/dist) is copied into stage 2.
FROM node:24-slim AS frontend
WORKDIR /frontend
COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci --no-audit --no-fund
COPY frontend/ ./
RUN npm run build

# --- Stage 2: backend -------------------------------------------------------
FROM ghcr.io/astral-sh/uv:python3.12-bookworm-slim

ENV PYTHONUNBUFFERED=1 \
    UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_NO_DEV=1

WORKDIR /app/backend

# Dependencies first (cached between builds while uv.lock is unchanged).
COPY backend/pyproject.toml backend/uv.lock ./
RUN uv sync --frozen --no-dev --no-install-project

# Then the code.
COPY backend/ ./
RUN uv sync --frozen --no-dev
COPY featured/ /app/featured/
COPY --from=frontend /frontend/dist /app/frontend/dist

ENV PATH="/app/backend/.venv/bin:$PATH"

# Not root (audit): the app only writes to /app/data (DATA_DIR default ../data); the code stays read-only.
RUN useradd --create-home --uid 10001 app && mkdir -p /app/data && chown -R app:app /app/data
USER app

# ONE uvicorn worker on Render's $PORT (7860 if unset).
CMD ["sh", "-c", "exec uvicorn ctxpack.api.main:app --host 0.0.0.0 --port ${PORT:-7860} --workers 1"]
