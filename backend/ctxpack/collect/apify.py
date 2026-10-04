"""Apify actor calls for social platforms (async), with the 24 h cache.

Rules from the 2026-10-04 smoke test (catalog.yaml call_rules):
- budget checks use the EXPECTED cost; max_charge is only a ceiling, and
  some actors refuse a ceiling below min_max_charge_usd;
- actors can return more than max_items: code keeps at most `limit`;
- usageTotalUsd settles late: the recorded cost is the larger of the
  reported cost and the expected cost of what came back;
- memory_mbytes always comes from the catalog.
USE_FIXTURES=true replays tests/fixtures/tools/<actor>.json (no network).
"""

from __future__ import annotations

import hashlib
import json
import logging
import time
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from pathlib import Path
from typing import Any

from ctxpack.config import BACKEND_DIR, get_settings, load_yaml

log = logging.getLogger(__name__)

FIXTURE_DIR = BACKEND_DIR / "tests" / "fixtures" / "tools"
OK_STATUSES = {"SUCCEEDED", "TIMED-OUT"}  # a timed-out run keeps its partial items


def _cfg() -> dict[str, Any]:
    return load_yaml("modes")["collection"]


def fixture_path(actor_id: str) -> Path:
    return FIXTURE_DIR / f"{actor_id.replace('/', '__')}.json"


def expected_cost(spec: dict[str, Any], items: int) -> float:
    """Start fees + per-item price from the catalog, plus the overshoot margin."""
    price = spec.get("price_usd") or {}
    per_item = next((v for k, v in price.items() if k in (
        "result", "dataset_item", "result_item", "comment")), 0.0) or 0.0
    per_item += sum(v for k, v in price.items() if k.endswith("_per_item"))  # e.g. charged date filters
    start = sum(v for k, v in price.items() if ("start" in k or k == "init") and not k.endswith("_per_gb"))
    if "actor_start_per_gb" in price:
        start += price["actor_start_per_gb"] * spec.get("memory_mbytes", 1024) / 1024
    return round((start + per_item * items) * (1 + _cfg()["cost_margin"]), 4)


@dataclass
class ActorResult:
    actor_id: str
    items: list[dict] = field(default_factory=list)
    usd: float = 0.0
    status: str = "SUCCEEDED"
    seconds: float = 0.0
    used_fallback: bool = False
    error: str | None = None
    context: dict = field(default_factory=dict)  # e.g. parent URLs for chained comments


def _d(obj: Any) -> dict:
    return obj if isinstance(obj, dict) else obj.model_dump(by_alias=True)


async def run_actor(spec: dict[str, Any], run_input: dict[str, Any], limit: int,
                    timeout_secs: int | None = None) -> ActorResult:
    """One actor run. Never raises for actor problems: returns status + error instead."""
    actor_id = spec["id"]
    started = time.monotonic()
    if get_settings().use_fixtures:
        path = fixture_path(actor_id)
        items = json.loads(path.read_text(encoding="utf-8")) if path.exists() else []
        return ActorResult(actor_id, items[:limit], 0.0, "SUCCEEDED" if items else "NO_FIXTURE")

    from apify_client import ApifyClientAsync

    token = get_settings().apify_api_token
    client = ApifyClientAsync(token.get_secret_value() if token else None)
    ceiling = max(expected_cost(spec, limit), spec.get("min_max_charge_usd", 0.0))
    try:
        run = await client.actor(actor_id).call(
            run_input=run_input,
            max_items=limit,
            max_total_charge_usd=Decimal(str(round(ceiling, 2) or 0.01)),
            memory_mbytes=spec.get("memory_mbytes"),
            run_timeout=timedelta(seconds=timeout_secs or _cfg()["actor_timeout_secs"]),
            logger=None,
        )
    except Exception as exc:  # the API refused the run (bad input, cap too low, ...)
        # Apify's message says what was wrong with the input; it never contains the token.
        return ActorResult(actor_id, status="ERROR", seconds=time.monotonic() - started,
                           error=f"{type(exc).__name__}: {str(exc)[:200]}")
    run = _d(run)
    items = (await client.dataset(run["defaultDatasetId"]).list_items(limit=limit)).items
    items = [i for i in items if isinstance(i, dict)][:limit]
    settled = _d(await client.run(run["id"]).get() or run)
    reported = float(settled.get("usageTotalUsd") or 0.0)
    usd = max(reported, expected_cost(spec, len(items)) if items else reported)
    return ActorResult(actor_id, items, round(usd, 4), run.get("status", "?"), time.monotonic() - started)


async def run_with_fallback(attempts: list[tuple], limit: int, timeout_secs: int | None = None) -> ActorResult:
    """Try the actor, then its fallback, if it failed or returned nothing usable.

    attempts: (spec, input) or (spec, input, own_limit) when actors count items differently.
    """
    spent, result = 0.0, ActorResult("none", status="ERROR")
    for n, attempt in enumerate(attempts):
        spec, run_input = attempt[0], attempt[1]
        result = await run_actor(spec, run_input, attempt[2] if len(attempt) > 2 else limit, timeout_secs)
        spent += result.usd
        result.usd, result.used_fallback = spent, n > 0
        if result.status in OK_STATUSES and result.items:
            return result
        log.warning("actor %s gave status %s with %d items (%s)", spec["id"], result.status,
                    len(result.items), result.error or "-")
    return result


# --------------------------------------------------------------------------
# 24 h cache of CLEANED drafts (PRD DH2): never raw actor output
# --------------------------------------------------------------------------

def _cache_file(tool: str, target: str, language: str, extra: str = "") -> Path:
    day = datetime.now(timezone.utc).date().isoformat()
    key = hashlib.sha256(f"{tool}|{target.casefold()}|{language}|{day}|{extra}".encode()).hexdigest()[:24]
    return get_settings().data_path / "cache" / f"{key}.json"


def cache_get(tool: str, target: str, language: str, extra: str = "") -> dict | None:
    if get_settings().use_fixtures:  # fixture data must never be served to a real run
        return None
    path = _cache_file(tool, target, language, extra)
    if not path.exists():
        return None
    data = json.loads(path.read_text(encoding="utf-8"))
    saved = datetime.fromisoformat(data["saved_at"])
    if datetime.now(timezone.utc) - saved > timedelta(hours=_cfg()["cache_hours"]):
        return None
    return data


def cache_put(tool: str, target: str, language: str, payload: dict, extra: str = "") -> None:
    """payload must already be hashed and redacted (Draft.to_cache())."""
    if get_settings().use_fixtures:
        return
    path = _cache_file(tool, target, language, extra)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"saved_at": datetime.now(timezone.utc).isoformat(), **payload}),
                    encoding="utf-8")
