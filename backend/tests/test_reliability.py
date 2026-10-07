"""Change V1: never lose a run. Any run with enough relevant posts ends with a pack, whatever fails after
collection; below the floor it ends on a clear thin-evidence state. Fixtures + fake model: no money."""

from ctxpack import db, orchestrator, worker
from ctxpack.schemas.enums import FinishReason, RunStatus
from tests.test_worker import approved_run, offline, stages  # noqa: F401  (fixture)


async def test_root_cause_collection_time_limit_still_builds_a_pack(offline):  # noqa: F811
    """The user-test bug: the agent loop ends by time limit or error -> analysis was skipped -> no pack."""
    run_id = await approved_run()

    async def collect_then_time_out(rid):
        await orchestrator.collect_agent(rid)
        db.update_run(rid, finish_reason=FinishReason.time_limit)

    await worker.run_next(collect=collect_then_time_out)
    run = db.get_run(run_id)
    assert run.status == RunStatus.partial
    assert run.pack_id, "a run with enough posts must end with a pack"


from ctxpack.schemas.enums import EventType, RunStage  # noqa: E402
from tests.test_worker import ALL_STAGES, events  # noqa: E402

import pytest  # noqa: E402


async def test_exception_mid_collection_keeps_what_was_collected(offline):  # noqa: F811
    run_id = await approved_run()

    async def collect_then_crash(rid):
        await orchestrator.collect_agent(rid)
        raise RuntimeError("loop broke")

    await worker.run_next(collect=collect_then_crash)
    run = db.get_run(run_id)
    assert run.finish_reason == FinishReason.error and run.status == RunStatus.partial and run.pack_id
    assert stages(run_id) == ALL_STAGES
    assert db.get_pack(run.pack_id)["blind_spots"][0]["text"].startswith("Partial pack: the research agent stopped")


@pytest.mark.parametrize("failing", ["extracting", "clustering", "writing", "verifying"])
async def test_each_analysis_step_failing_twice_gives_an_evidence_only_pack(offline, failing):  # noqa: F811
    run_id = await approved_run()
    real = dict(orchestrator.ANALYSIS_STAGES)

    async def boom(rid):
        raise ValueError("model answer could not be read")

    steps = [(st, boom if st.value == failing else real[st]) for st, _ in orchestrator.ANALYSIS_STAGES]
    await worker.run_next(stages=steps)
    run = db.get_run(run_id)
    assert run.status == RunStatus.partial and run.pack_id
    pack = db.get_pack(run.pack_id)
    assert f"({failing} failed: ValueError)" in pack["blind_spots"][0]["text"]
    assert pack["evidence"] and all(not e["short_form"] for e in pack["evidence"])
    assert "model answer could not be read" not in str(pack)


async def test_packaging_failing_twice_gives_an_evidence_only_pack(offline):  # noqa: F811
    run_id = await approved_run()

    async def broken_pack(rid, partial):
        raise RuntimeError("validation")

    await worker.run_next(build_pack=broken_pack)
    run = db.get_run(run_id)
    assert run.status == RunStatus.partial and run.pack_id
    assert db.get_pack(run.pack_id)["blind_spots"][0]["text"].startswith("Partial pack: packaging failed")


async def test_a_one_off_glitch_is_retried_and_the_pack_is_complete(offline):  # noqa: F811
    run_id = await approved_run()
    real = dict(orchestrator.ANALYSIS_STAGES)
    calls = []

    async def flaky_write(rid):
        calls.append(1)
        if len(calls) == 1:
            raise TimeoutError("slow model")
        await real[RunStage.writing](rid)

    steps = [(st, flaky_write if st == RunStage.writing else real[st]) for st, _ in orchestrator.ANALYSIS_STAGES]
    await worker.run_next(stages=steps)
    run = db.get_run(run_id)
    assert run.status == RunStatus.complete and run.pack_id and len(calls) == 2
    assert not db.get_pack(run.pack_id)["blind_spots"][0]["text"].startswith("Partial pack")


async def test_below_the_floor_ends_on_a_clear_thin_state(offline, monkeypatch):  # noqa: F811
    monkeypatch.setattr(orchestrator, "thin_floor", lambda: 10_000)
    run_id = await approved_run()
    await worker.run_next()
    run = db.get_run(run_id)
    assert run.status == RunStatus.failed and run.pack_id is None
    thin = run.collection["thin"]
    assert thin["needed"] == 10_000 and thin["reasons"] and all(r["text"] for r in thin["reasons"])
    assert {"broaden_audience", "run_standard"} <= set(thin["replans"])                 # quick run, offered Standard
    assert events(run_id, EventType.error)[-1].payload["thin"] is True
    assert stages(run_id) == ["collecting"]                                            # nothing paid after collection


async def test_stop_during_analysis_still_gives_a_pack(offline):  # noqa: F811
    run_id = await approved_run()

    async def press_stop(rid):
        orchestrator.request_stop(rid)

    await worker.run_next(stages=[(RunStage.extracting, press_stop), (RunStage.clustering, press_stop)])
    run = db.get_run(run_id)
    assert run.status == RunStatus.partial and run.pack_id
    assert "stopped by hand" in db.get_pack(run.pack_id)["blind_spots"][0]["text"]
