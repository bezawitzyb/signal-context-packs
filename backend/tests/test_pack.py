"""Playbook, compliance and finalise (Step 3.5, F4-11, F4-12, PRD 6, 11.4). LLM_FAKE: no money."""

import pytest

from ctxpack import db, worker
from ctxpack.schemas.enums import EventType, RunStatus
from ctxpack.schemas.pack import ContextPack
from ctxpack.synthesis import compliance, finalize, playbook, posts
from ctxpack.synthesis import verify as vf
from ctxpack.synthesis import write as wr
from tests.test_cluster import CTX, fake  # noqa: F401  (fixture)
from tests.test_worker import approved_run, offline  # noqa: F401  (fixture)
from tests.test_write import prepared_run


async def verified_run_id() -> str:
    run_id = await prepared_run()
    await wr.write_run(run_id, CTX)
    await vf.verify_run(run_id)
    return run_id


def sections(run_id: str) -> dict:
    return db.get_run(run_id).draft["verified"]["sections"]


# --- the playbook: only references to real items -------------------------------------

async def test_playbook_keeps_only_evidence_backed_parts(fake, temp_db):
    s = sections(await verified_run_id())
    ten = s["tensions"][0]["id"]
    out = playbook.PlaybookOut.model_validate({
        "do_first": [{"action": "a", "why_ids": [ten]}, {"action": "b", "why_ids": ["THM-99"]},
                     {"action": "c", "why_ids": [ten.lower()], "effort": "huge"}],
        "channel_plan": [{"platform": "tiktok", "why_ids": [ten]}, {"platform": "myspace", "why_ids": [ten]},
                         {"platform": "reddit", "why_ids": []}],
        "hooks": [{"text": "h1", "why_ids": ["THM-99"]}, {"text": "h2", "why_ids": [ten]},
                  {"text": "h3", "why_ids": [s["themes"][0]["id"]]}],
        "this_week": [{"day": "Monday", "platform": "tiktok", "format": "f", "hook_id": "HOOK-02", "angle": "x",
                       "moment_id": "MOM-99"},
                      {"day": "tuesday", "platform": "tiktok", "format": "f", "hook_id": "HOOK-01", "angle": "x"},
                      {"day": "someday", "platform": "tiktok", "format": "f", "hook_id": "HOOK-03", "angle": "x"}],
        "objection_handling": [{"objection_id": "OBJ-99", "response": "r"}]})
    stats = playbook.PlaybookStats()
    parts = playbook.validate(out, s, stats)
    assert [d["action"] for d in parts["do_first"]] == ["a", "c"] and parts["do_first"][1]["effort"] == "medium"
    assert [c["platform"] for c in parts["channel_plan"]] == ["tiktok"]           # no channel without evidence
    hooks = parts["playbook"]["hooks"]
    assert [(h["id"], h["text"]) for h in hooks] == [("HOOK-01", "h2"), ("HOOK-02", "h3")]  # renumbered
    week = parts["playbook"]["this_week"]
    assert [(w["day"], w["hook_id"], w["moment_id"]) for w in week] == [("monday", "HOOK-01", None)]
    assert stats.hooks_without_tension == 1 and parts["playbook"]["objection_handling"] == []


# --- compliance ---------------------------------------------------------------------

async def test_compliance_flags_only_real_items_and_keeps_test_texts_apart(fake):
    items = {"HOOK-01": "Healthy chips for everyone", "HOOK-02": "Proper salty chips"}
    flags, tests, _ = await compliance.flag(items, "food_nutrition", "NL",
                                            ["Save 40% on heating and save the planet"])
    assert [(f["id"], f["item_id"], f["category"]) for f in flags] == [("CMP-01", "HOOK-01", "food_nutrition")]
    assert all(f["note"] == "check with legal - not legal advice" for f in flags)
    assert [(t["item_id"], t["category"]) for t in tests] == [("TEST-01", "energy_environmental")]


# --- the pack -------------------------------------------------------------------------

async def test_package_run_saves_a_valid_pack_and_reuses_the_playbook(fake, temp_db, monkeypatch):
    run_id = await verified_run_id()
    out = await finalize.package_run(run_id)
    pack = ContextPack.model_validate(db.get_pack(out.pack_id))
    assert db.get_run(run_id).pack_id == out.pack_id
    assert pack.instructions_for_agents == finalize.INSTRUCTIONS_FOR_AGENTS
    assert len(pack.do_first) == 3 and len(pack.playbook.this_week) == 5 and len(pack.playbook.hooks) == 10
    assert pack.blind_spots and pack.guardrails.quote_reuse_note
    assert pack.coverage.thin_evidence and out.bar_short                       # a 10-post corpus is thin
    assert any("Minimum content bar not met" in b.text for b in pack.blind_spots)
    assert len(pack.digest) <= 2000 and "Five truths:" in pack.digest
    truths = pack.snapshot.five_truths
    assert 1 <= len(truths) <= 5 and pack.snapshot.top_opportunity
    assert pack.coverage.counts.undated == pack.coverage.counts.kept               # counted from the store

    calls = []
    real = playbook.structured
    monkeypatch.setattr(playbook, "structured", lambda *a, **k: calls.append(a[4]) or real(*a, **k))
    again = await finalize.package_run(run_id)
    assert again.reused_playbook and calls == [] and again.pack_id != out.pack_id   # a new pack, no new calls


async def test_the_playbook_is_saved_before_compliance_and_a_new_verification_clears_it(fake, temp_db, monkeypatch):
    """DE rebuild 2026-10-10: the budget ran out at the compliance call and the paid playbook was lost; and a
    re-verified draft must never be packed with the playbook or opportunities of the previous one."""
    run_id = await verified_run_id()

    async def no_budget(*a, **k):
        raise RuntimeError("budget spent")

    monkeypatch.setattr(compliance, "flag", no_budget)
    with pytest.raises(RuntimeError):
        await finalize.package_run(run_id)
    assert db.get_run(run_id).draft["playbooks"]["_neutral"]["parts"]        # kept for the next try
    assert "news_v7" in db.get_run(run_id).draft

    await vf.verify_run(run_id, redo=True)
    draft = db.get_run(run_id).draft
    assert not {"playbooks", "news_v7", "opportunities_v5", "brand_v12"} & set(draft)


async def test_brand_voice_reaches_only_the_playbook_call(offline, monkeypatch):  # noqa: F811
    from ctxpack.analysis import cluster, extract
    from ctxpack.collect import relevance
    from ctxpack.synthesis import baseline

    voice = "VOICE-MARKER dry Dutch humour"
    seen: list[tuple[str, str]] = []
    for module in (relevance, extract, cluster, baseline, wr, vf, playbook, posts, compliance):
        real = module.structured

        def spy(*a, _real=real, **k):
            seen.append((a[4], a[2] + a[1]))  # tool name, user + system text
            return _real(*a, **k)
        monkeypatch.setattr(module, "structured", spy)
    run_id = await approved_run()
    db.update_run(run_id, brand_voice=voice)
    assert await worker.run_next() == run_id
    assert db.get_run(run_id).status == RunStatus.complete
    with_voice = {tool for tool, text in seen if "VOICE-MARKER" in text}
    assert with_voice == {"record_playbook", "record_drafts"} and len({t for t, _ in seen}) > 5  # V8: one stage
    pack = db.get_pack(db.get_run(run_id).pack_id)
    assert pack["brief"]["brand_voice"] == voice


async def test_the_pipeline_ends_with_a_saved_pack(offline):  # noqa: F811
    run_id = await approved_run()
    assert await worker.run_next() == run_id
    run = db.get_run(run_id)
    assert run.status == RunStatus.complete and run.pack_id
    assert any(e.type == EventType.pack_ready for e in db.get_events(run_id))
    ContextPack.model_validate(db.get_pack(run.pack_id))


def test_content_bar_counts_strong_tensions_only():
    ev = [{"id": "EV-0001", "source_unit": "a"}, {"id": "EV-0002", "source_unit": "a"},
          {"id": "EV-0003", "source_unit": "b"}]
    t_ok = {"evidence_ids": ["EV-0001"], "want": {"evidence_ids": ["EV-0002"]}, "but": {"evidence_ids": ["EV-0003"]}}
    t_one_source = {"evidence_ids": ["EV-0001"], "want": {"evidence_ids": ["EV-0002"]}, "but": {"evidence_ids": []}}
    secs = {"lexicon": [{}] * 8, "tensions": [t_ok, t_one_source], "objections": [{}] * 3, "opportunities": [{}] * 3,
            "white_space": [], "what_performs": [{}] * 3, "_evidence": ev}
    parts = {"playbook": {"hooks": [{}] * 6, "this_week": [{}] * 5}, "channel_plan": [{}] * 3, "do_first": [{}] * 3}
    assert finalize.content_bar(secs, parts, "quick") == ["tensions 1 of 2"]   # white space 0 = "none found"


@pytest.mark.parametrize("mode", ["quick", "standard"])
def test_content_bar_numbers_come_from_config(mode):
    from ctxpack.config import load_yaml

    assert set(load_yaml("modes")["content_bar"][mode]) == {"lexicon", "tensions", "hooks", "objections",
                                                             "opportunities", "white_space", "what_performs",
                                                             "channel_plan"}


async def test_test_hooks_rerun_only_the_compliance_call(fake, temp_db, monkeypatch):
    run_id = await verified_run_id()
    await finalize.package_run(run_id)
    calls = []
    for module in (playbook, compliance):
        real = module.structured
        monkeypatch.setattr(module, "structured", lambda *a, _r=real, **k: calls.append(a[4]) or _r(*a, **k))
    out = await finalize.package_run(run_id, test_hooks=["Save 40% on heating and save the planet"])
    assert calls == ["record_flags"] and out.reused_playbook
    assert [t["category"] for t in out.test_flags] == ["energy_environmental"]
    pack = ContextPack.model_validate(db.get_pack(out.pack_id))
    assert all(f.note == "check with legal - not legal advice" for f in pack.compliance_flags)
