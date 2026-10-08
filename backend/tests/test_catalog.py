"""The source catalogue is complete and never lists per-brief communities."""

from typer.testing import CliRunner

from ctxpack.cli import app
from ctxpack.config import load_yaml
from ctxpack.schemas.enums import Platform, SourceUnitKind

APIFY = {"reddit", "tiktok", "youtube", "google_trends", "instagram", "linkedin", "x"}
WEB = {"web_forums", "web_reviews", "web_editorial"}


def test_every_source_is_present_with_valid_unit_types():
    sources = load_yaml("catalog")["sources"]
    assert set(sources) == APIFY | WEB
    for src in sources.values():
        assert src["unit_types"]
        assert all(u in SourceUnitKind.__members__ for u in src["unit_types"])
        if src["platform"] is not None:
            assert src["platform"] in Platform.__members__


def test_apify_sources_have_a_different_fallback_and_limits():
    sources = load_yaml("catalog")["sources"]
    for name in APIFY:
        src = sources[name]
        if src["fallback"] is None:  # allowed only for optional context, never for audience voice
            assert src["platform"] is None, f"{name} needs a fallback"
        else:
            assert src["actor"]["id"] != src["fallback"]["id"]
        assert src["actor"]["limit_inputs"], f"{name} has no item limit input"
        if src.get("comments", {}).get("fallback"):
            assert src["comments"]["actor"]["id"] != src["comments"]["fallback"]["id"]


def test_no_per_brief_communities():
    # Unit TYPES only - never a list of subreddits, hashtags or domains.
    for src in load_yaml("catalog")["sources"].values():
        assert not {"subreddits", "hashtags", "domains", "channels", "communities"} & set(src)


def test_cli_catalog_prints_table():
    result = CliRunner().invoke(app, ["catalog"])
    assert result.exit_code == 0
    for name in APIFY | WEB:
        assert name in result.output


def _all_actors():
    for name, src in load_yaml("catalog")["sources"].items():
        comments = src.get("comments") or {}
        for actor in (src.get("actor"), src.get("fallback"), comments.get("actor"), comments.get("fallback")):
            if actor:
                yield name, actor


def test_every_actor_has_memory_and_a_smoke_status():
    # No actor joins the catalogue without a memory setting and an honest
    # smoke-test status ("ok <date> ..." or "not run ...").
    for name, actor in _all_actors():
        assert isinstance(actor.get("memory_mbytes"), int), f"{name}: {actor['id']} has no memory_mbytes"
        smoke = actor.get("smoke", "")
        assert smoke.startswith(("ok ", "not run", "timed out")), f"{name}: {actor['id']} smoke status missing"
        assert actor.get("price_usd"), f"{name}: {actor['id']} has no price"


def test_main_actors_passed_the_smoke_test():
    for name, src in load_yaml("catalog")["sources"].items():
        if src["kind"] == "apify":
            assert src["actor"]["smoke"].startswith("ok "), f"{name} main actor not smoke-tested"


def test_call_rules_are_recorded():
    rules = load_yaml("catalog")["call_rules"]
    assert {"budget_check", "count_items", "final_cost", "chain_comments", "missing_engagement"} <= set(rules)
