"""REST routes /api/v1 (PRD 11.1, guide B9). Same functions as the MCP server (api/service.py).

Public: featured packs, any pack by its random id (views, items, evidence,
exports), run status and live events, the JSON schema.
Run key (header X-API-Key, constant-time check): create, answer, start, stop.

Live events (SSE, guide B6) read the events table (never memory), so a
refresh, a second tab or a restarted service continues where it left off:
the browser sends the last number it saw as Last-Event-ID.
"""

from __future__ import annotations

import asyncio
import json
from typing import Any, AsyncIterator, Literal

from fastapi import APIRouter, Header, HTTPException, Query, Request
from fastapi.responses import JSONResponse, Response
from pydantic import BaseModel, Field
from sse_starlette import EventSourceResponse

from ctxpack import db, guards
from ctxpack.api import service
from ctxpack.config import load_yaml
from ctxpack.orchestrator import TERMINAL
from ctxpack.schemas.enums import Requester

router = APIRouter(prefix="/api/v1")


def _events_cfg() -> dict[str, Any]:
    return load_yaml("modes")["events"]


async def _call(fn, *args, **kwargs) -> Any:
    """Run a service function and turn its errors into plain HTTP answers."""
    try:
        result = fn(*args, **kwargs)
        return await result if asyncio.iscoroutine(result) else result
    except service.NotFound as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    except guards.GuardError as exc:
        raise HTTPException(status_code=exc.status, detail=exc.message)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))


def _key(x_api_key: str | None) -> None:
    try:
        guards.check_run_key(x_api_key)
    except guards.GuardError as exc:
        raise HTTPException(status_code=exc.status, detail=exc.message)


def _owner(x_api_key: str | None) -> None:
    try:
        guards.check_owner_key(x_api_key)
    except guards.GuardError as exc:
        raise HTTPException(status_code=exc.status, detail=exc.message)


# --------------------------------------------------------------------------
# Owner views (main run key only; not in the public API docs)
# --------------------------------------------------------------------------


@router.get("/owner/runs", include_in_schema=False)
async def owner_runs(limit: int = Query(default=50, ge=1, le=200),
                     x_api_key: str | None = Header(default=None)) -> Any:
    """Recent runs with their cost (Apify + Anthropic) and today's spend against the cap."""
    _owner(x_api_key)
    return await _call(asyncio.to_thread, service.owner_runs, limit)


@router.get("/owner/runs/{run_id}", include_in_schema=False)
async def owner_run_cost(run_id: str, x_api_key: str | None = Header(default=None)) -> Any:
    """One run's cost and where it went."""
    _owner(x_api_key)
    return await _call(asyncio.to_thread, service.owner_run_cost, run_id)


# --------------------------------------------------------------------------
# Packs (public)
# --------------------------------------------------------------------------


@router.get("/packs")
async def list_packs() -> list[dict[str, Any]]:
    """Featured packs (any other pack is readable by its link)."""
    return await asyncio.to_thread(service.featured)


@router.get("/packs/{pack_id}")
async def get_pack(pack_id: str, view: Literal["digest", "full"] = "full",
                   fields: str | None = Query(default=None, description="Comma-separated top-level sections")) -> Any:
    """A pack: digest (<= ~500 tokens) or full; fields selects sections. Guardrails and agent rules always."""
    names = [f.strip() for f in fields.split(",") if f.strip()] if fields else None
    return await _call(asyncio.to_thread, service.pack_view, pack_id, view, names)


@router.get("/packs/{pack_id}/items/{item_id}")
async def get_item(pack_id: str, item_id: str, evidence: int = Query(default=3, ge=0, le=20)) -> Any:
    """One item (e.g. TEN-01) with up to `evidence` of its posts."""
    return await _call(asyncio.to_thread, service.insight, pack_id, item_id, evidence)


@router.get("/packs/{pack_id}/evidence")
async def get_evidence(pack_id: str, q: str = "", platform: str | None = None, language: str | None = None,
                       limit: int = Query(default=20, ge=1, le=50)) -> Any:
    """Search the pack's evidence posts (untrusted quoted data)."""
    return await _call(asyncio.to_thread, service.search_evidence, pack_id, q, platform, language, limit)


@router.get("/packs/{pack_id}/inputs")
async def get_pack_inputs(pack_id: str) -> Any:
    """The brief, mode, time window, brand voice and clarifying answer behind a pack ("Run again")."""
    return await _call(asyncio.to_thread, service.pack_inputs, pack_id)


@router.get("/packs/{pack_id}/export/{kind}")
async def get_export(pack_id: str, kind: Literal["json", "md", "prompt", "skill"]) -> Response:
    """Download: json (context_pack.json), md (brief.md), prompt (prompt_block.txt) or skill (zip)."""
    data, media, name = await _call(asyncio.to_thread, service.export, pack_id, kind)
    return Response(content=data, media_type=media, headers={"Content-Disposition": f'attachment; filename="{name}"'})


@router.get("/options")
async def get_options() -> dict[str, Any]:
    """What the Ask form offers, from modes.yaml: modes with time and cost estimates, time windows."""
    from ctxpack.agent.interpret import estimate

    cfg = load_yaml("modes")
    return {"modes": {m: estimate(m).model_dump(mode="json") for m in ("quick", "standard")},
            "default_mode": cfg["default_mode"], "time_window_days_options": cfg["time_window_days_options"],
            "default_time_window_days": cfg["default_time_window_days"], "brand_voice_max_chars": 200}


@router.get("/evals")
async def get_evals() -> dict[str, Any]:
    """Evaluation results (featured/evals.json from the eval command) plus the human ratings file.
    Before the first eval it says so plainly."""
    from ctxpack.evaluation import published

    return await asyncio.to_thread(published)


@router.get("/schema")
async def get_schema() -> JSONResponse:
    """The Context Pack 1.1 JSON schema."""
    from ctxpack.schemas.pack import ContextPack

    return JSONResponse(ContextPack.model_json_schema())


# --------------------------------------------------------------------------
# Runs
# --------------------------------------------------------------------------


class RunRequest(BaseModel):
    brief: str = Field(min_length=3, max_length=2000)
    mode: Literal["quick", "standard"] = "quick"
    time_window_days: Literal[30, 90, 180, 365] | None = None
    brand_voice: str | None = Field(default=None, max_length=200)
    auto_approve: bool = False


class AnswerRequest(BaseModel):
    answer: str = Field(min_length=1, max_length=500)


class StartRequest(BaseModel):
    disabled_units: list[int] = Field(default_factory=list, description="Starting sources to switch off (0-based).")
    removed_questions: list[str] = Field(default_factory=list, description="Research question ids to drop.")


@router.post("/runs", status_code=201)
async def create_run(body: RunRequest, request: Request, x_api_key: str | None = Header(default=None)) -> Any:
    """Interpret + plan now; returns the plan (or one clarifying question). auto_approve queues it at once."""
    _key(x_api_key)
    requester = Requester.web if request.headers.get("x-requester") == "web" else Requester.api
    return await _call(service.create_run, body.brief, body.mode, body.time_window_days, body.brand_voice,
                       body.auto_approve, requester)


@router.post("/runs/{run_id}/answer")
async def answer(run_id: str, body: AnswerRequest, x_api_key: str | None = Header(default=None)) -> Any:
    """Answer the clarifying question; returns the plan."""
    _key(x_api_key)
    return await _call(service.answer_question, run_id, body.answer)


@router.post("/runs/{run_id}/start")
async def start(run_id: str, body: StartRequest | None = None, x_api_key: str | None = Header(default=None)) -> Any:
    """Approve the plan (optionally with sources switched off) - the run joins the queue."""
    _key(x_api_key)
    body = body or StartRequest()
    return await _call(asyncio.to_thread, service.start_run, run_id, body.disabled_units, body.removed_questions)


@router.post("/runs/{run_id}/stop")
async def stop(run_id: str, x_api_key: str | None = Header(default=None)) -> Any:
    """Stop: a queued run is cancelled; a working run is packaged from what exists."""
    _key(x_api_key)
    return await _call(asyncio.to_thread, service.stop_run, run_id)


@router.get("/runs/{run_id}")
async def get_run(run_id: str) -> Any:
    """Status, stage, queue position, plan and pack_id when done. No secrets, no costs."""
    return await _call(asyncio.to_thread, service.run_status, run_id)


async def event_stream(run_id: str, after: int = 0, poll_secs: float | None = None) -> AsyncIterator[dict[str, Any]]:
    """Every event after `after`, in order; ends once the run is finished and all events are sent.

    The run's status is read BEFORE its events, so an event written just
    before the run finished is always sent. A run that is gone from the
    database replays from its pack's copied events.
    """
    poll = _events_cfg()["poll_secs"] if poll_secs is None else poll_secs
    last = after
    run = await asyncio.to_thread(db.get_run, run_id)
    if run is None:
        p = await asyncio.to_thread(db.get_pack_for_run, run_id)
        for e in (p or {}).get("events", []):
            if e["seq"] > last:
                yield {"id": str(e["seq"]), "event": e["type"],
                       "data": json.dumps({"seq": e["seq"], **e["payload"]}, ensure_ascii=False)}
        return
    while True:
        run = await asyncio.to_thread(db.get_run, run_id)
        rows = await asyncio.to_thread(db.get_events, run_id, last)
        for row in rows:
            last = row.seq
            yield {"id": str(row.seq), "event": row.type.value,
                   "data": json.dumps({"seq": row.seq, **row.payload}, ensure_ascii=False)}
        if rows:
            continue
        if run is None or run.status in TERMINAL:
            return
        await asyncio.sleep(poll)


def _last_id(value: str | None) -> int:
    try:
        return max(0, int(value)) if value else 0
    except ValueError:
        return 0


@router.get("/runs/{run_id}/events")
async def run_events(run_id: str, after: int = Query(default=0, ge=0),
                     last_event_id: str | None = Header(default=None)) -> EventSourceResponse:
    """Live events for one run (SSE). Reconnects resume after Last-Event-ID (or ?after=N)."""
    exists = await asyncio.to_thread(db.get_run, run_id) or await asyncio.to_thread(db.get_pack_for_run, run_id)
    if not exists:
        raise HTTPException(status_code=404, detail="run not found")
    start_at = max(after, _last_id(last_event_id))
    return EventSourceResponse(event_stream(run_id, start_at), ping=_events_cfg()["ping_secs"])
