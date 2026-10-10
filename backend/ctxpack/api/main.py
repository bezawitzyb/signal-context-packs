"""FastAPI app: /ping, /health, the REST API (/api/v1), the MCP server (/mcp) and the home page.

Started by start.sh (locally) and the Dockerfile (Render) as ONE uvicorn
worker on $PORT. The frontend build is served here in a later step.
"""

import asyncio
import logging
import re
from contextlib import asynccontextmanager
from importlib.metadata import version as pkg_version

from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse, PlainTextResponse
from sqlalchemy import text

from ctxpack import db, mcp_server, worker
from ctxpack.api.routes import router
from ctxpack.config import get_settings, load_yaml

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
    delay = 2.0
    while not stop.is_set():  # keep trying while the database wakes up (database routes wait for it)
        try:
            result = await asyncio.to_thread(db.startup)
            log.info("startup tasks done: %s", result)
            break
        except Exception as exc:  # never log the message: it may contain the URL
            log.error("startup tasks failed (%s); retrying in %.0f s", type(exc).__name__, delay)
            try:
                await asyncio.wait_for(stop.wait(), timeout=delay)
            except TimeoutError:
                pass
            delay = min(delay * 2, 60.0)
    if stop.is_set():
        return
    if get_settings().worker_mode == "inprocess":
        await worker.worker_loop(stop)


mcp_app = mcp_server.http_app()  # creates the MCP session manager, started in the lifespan below


@asynccontextmanager
async def lifespan(app: FastAPI):
    stop = asyncio.Event()
    task = asyncio.create_task(_startup_tasks(stop))
    async with mcp_server.mcp.session_manager.run():
        yield
    stop.set()
    task.cancel()


app = FastAPI(title="SIGNAL - Context Packs", version=VERSION, lifespan=lifespan)
app.include_router(router)
app.mount("/mcp", mcp_app)

MIRROR_URL = "https://bezawitzyb.github.io/signal-context-packs/"


@app.exception_handler(Exception)
async def friendly_error(request, exc: Exception) -> JSONResponse:
    """Anything unexpected: a plain message, never a stack trace (logged as its type only)."""
    log.error("unhandled %s on %s", type(exc).__name__, request.url.path)
    return JSONResponse(status_code=500, content={
        "detail": "Something went wrong on our side. Please try again in a minute. The example packs are "
                  f"also in the read-only mirror: {MIRROR_URL}"})


# Audit (2026-10-09): browser security headers. The app loads only its own files; the interactive API docs
# (/docs, /redoc) load FastAPI's CDN scripts, so they get the same headers without the content policy.
CSP = ("default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; img-src 'self' data:; "
       "font-src 'self' data:; connect-src 'self'; object-src 'none'; base-uri 'self'; form-action 'self'; "
       "frame-ancestors 'none'")
SECURITY_HEADERS = {"X-Content-Type-Options": "nosniff", "Referrer-Policy": "strict-origin-when-cross-origin",
                    "X-Frame-Options": "DENY"}


@app.middleware("http")
async def security_headers(request, call_next):
    response = await call_next(request)
    for name, value in SECURITY_HEADERS.items():
        response.headers.setdefault(name, value)
    if not request.url.path.startswith(("/docs", "/redoc")):
        response.headers.setdefault("Content-Security-Policy", CSP)
    return response


@app.middleware("http")
async def wait_for_schema(request, call_next):
    """Data audit 3: database routes wait (up to schema_wait_secs) until this process has migrated the database;
    /ping, /health and the web app's files are served at once, so the service answers while Neon wakes up."""
    path = request.url.path
    if (path.startswith("/api/") or path.startswith("/mcp")) and not db.SCHEMA_READY.is_set():
        wait = load_yaml("modes")["worker"]["schema_wait_secs"]
        if not await asyncio.to_thread(db.SCHEMA_READY.wait, wait):
            return JSONResponse(status_code=503, content={
                "detail": "The service is starting up. Please try again in a minute."})
    return await call_next(request)


@app.middleware("http")
async def mcp_without_slash(request, call_next):
    """/mcp and /mcp/ are the same endpoint (MCP clients POST to /mcp and do not follow redirects)."""
    if request.scope["path"] == "/mcp":
        request.scope["path"] = "/mcp/"
        request.scope["raw_path"] = b"/mcp/"
    return await call_next(request)


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
    """App status + version + whether the database answers SELECT 1, and whether new runs are accepted
    today (false once the daily spend cap is reached). No amounts: those stay private."""
    from ctxpack.guards import daily_spend_left

    database = _database_reachable()
    accepting = None
    if database:
        try:
            accepting = daily_spend_left() > 0
        except Exception as exc:
            log.warning("health: spend check failed (%s)", type(exc).__name__)
    return {"ok": database, "version": VERSION, "database": database, "accepting_runs": accepting}


# The built web app (frontend/dist). Locally next to backend/, in the image at /app/frontend/dist.
DIST = Path(__file__).resolve().parents[3] / "frontend" / "dist"
NOT_APP = ("api/", "mcp", "docs", "redoc", "openapi.json", "ping", "health")


def _app_file(path: str) -> Path | None:
    """A file inside DIST (never outside it), or None."""
    if not DIST.is_dir():
        return None
    target = (DIST / path).resolve()
    return target if target.is_file() and target.is_relative_to(DIST.resolve()) else None


@app.get("/", include_in_schema=False)
async def home():
    index = _app_file("index.html")
    return FileResponse(index) if index else HTMLResponse(PLACEHOLDER_HTML)


@app.get("/{path:path}", include_in_schema=False)
async def web_app(path: str):
    """Static files of the web app; every other page path gets index.html (the app routes it)."""
    if path.startswith(NOT_APP):
        raise HTTPException(status_code=404)
    if found := _app_file(path):
        headers = {"Cache-Control": "public, max-age=31536000, immutable"} if path.startswith("assets/") else {}
        return FileResponse(found, headers=headers)
    index = _app_file("index.html")
    if index is None:
        raise HTTPException(status_code=404)
    if m := _PACK_PAGE.fullmatch(path):   # a pasted pack link previews with its own title (exports audit)
        if html := await asyncio.to_thread(_pack_preview_html, index, m.group(1)):
            return HTMLResponse(html, headers={"Cache-Control": "no-cache"})
    return FileResponse(index, headers={"Cache-Control": "no-cache"})


_PACK_PAGE = re.compile(r"packs/(pk_[A-Za-z0-9_-]{6,40})")


def _pack_preview_html(index: Path, pack_id: str) -> str | None:
    """index.html with this pack's title and one-line description (link previews); None on any problem."""
    from html import escape

    from ctxpack.api import service
    from ctxpack.exports.plain import pack_title, preview_line

    try:
        p = service.pack(pack_id)
        title, desc = escape(pack_title(p)), escape(preview_line(p))
    except Exception:  # noqa: BLE001 - an unknown or unreadable pack just gets the plain page
        return None
    tags = (f'<meta property="og:title" content="{title}" /><meta property="og:description" content="{desc}" />'
            '<meta property="og:type" content="article" /><meta property="og:site_name" content="SIGNAL - Context Packs" />'
            '<meta name="twitter:card" content="summary" />')
    html = index.read_text(encoding="utf-8")
    html = re.sub(r"<title>.*?</title>", f"<title>{title} - SIGNAL</title>", html, count=1, flags=re.S)
    html = re.sub(r'<meta name="description" content="[^"]*" />', f'<meta name="description" content="{desc}" />',
                  html, count=1)
    return html.replace("</head>", tags + "</head>", 1)
