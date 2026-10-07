"""REST /api/v1, guards, queue, MCP and featured packs (Step 3.7). USE_FIXTURES + LLM_FAKE: no money.

The run key used here is a test value set only inside these tests.
"""

import io
import json
import zipfile
from contextlib import asynccontextmanager
from pathlib import Path

import httpx
import pytest
from fastapi.testclient import TestClient
from starlette.applications import Starlette
from starlette.routing import Mount

from ctxpack import db, mcp_server, worker
from ctxpack.api import service
from ctxpack.api.main import app
from ctxpack.config import get_settings
from ctxpack.schemas.enums import RunStatus
from ctxpack.schemas.pack import ContextPack
from tests.test_cluster import fake  # noqa: F401  (fixture)
from tests.test_worker import offline  # noqa: F401  (fixture)

FIXTURE = Path(__file__).parent / "fixtures" / "example_pack.json"
TEST_KEY = "test-run-key-not-a-secret"
client = TestClient(app)  # no "with": the startup tasks (real DATABASE_URL) never run here


@pytest.fixture
def api(offline, monkeypatch):  # noqa: F811
    monkeypatch.setenv("RUN_KEY", TEST_KEY)
    get_settings.cache_clear()
    pack = ContextPack.model_validate_json(FIXTURE.read_text(encoding="utf-8"))
    db.save_pack(pack, featured=True)
    yield pack
    get_settings.cache_clear()


KEY = {"X-API-Key": TEST_KEY}


# --- packs (public) -------------------------------------------------------------------

def test_featured_packs_and_views_need_no_key(api):
    listed = client.get("/api/v1/packs").json()
    assert [p["pack_id"] for p in listed] == [api.pack_id]
    digest = client.get(f"/api/v1/packs/{api.pack_id}?view=digest").json()
    assert digest["guardrails"] and digest["instructions_for_agents"] and "five_truths" in digest
    part = client.get(f"/api/v1/packs/{api.pack_id}?fields=tensions,voice").json()
    assert {"tensions", "voice", "guardrails", "instructions_for_agents"} <= set(part) and "evidence" not in part
    assert client.get(f"/api/v1/packs/{api.pack_id}?fields=nonsense").status_code == 400
    assert client.get("/api/v1/packs/pk_doesnotexist").status_code == 404


def test_items_evidence_exports_and_schema(api):
    item_id = api.tensions[0].id
    item = client.get(f"/api/v1/packs/{api.pack_id}/items/{item_id}?evidence=2").json()
    assert item["item"]["id"] == item_id and 1 <= len(item["evidence"]) <= 2 and "untrusted" in item["note"]
    assert client.get(f"/api/v1/packs/{api.pack_id}/items/XYZ-99").status_code == 404
    word = api.evidence[0].text.split()[0]
    found = client.get(f"/api/v1/packs/{api.pack_id}/evidence", params={"q": word}).json()
    assert found["total"] >= 1 and word.casefold() in found["evidence"][0]["text"].casefold()
    md = client.get(f"/api/v1/packs/{api.pack_id}/export/md")
    assert md.status_code == 200 and md.text.startswith("# Context Pack") and "brief.md" in md.headers[
        "content-disposition"]
    skill = client.get(f"/api/v1/packs/{api.pack_id}/export/skill")
    assert any(n.endswith("/SKILL.md") for n in zipfile.ZipFile(io.BytesIO(skill.content)).namelist())
    assert client.get(f"/api/v1/packs/{api.pack_id}/export/xlsx").status_code == 422
    assert client.get("/api/v1/schema").json()["title"] == "ContextPack"


# --- runs: key, plan, queue -------------------------------------------------------------

def test_starting_runs_needs_the_key(api, monkeypatch):
    body = {"brief": "Gen Z and meal prep"}
    assert client.post("/api/v1/runs", json=body).status_code == 401
    assert client.post("/api/v1/runs", json=body, headers={"X-API-Key": "wrong"}).status_code == 401
    assert client.post("/api/v1/runs/run_x/start", headers={"X-API-Key": "wrong"}).status_code == 401
    monkeypatch.setenv("RUN_KEY", "")  # empty on purpose: the owner's local key is never used in tests
    monkeypatch.setenv("LLM_FAKE", "false")  # a real server (not the offline demo): runs switched off
    get_settings.cache_clear()
    assert client.post("/api/v1/runs", json=body, headers=KEY).status_code == 503   # refused before any call


def test_plan_then_start_then_the_queue(api):
    made = client.post("/api/v1/runs", json={"brief": "Gen Z and meal prep", "mode": "quick"}, headers=KEY)
    assert made.status_code == 201
    run = made.json()
    assert run["status"] == "awaiting_approval" and run["plan"] and run["estimate"]["max_usd"] > 0
    assert TEST_KEY not in made.text                                         # no endpoint returns a secret
    started = client.post(f"/api/v1/runs/{run['run_id']}/start", json={"disabled_units": [0]}, headers=KEY).json()
    assert started["status"] == "queued" and started["queue_position"] == 1
    assert started["plan"]["starting_units"][0]["enabled"] is False
    second = client.post("/api/v1/runs", json={"brief": "snacks", "auto_approve": True}, headers=KEY).json()
    assert second["status"] == "queued" and second["queue_position"] == 2            # never "busy": it queues
    again = client.post(f"/api/v1/runs/{run['run_id']}/start", headers=KEY)
    assert again.status_code == 400                                                   # already queued
    assert client.get(f"/api/v1/runs/{run['run_id']}").json()["queue_position"] == 1  # public status


def test_queue_full_and_daily_cap_refuse_politely(api, monkeypatch):
    from ctxpack.config import load_yaml

    monkeypatch.setattr("ctxpack.guards.load_yaml", lambda name: {**load_yaml(name), "queue_max": 1})
    assert client.post("/api/v1/runs", json={"brief": "a", "auto_approve": True}, headers=KEY).status_code == 422
    assert client.post("/api/v1/runs", json={"brief": "Gen Z", "auto_approve": True}, headers=KEY).status_code == 201
    full = client.post("/api/v1/runs", json={"brief": "Gen Z", "auto_approve": True}, headers=KEY)
    assert full.status_code == 429 and "queue full" in full.json()["detail"]
    monkeypatch.setenv("DAILY_SPEND_CAP_USD", "1")
    get_settings.cache_clear()
    db.add_spend(llm_usd=1.0)
    capped = client.post("/api/v1/runs", json={"brief": "Gen Z"}, headers=KEY)
    assert capped.status_code == 429 and "research allowance" in capped.json()["detail"]
    assert client.get("/api/v1/packs").status_code == 200                            # featured packs still work


async def test_two_queued_runs_start_by_themselves_one_after_the_other(api):
    first = await service.create_run("Gen Z and meal prep", auto_approve=True)
    second = await service.create_run("Gen Z and meal prep", auto_approve=True)
    assert (first["queue_position"], second["queue_position"]) == (1, 2)
    assert await worker.run_next() == first["run_id"]
    assert service.run_status(second["run_id"])["queue_position"] == 1
    assert await worker.run_next() == second["run_id"]
    for r in (first, second):
        status = service.run_status(r["run_id"])
        assert status["status"] == "complete" and status["pack_id"]


async def test_clarifying_question_then_answer(api, monkeypatch):
    from ctxpack.agent import interpret as ip
    from ctxpack.schemas.plan import ClarifyingQuestion, PlanResult

    real = ip.interpret

    async def ask_first(brief, **kw):
        out = await real(brief, **kw)
        if kw.get("clarification") is None and kw.get("allow_question"):
            out.result = PlanResult(interpretation=out.result.interpretation, plan=None,
                                    clarifying_question=ClarifyingQuestion(
                                        question="Which country?", options=["NL", "DE", "global"]))
        return out

    monkeypatch.setattr(ip, "interpret", ask_first)
    run = await service.create_run("snacks")
    assert run["status"] == "needs_clarification" and run["clarifying_question"]["question"] == "Which country?"
    with pytest.raises(ValueError):
        service.start_run(run["run_id"])
    planned = await service.answer_question(run["run_id"], "NL")
    assert planned["status"] == "awaiting_approval" and planned["plan"] and planned["clarifying_question"] is None


def test_events_replay_from_the_pack_when_the_run_is_gone(api):
    pack = api.model_dump(mode="json")
    pack["pack_id"] = "pk_replaytest01"
    db.save_pack(ContextPack.model_validate(pack), run_id="run_gone")
    text = client.get("/api/v1/runs/run_gone/events").text
    assert text.count("id: ") == len(api.events) and len(api.events) > 0


# --- MCP ----------------------------------------------------------------------------------

async def test_mcp_tools_read_without_a_key_and_refuse_create_without_one(api):
    from mcp.server.mcpserver.exceptions import ToolError

    listed = await mcp_server.mcp.call_tool("list_packs", {})
    assert api.pack_id in json.dumps(listed.structured_content)
    digest = await mcp_server.mcp.call_tool("get_pack_view", {"pack_id": api.pack_id})
    assert "instructions_for_agents" in json.dumps(digest.structured_content)
    hit = await mcp_server.mcp.call_tool("get_insight", {"pack_id": api.pack_id, "item_id": api.tensions[0].id})
    assert api.tensions[0].id in json.dumps(hit.structured_content)
    with pytest.raises(ToolError, match="not found"):
        await mcp_server.mcp.call_tool("get_pack_view", {"pack_id": "pk_nope12345"})
    with pytest.raises(ToolError):
        await mcp_server.mcp.call_tool("create_context_pack", {"brief": "Gen Z and meal prep"})


@asynccontextmanager
async def mcp_http():
    """A fresh MCP app (each session manager starts once) on an in-memory HTTP client."""
    mcp_app = mcp_server.http_app()
    holder = Starlette(routes=[Mount("/mcp", mcp_app)])
    async with mcp_server.mcp.session_manager.run():
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=holder), base_url="http://testserver") as c:
            yield c


def rpc(method: str, params: dict, n: int = 1) -> dict:
    return {"jsonrpc": "2.0", "id": n, "method": method, "params": params}


HEADERS = {"Accept": "application/json, text/event-stream", "Content-Type": "application/json",
           "MCP-Protocol-Version": "2025-06-18"}
INIT = {"protocolVersion": "2025-06-18", "capabilities": {}, "clientInfo": {"name": "test", "version": "1"}}


async def test_mcp_over_http_reads_freely_and_checks_the_key_header(api):
    async with mcp_http() as c:
        init = await c.post("/mcp/", json=rpc("initialize", INIT), headers=HEADERS)
        assert init.status_code == 200, init.text
        tools = await c.post("/mcp/", json=rpc("tools/list", {}, 2), headers=HEADERS)
        names = {t["name"] for t in tools.json()["result"]["tools"]}
        assert names == {"list_packs", "get_pack_view", "get_insight", "search_evidence", "create_context_pack",
                         "get_pack_status"}
        listed = await c.post("/mcp/", json=rpc("tools/call", {"name": "list_packs", "arguments": {}}, 3),
                              headers=HEADERS)
        assert api.pack_id in listed.text
        refused = await c.post("/mcp/", json=rpc("tools/call", {"name": "get_pack_status",
                                                                "arguments": {"run_id": "run_x"}}, 4),
                               headers=HEADERS)
        assert refused.json()["result"]["isError"] is True and "run key" in refused.text
        allowed = await c.post("/mcp/", json=rpc("tools/call", {"name": "get_pack_status",
                                                                "arguments": {"run_id": "run_x"}}, 5),
                               headers={**HEADERS, "X-API-Key": TEST_KEY})
        assert "run key" not in allowed.text and "not found" in allowed.text        # key accepted; no such run
        evil = await c.post("/mcp/", json=rpc("tools/list", {}, 6), headers={**HEADERS, "Host": "evil.example"})
        assert evil.status_code in (400, 421)                                       # DNS-rebinding protection


def test_mcp_is_mounted_at_slash_mcp_without_redirect():
    paths = [getattr(r, "path", "") for r in app.routes]
    assert "/mcp" in paths


# --- featured packs ---------------------------------------------------------------------------

def test_feature_writes_public_files_without_costs_and_refuses_private_data(api, tmp_path):
    from ctxpack.exports.featured import feature, privacy_problems

    pack = api.model_dump(mode="json")
    pack["events"].append({"seq": 999, "type": "cost", "payload": {"llm_usd": 1.0},
                           "created_at": pack["generated_at"]})
    pack["coverage"]["decision_log"].append({"seq": 99, "tool": "search_reddit", "source_unit": None,
                                             "reason": "r", "result_summary": "limit_reached (this call ~0.17 USD)"})
    assert privacy_problems(pack)                                    # a cost amount is not publishable as is
    paths = feature(pack, tmp_path / "featured", tmp_path / "examples")
    saved = json.loads(paths["featured"].read_text(encoding="utf-8"))
    assert all(e["type"] != "cost" for e in saved["events"]) and "documents" not in saved
    assert "USD" not in paths["featured"].read_text(encoding="utf-8")
    assert paths["example_md"].exists() and (paths["skill"] / "SKILL.md").exists()
    ContextPack.model_validate(saved)

    for leak in ("mail me at jan.jansen@example.nl", "bel 06-12345678", "volg @snackqueen",
                 "zie https://www.instagram.com/snackqueen", "u/snackfan99 zegt"):
        bad = json.loads(json.dumps(pack))
        bad["tensions"][0]["claim"] = leak
        assert privacy_problems(bad), leak
        with pytest.raises(ValueError, match="privacy check failed"):
            feature(bad, tmp_path / "f2", tmp_path / "e2")
        assert not (tmp_path / "f2").exists()                                      # nothing written
    long_quote = json.loads(json.dumps(pack))
    long_quote["evidence"][0]["text"] = "x" * 281
    assert any("over 280" in p for p in privacy_problems(long_quote))


async def test_redact_run_fixes_names_in_documents_draft_and_packs(fake, temp_db):  # noqa: F811
    from ctxpack.maintenance import redact_run
    from ctxpack.synthesis import finalize
    from tests.test_pack import verified_run_id

    run_id = await verified_run_id()
    docs = db.get_documents(run_id)
    name_doc = docs[0].model_copy(update={"text": docs[0].text + " Mijn man Hans vindt het ook.",
                                          "text_en": "My husband Hans agrees."})
    db.save_documents([name_doc])
    out = await finalize.package_run(run_id)
    p = db.get_pack(out.pack_id)
    p["evidence"][0]["text"] += " Mijn man Hans zegt: lekker"  # appended: earlier quotes stay valid
    p["tensions"][0]["quotes"] = [{"evidence_id": p["evidence"][0]["id"], "text": "Mijn man Hans zegt"},
                                  {"evidence_id": p["evidence"][0]["id"], "text": "Hans zegt"}]
    db.save_pack(ContextPack.model_validate(p), run_id=run_id)

    p = db.get_pack(out.pack_id)
    p["evidence"][1]["text_fragment_url"] = "https://forum.example.nl/t/1#:~:text=Weet%20je,Hans%20en%20de%20kids"
    db.save_pack(ContextPack.model_validate(p), run_id=run_id)

    rep = redact_run(run_id)
    assert rep.documents_changed == 1 and rep.packs_saved and rep.quotes_removed == 1
    stored = next(d for d in db.get_documents(run_id) if d.id == name_doc.id)
    assert "Hans" not in stored.text and "[name]" in stored.text and "Hans" not in stored.text_en
    saved = db.get_pack(out.pack_id)
    assert "Hans" not in json.dumps(saved) and saved["evidence"][1]["text_fragment_url"] is None
    assert saved["tensions"][0]["quotes"] == [{"evidence_id": saved["evidence"][0]["id"],
                                               "text": "Mijn man [name] zegt"}]   # same rule on both sides
    ContextPack.model_validate(saved)


def test_options_come_from_config(api):
    from ctxpack.config import load_yaml

    opts = client.get("/api/v1/options").json()
    cfg = load_yaml("modes")
    assert opts["time_window_days_options"] == cfg["time_window_days_options"]
    assert opts["default_time_window_days"] == cfg["default_time_window_days"]
    assert opts["modes"]["quick"]["typical_minutes"] == cfg["modes"]["quick"]["typical_minutes"]
    assert opts["modes"]["standard"]["max_usd"] > opts["modes"]["quick"]["max_usd"]


def test_snacks_gets_one_question_in_fake_mode_and_agents_never_do(api):
    run = client.post("/api/v1/runs", json={"brief": "snacks"}, headers=KEY).json()
    assert run["status"] == "needs_clarification" and len(run["clarifying_question"]["options"]) >= 3
    answered = client.post(f"/api/v1/runs/{run['run_id']}/answer", json={"answer": "Netherlands, young adults"},
                           headers=KEY).json()
    assert answered["status"] == "awaiting_approval" and answered["plan"]
    agent = client.post("/api/v1/runs", json={"brief": "snacks", "auto_approve": True}, headers=KEY).json()
    assert agent["status"] == "queued" and agent["clarifying_question"] is None   # agents: never a question
    wrong = client.post("/api/v1/runs", json={"brief": "snacks"}, headers={"X-API-Key": "nope"})
    assert wrong.status_code == 401 and "run key" in wrong.json()["detail"]


async def test_run_status_shows_the_agents_verdicts_once_collection_is_done(api):
    run = await service.create_run("Gen Z and meal prep", auto_approve=True)
    assert service.run_status(run["run_id"])["collection"] is None          # nothing collected yet
    await worker.run_next()
    status = client.get(f"/api/v1/runs/{run['run_id']}").json()
    col = status["collection"]
    assert col["sources_used"] and {"source_unit", "reason"} <= set(col["sources_used"][0])
    assert "finish_reason" in col and TEST_KEY not in json.dumps(status)


def test_clean_text_and_escape_debris_in_new_terms():
    from ctxpack.maintenance import RedactReport, clean_text, redact_tree

    assert clean_text(r"\ud83d\udc40 lekker ![:P](http://i.fok.nl/s/puh2.gif)") == ("👀 lekker :P", True)
    rep = RedactReport()
    tree = redact_tree({"payload": {"new_terms": ["chips", "ud83d", "ud83e udd63", "lekker"]}}, rep)
    assert tree["payload"]["new_terms"] == ["chips", "lekker"] and rep.strings_changed == 2


def test_offline_demo_needs_no_keys(monkeypatch, tmp_path):
    """A fresh clone without .env (README): fixtures + fake model -> local SQLite, demo salt, no run key."""
    from ctxpack import guards
    from ctxpack.collect.cleaning import hash_author  # noqa: F401
    for name in ("DATABASE_URL", "RUN_KEY", "AUTHOR_HASH_SALT"):
        monkeypatch.setenv(name, "")
    monkeypatch.setenv("USE_FIXTURES", "true")
    monkeypatch.setenv("LLM_FAKE", "true")
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    get_settings.cache_clear()
    try:
        assert get_settings().offline
        engine = db.init_engine()
        assert str(engine.url).startswith("sqlite") and (tmp_path / "local.db").name in str(engine.url)
        guards.check_run_key(None)                                       # no key needed offline
        monkeypatch.setenv("LLM_FAKE", "false")                          # anything paid possible -> key needed
        get_settings.cache_clear()
        with pytest.raises(guards.GuardError):
            guards.check_run_key(None)
    finally:
        db.get_engine().dispose()
        db._engine = None
        get_settings.cache_clear()


def test_guest_key_gives_temporary_access_and_deleting_it_revokes(api, monkeypatch):
    body = {"brief": "Gen Z and meal prep"}
    guest = {"X-API-Key": "guest-key-for-a-tester-only"}             # test value, not a secret
    assert client.post("/api/v1/runs", json=body, headers=guest).status_code == 401   # not set yet
    monkeypatch.setenv("GUEST_RUN_KEY", "guest-key-for-a-tester-only")
    get_settings.cache_clear()
    made = client.post("/api/v1/runs", json=body, headers=guest)
    assert made.status_code == 201 and "guest-key-for-a-tester-only" not in made.text
    assert client.post("/api/v1/runs", json=body, headers=KEY).status_code == 201       # main key unaffected
    monkeypatch.setenv("GUEST_RUN_KEY", "")                          # revoke: delete it in Render
    get_settings.cache_clear()
    assert client.post("/api/v1/runs", json=body, headers=guest).status_code == 401
    assert client.post("/api/v1/runs", json=body, headers=KEY).status_code == 201
    get_settings.cache_clear()


def test_short_guest_key_is_ignored_and_guest_alone_opens_nothing(api, monkeypatch):
    body = {"brief": "Gen Z and meal prep"}
    monkeypatch.setenv("GUEST_RUN_KEY", "short")
    get_settings.cache_clear()
    assert client.post("/api/v1/runs", json=body, headers={"X-API-Key": "short"}).status_code == 401
    monkeypatch.setenv("GUEST_RUN_KEY", "guest-key-for-a-tester-only")
    monkeypatch.setenv("RUN_KEY", "")
    monkeypatch.setenv("LLM_FAKE", "false")                         # a real server, not the offline demo
    get_settings.cache_clear()
    r = client.post("/api/v1/runs", json=body, headers={"X-API-Key": "guest-key-for-a-tester-only"})
    assert r.status_code == 503                                      # no main key: runs are off for everyone
    get_settings.cache_clear()


def test_owner_cost_view_needs_the_main_key_not_the_guest_key(api, monkeypatch):
    made = client.post("/api/v1/runs", json={"brief": "Gen Z and meal prep"}, headers=KEY).json()
    db.update_run(made["run_id"], cost_apify_usd=0.5, cost_llm_usd=1.25,
                  cost_breakdown={"anthropic": {"reasoner/plan": {"calls": 1, "usd": 1.25}},
                                  "apify": {"some/actor": {"runs": 2, "usd": 0.5}}})
    assert client.get("/api/v1/owner/runs").status_code == 401                         # no key
    monkeypatch.setenv("GUEST_RUN_KEY", "guest-key-for-a-tester-only")
    get_settings.cache_clear()
    guest = {"X-API-Key": "guest-key-for-a-tester-only"}
    assert client.get("/api/v1/owner/runs", headers=guest).status_code == 401           # guest can run, not see costs
    body = client.get("/api/v1/owner/runs", headers=KEY).json()
    row = next(r for r in body["runs"] if r["run_id"] == made["run_id"])
    assert row["total_usd"] == 1.75 and "cap_usd" in body["today"] and TEST_KEY not in json.dumps(body)
    one = client.get(f"/api/v1/owner/runs/{made['run_id']}", headers=KEY).json()
    assert [b["usd"] for b in one["breakdown"]] == [1.25, 0.5]
    assert client.get("/api/v1/owner/runs/run_missing", headers=KEY).status_code == 404
    assert "/api/v1/owner/runs" not in client.get("/openapi.json").text                 # not advertised
    get_settings.cache_clear()


def test_run_again_inputs_keep_the_clarifying_answer(api):
    """V1: every run and pack can be started again with all its inputs, the clarifying answer included."""
    made = client.post("/api/v1/runs", json={"brief": "snacks", "mode": "quick", "time_window_days": 90,
                                             "brand_voice": "dry Dutch humour"}, headers=KEY).json()
    assert made["status"] == "needs_clarification"
    q = made["clarifying_question"]["question"]
    answered = client.post(f"/api/v1/runs/{made['run_id']}/answer", json={"answer": "Netherlands, young adults"},
                           headers=KEY).json()
    inputs = answered["inputs"]
    assert inputs == {"brief": "snacks", "mode": "quick", "time_window_days": 90, "brand_voice": "dry Dutch humour",
                      "clarification": {"question": q, "answer": "Netherlands, young adults"}}
    db.update_run(made["run_id"], pack_id=api.pack_id)
    with db.session() as s:                                    # link the fixture pack to this run
        row = s.get(db.PackRow, api.pack_id)
        row.run_id = made["run_id"]
        s.add(row)
        s.commit()
    assert client.get(f"/api/v1/packs/{api.pack_id}/inputs").json() == inputs
    assert client.get("/api/v1/packs/pk_missing/inputs").status_code == 404
