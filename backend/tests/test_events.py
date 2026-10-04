"""Live events over SSE (guide B6): read from the events table, resumable with Last-Event-ID."""

import asyncio
import json

from fastapi.testclient import TestClient

from ctxpack import db
from ctxpack.api.main import app
from ctxpack.api.routes import event_stream
from ctxpack.schemas.enums import EventType, RunStatus

client = TestClient(app)  # no "with": the startup tasks and worker do not run


def add_events(run_id: str, n: int) -> None:
    for i in range(n):
        db.append_event(run_id, EventType.counters, {"collected": i})


async def take(stream, n: int) -> list[int]:
    seqs = []
    async for message in stream:
        seqs.append(int(message["id"]))
        if len(seqs) == n:
            break
    return seqs


async def test_disconnect_and_reconnect_with_last_event_id_misses_nothing(temp_db):
    run = db.create_run("Gen Z and meal prep")
    db.set_status(run.id, RunStatus.running)
    add_events(run.id, 5)

    first = event_stream(run.id, 0, poll_secs=0.01)
    seen = await take(first, 3)
    await first.aclose()  # the browser drops the connection after event 3

    add_events(run.id, 3)  # events keep coming while it is away (4..8 not yet seen)
    second = event_stream(run.id, after=seen[-1], poll_secs=0.01)
    reader = asyncio.create_task(take(second, 100))
    await asyncio.sleep(0.05)
    add_events(run.id, 2)  # and while it is connected again
    db.set_status(run.id, RunStatus.complete)
    seen += await asyncio.wait_for(reader, 5)

    assert seen == list(range(1, 11))  # every event once, in order


def sse_ids(text: str) -> list[int]:
    return [int(line.split(":", 1)[1]) for line in text.splitlines() if line.startswith("id:")]


def test_http_stream_resumes_after_last_event_id(temp_db):
    run = db.create_run("Gen Z and meal prep")
    add_events(run.id, 6)
    db.set_status(run.id, RunStatus.complete)

    full = client.get(f"/api/runs/{run.id}/events")
    assert full.status_code == 200 and full.headers["content-type"].startswith("text/event-stream")
    assert sse_ids(full.text) == [1, 2, 3, 4, 5, 6]
    assert "event: counters" in full.text
    data = [json.loads(l[5:]) for l in full.text.splitlines() if l.startswith("data:")]
    assert data[0] == {"seq": 1, "collected": 0}

    resumed = client.get(f"/api/runs/{run.id}/events", headers={"Last-Event-ID": "4"})
    assert sse_ids(resumed.text) == [5, 6]
    assert sse_ids(client.get(f"/api/runs/{run.id}/events?after=5").text) == [6]


def test_unknown_run_is_404(temp_db):
    assert client.get("/api/runs/run_nope/events").status_code == 404
