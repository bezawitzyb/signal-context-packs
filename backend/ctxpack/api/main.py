"""FastAPI app: /ping, /health, live run events and the placeholder home page.

Started by start.sh (locally) and the Dockerfile (Render) as ONE uvicorn
worker on $PORT. The frontend build is served here in a later step.
"""

import asyncio
import logging
from contextlib import asynccontextmanager
from importlib.metadata import version as pkg_version

from fastapi import FastAPI
from fastapi.responses import HTMLResponse, PlainTextResponse
from sqlalchemy import text

from ctxpack import db, worker
from ctxpack.api.routes import router
from ctxpack.config import get_settings

logging.basicConfig(
    level=get_settings().log_level,
    format="%(levelname)s:     %(name)s: %(message)s",
)
log = logging.getLogger(__name__)

VERSION = pkg_version("ctxpack")

PLACEHOLDER_HTML = """<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>SIGNAL - Context Packs</title>
<style>
  body { margin: 0; min-height: 100vh; display: grid; place-items: center;
         font-family: system-ui, sans-serif; background: #fafaf7; color: #1a1a1a; }
  h1 { font-weight: 600; letter-spacing: .02em; }
  p { color: #555; }
</style>
</head>
<body>
<main>
  <h1>SIGNAL - Context Packs</h1>
  <p>Coming soon.</p>
</main>
</body>
</html>
"""


async def _startup_tasks(stop: asyncio.Event) -> None:
    """Tables, featured packs, retention, interrupted runs (B4), then the worker loop (B13).

    Runs in the background so the server answers /ping straight away,
    even while Neon wakes up. A failure is logged (type only) and /health
    then reports the database as unreachable.
    """
    try:
        result = await asyncio.to_thread(db.startup)
        log.info("startup tasks done: %s", result)
    except Exception as exc:  # never log the message: it may contain the URL
        log.error("startup tasks failed: %s", type(exc).__name__)
        return
    if get_settings().worker_mode == "inprocess":
        await worker.worker_loop(stop)


@asynccontextmanager
async def lifespan(app: FastAPI):
    stop = asyncio.Event()
    task = asyncio.create_task(_startup_tasks(stop))
    yield
    stop.set()
    task.cancel()


app = FastAPI(title="SIGNAL - Context Packs", version=VERSION, lifespan=lifespan)
app.include_router(router)


@app.get("/ping", response_class=PlainTextResponse)
async def ping() -> str:
    """Keep-alive target. Never touches the database or a paid API."""
    return "ok"


def _database_reachable() -> bool:
    try:
        with db.get_engine().connect() as conn:
            return conn.execute(text("SELECT 1")).scalar() == 1
    except Exception as exc:
        log.warning("health: database unreachable (%s)", type(exc).__name__)
        return False


@app.get("/health")
def health() -> dict:
    """App status + version + whether the database answers SELECT 1."""
    database = _database_reachable()
    return {"ok": database, "version": VERSION, "database": database}


@app.get("/", response_class=HTMLResponse)
async def home() -> str:
    return PLACEHOLDER_HTML
