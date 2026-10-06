"""demo-check (guide Step 5.5): one command before the demo, every line green or a reason.

Live service: /ping, /health (database, new runs accepted today), featured packs, MCP.
Around it: last keep-alive run (public GitHub API), the static mirror (GitHub Pages).
Paid, tiny: one Anthropic call (< $0.001) and an Apify account call (free).
Security: the real RUN_KEY value is searched for in the tracked files, the whole git history,
the README, both web builds and the live web app - compared here, NEVER printed - and gitleaks
scans the full history.
"""

from __future__ import annotations

import json
import re
import subprocess
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Callable

import httpx

from ctxpack.config import REPO_DIR, get_settings

PUBLIC_URL = "https://signal-l2w5.onrender.com"
KEEPALIVE_MAX_MIN = 15
TIMEOUT = 90  # a sleeping free service takes up to a minute to wake


@dataclass
class Check:
    name: str
    ok: bool
    detail: str


def _reason(exc: Exception) -> str:
    """Error type plus HTTP status - never a message that could echo a URL with credentials."""
    status = getattr(getattr(exc, "response", None), "status_code", None)
    return type(exc).__name__ + (f" (HTTP {status})" if status else "")


def run_check(name: str, fn: Callable[[], tuple[bool, str]]) -> Check:
    try:
        ok, detail = fn()
    except Exception as exc:  # one broken check never stops the others
        ok, detail = False, _reason(exc)
    return Check(name, ok, detail)


def github_repo() -> str:
    """owner/name from the origin remote (public repo)."""
    url = subprocess.run(["git", "remote", "get-url", "origin"], cwd=REPO_DIR, capture_output=True, text=True,
                         check=True).stdout.strip()
    m = re.search(r"github\.com[:/]([^/]+/[^/.]+)", url)
    if not m:
        raise ValueError("origin is not a GitHub remote")
    return m.group(1)


def mirror_url(repo: str) -> str:
    owner, name = repo.split("/")
    return f"https://{owner}.github.io/{name}/"


def featured_ids() -> set[str]:
    return {json.loads(p.read_text(encoding="utf-8"))["pack_id"] for p in (REPO_DIR / "featured").glob("*.json")
            if not p.stem.startswith("evals")}


# --------------------------------------------------------------------------
# Live service
# --------------------------------------------------------------------------


def check_ping(http: httpx.Client, url: str) -> tuple[bool, str]:
    r = http.get(f"{url}/ping")
    return r.status_code == 200 and r.text == "ok", f"HTTP {r.status_code}"


def check_health(http: httpx.Client, url: str) -> tuple[bool, str]:
    b = http.get(f"{url}/health").json()
    return bool(b.get("ok") and b.get("database")), f"version {b.get('version')}, database {b.get('database')}"


def check_accepting(http: httpx.Client, url: str) -> tuple[bool, str]:
    accepting = http.get(f"{url}/health").json().get("accepting_runs")
    if accepting is None:
        return False, "the live service does not report it yet (deploy this version)"
    return bool(accepting), "new runs accepted today" if accepting else "daily spend cap reached: runs are refused"


def check_featured(http: httpx.Client, url: str) -> tuple[bool, str]:
    live = {p["pack_id"] for p in http.get(f"{url}/api/v1/packs").json()}
    want = featured_ids()
    missing, extra = want - live, live - want
    detail = f"{len(live)} live" + (f"; missing {sorted(missing)}" if missing else "") + \
        (f"; not in featured/ {sorted(extra)}" if extra else "")
    return not missing and not extra, detail


def check_mcp(http: httpx.Client, url: str) -> tuple[bool, str]:
    body = {"jsonrpc": "2.0", "id": 1, "method": "initialize",
            "params": {"protocolVersion": "2025-06-18", "capabilities": {},
                       "clientInfo": {"name": "demo-check", "version": "1"}}}
    r = http.post(f"{url}/mcp", json=body, headers={"Accept": "application/json, text/event-stream"})
    return r.status_code == 200 and "serverInfo" in r.text, f"HTTP {r.status_code}, initialize " + \
        ("answered" if "serverInfo" in r.text else "not answered")


# --------------------------------------------------------------------------
# Around the service
# --------------------------------------------------------------------------


def check_keepalive(http: httpx.Client, repo: str) -> tuple[bool, str]:
    r = http.get(f"https://api.github.com/repos/{repo}/actions/workflows/keepalive.yml/runs",
                 params={"per_page": 1}, headers={"Accept": "application/vnd.github+json"})
    runs = r.json().get("workflow_runs", [])
    if not runs:
        return False, "no keep-alive runs yet"
    last = runs[0]
    age = (datetime.now(UTC) - datetime.fromisoformat(last["created_at"].replace("Z", "+00:00"))).total_seconds() / 60
    ok = age < KEEPALIVE_MAX_MIN and last.get("conclusion") in ("success", None)
    return ok, f"last run {round(age)} min ago, {last.get('conclusion') or last.get('status')}"


def check_mirror(http: httpx.Client, repo: str) -> tuple[bool, str]:
    base = mirror_url(repo)
    page = http.get(base)
    if page.status_code != 200:
        return False, f"{base} HTTP {page.status_code}"
    ids = {p["pack_id"] for p in http.get(f"{base}data/packs.json").json()}
    missing = featured_ids() - ids
    return not missing, f"{base} with {len(ids)} packs" + (f"; missing {sorted(missing)}" if missing else "")


# --------------------------------------------------------------------------
# Security: the real run key must appear nowhere (compared here, never printed)
# --------------------------------------------------------------------------


def _files_contain(paths: list[Path], needle: bytes) -> list[str]:
    hits = []
    for p in paths:
        try:
            if p.is_file() and needle in p.read_bytes():
                hits.append(str(p.relative_to(REPO_DIR)))
        except OSError:
            continue
    return hits


def check_key_absent(http: httpx.Client, url: str) -> tuple[bool, str]:
    s = get_settings()
    if not s.is_set("RUN_KEY"):
        return False, "RUN_KEY not set locally: nothing to compare (run the doctor command)"
    key = s.run_key.get_secret_value().strip()
    needle = key.encode()
    places: list[str] = []
    tracked = subprocess.run(["git", "ls-files", "-z"], cwd=REPO_DIR, capture_output=True, check=True).stdout
    files = [REPO_DIR / f.decode() for f in tracked.split(b"\0") if f]
    places += [f"file {h}" for h in _files_contain(files, needle)]
    history = subprocess.run(["git", "log", "--all", "-p", "--no-color", "--no-ext-diff"], cwd=REPO_DIR,
                             capture_output=True, check=True).stdout
    if needle in history:
        places.append("git history")
    for build in ("frontend/dist", "mirror"):
        root = REPO_DIR / build
        places += [f"build {h}" for h in _files_contain(list(root.rglob("*")) if root.is_dir() else [], needle)]
    home = http.get(url)
    pages = [home.text] + [http.get(url + src).text for src in re.findall(r'src="(/assets/[^"]+\.js)"', home.text)]
    if any(key in t for t in pages):
        places.append("live web app")
    del key, needle
    return not places, "not found in files, history, README, builds or the live app" if not places else \
        "FOUND in: " + ", ".join(places) + " - rotate the key in Render and remove it"


def check_gitleaks() -> tuple[bool, str]:
    r = subprocess.run(["gitleaks", "git", "--redact", "--no-banner", "--log-level", "error", str(REPO_DIR)],
                       capture_output=True, text=True)
    return r.returncode == 0, "full history: no leaks" if r.returncode == 0 else "gitleaks found something: run " \
        "'gitleaks git --redact -v' and read the report"


# --------------------------------------------------------------------------


def run_all(url: str = PUBLIC_URL, paid: bool = True) -> list[Check]:
    from ctxpack import cli, db

    url = url.rstrip("/")
    s = get_settings()
    out: list[Check] = []
    with httpx.Client(timeout=TIMEOUT, follow_redirects=True) as http:
        repo = github_repo()
        out.append(run_check("live /ping", lambda: check_ping(http, url)))
        out.append(run_check("live /health", lambda: check_health(http, url)))
        out.append(run_check("live runs accepted (daily cap)", lambda: check_accepting(http, url)))
        out.append(run_check("featured packs live", lambda: check_featured(http, url)))
        out.append(run_check("MCP reachable", lambda: check_mcp(http, url)))
        out.append(run_check(f"keep-alive < {KEEPALIVE_MAX_MIN} min ago", lambda: check_keepalive(http, repo)))
        out.append(run_check("static mirror", lambda: check_mirror(http, repo)))
        if paid:
            out.append(run_check("Anthropic (tiny call)", lambda: cli._check_anthropic(s)))
            out.append(run_check("Apify account", lambda: cli._check_apify(s)))

        def local_spend() -> tuple[bool, str]:
            db.init_engine()
            spent, cap = db.spend_today(), s.daily_spend_cap_usd
            return spent < cap, f"${spent:.2f} of ${cap:.2f} today (local database; the live cap is the line above)"

        out.append(run_check("spend today vs cap (local)", local_spend))
        out.append(run_check("security: run key nowhere", lambda: check_key_absent(http, url)))
        out.append(run_check("security: gitleaks", check_gitleaks))
    return out
