"""research / overlap commands (Step 2.5). --fixtures: recorded data, fake model, no network, $0."""

import re

from typer.testing import CliRunner

from ctxpack import db
from ctxpack.cli import app
from ctxpack.config import get_settings
from ctxpack.orchestrator import units_overlap


def test_research_with_fixtures_runs_the_whole_loop(monkeypatch, tmp_path):
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    monkeypatch.delenv("USE_FIXTURES", raising=False)
    monkeypatch.delenv("LLM_FAKE", raising=False)
    get_settings.cache_clear()
    try:
        result = CliRunner().invoke(app, ["research", "Gen Z and meal prep", "--fixtures", "--auto-approve",
                                          "--brand-voice", "Warm, never preachy"], terminal_width=200)
    finally:
        get_settings.cache_clear()
    out = result.output
    assert result.exit_code == 0, out
    assert (tmp_path / "fixtures.db").exists()                        # never the real database
    for expected in ("Here's where I'll start", "CALL  #1", "reason:", "COVERAGE", "FINISH complete",
                     "KEPT", "DROPPED", "COST Apify $0.000 | Anthropic $0.000", "peak memory"):
        assert expected in out, expected
    run_id = re.search(r"RUN (run_\S+)", out).group(1)
    run = db.get_run(run_id)
    assert run.brand_voice == "Warm, never preachy" and run.requester.value == "cli"
    db.get_engine().dispose()
    db._engine = None


def test_units_overlap():
    a, b, c = {"reddit:r/x", "web:a.de"}, {"reddit:r/x", "tiktok:#y"}, {"web:b.nl"}
    report = units_overlap([a, b, c])
    assert report["shared"] == 1 and report["total"] == 4 and report["share"] == 0.25
    assert round(report["max_pairwise"], 2) == 0.33
