"""REST routes. Step 2.3: live run events (SSE, guide B6).

The stream reads the events table (never memory), so a refresh, a second
tab or a restarted service continues where it left off: the browser sends
the last number it saw as Last-Event-ID and gets every later event.
"""

from __future__ import annotations

import asyncio
import json
from typing import Any, AsyncIterator

from fastapi import APIRouter, Header, HTTPException, Query
from sse_starlette import EventSourceResponse

from ctxpack import db
from ctxpack.config import load_yaml
from ctxpack.orchestrator import TERMINAL

router = APIRouter(prefix="/api")


def _events_cfg() -> dict[str, Any]:
    return load_yaml("modes")["events"]


async def event_stream(run_id: str, after: int = 0, poll_secs: float | None = None) -> AsyncIterator[dict[str, Any]]:
    """Every event after `after`, in order; ends once the run is finished and all events are sent.

    The run's status is read BEFORE its events, so an event written just
    before the run finished is always sent.
    """
    poll = _events_cfg()["poll_secs"] if poll_secs is None else poll_secs
    last = after
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
    """Live events for one run. Reconnects resume after Last-Event-ID (or ?after=N)."""
    if await asyncio.to_thread(db.get_run, run_id) is None:
        raise HTTPException(status_code=404, detail="run not found")
    start = max(after, _last_id(last_event_id))
    return EventSourceResponse(event_stream(run_id, start), ping=_events_cfg()["ping_secs"])
