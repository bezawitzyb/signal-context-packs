"""Pack schema 1.0: example pack, lowercase enums, ID and quote checks, generated docs."""

import json
from pathlib import Path

import pytest
from pydantic import ValidationError

from ctxpack.config import REPO_DIR
from ctxpack.schemas.document import Document
from ctxpack.schemas.enums import ConfidenceLabel
from ctxpack.schemas.pack import Confidence, ContextPack
from ctxpack.schemas.plan import BriefInput, PlanResult
from ctxpack.schemas.schema_doc import build_json_schema, build_markdown, missing_descriptions

EXAMPLE = Path(__file__).parent / "fixtures" / "example_pack.json"


@pytest.fixture
def example() -> dict:
    return json.loads(EXAMPLE.read_text(encoding="utf-8"))


def test_example_pack_is_valid(example):
    assert example["schema_version"] == "1.0"                    # the fixture stays 1.0: it tests the migration
    pack = ContextPack.model_validate(example)
    assert pack.schema_version == "1.3"
    assert pack.brief.interpreted.markets[0].code == example["brief"]["interpreted"]["market"]
    assert len(pack.do_first) == 3
    assert len(pack.playbook.this_week) == 5


def test_example_pack_round_trips(example):
    pack = ContextPack.model_validate(example)
    again = ContextPack.model_validate_json(pack.model_dump_json())
    assert again == pack


@pytest.mark.parametrize("bad", ["Strong", "STRONG", "Very Strong"])
def test_capitalised_enum_is_rejected(bad):
    with pytest.raises(ValidationError):
        Confidence(score=0.8, label=bad)
    assert Confidence(score=0.8, label="strong").label is ConfidenceLabel.strong


def test_capitalised_enum_in_pack_is_rejected(example):
    example["tensions"][0]["claim_type"] = "Observed"
    with pytest.raises(ValidationError):
        ContextPack.model_validate(example)


def test_wrong_id_prefix_is_rejected(example):
    example["tensions"][0]["id"] = "TENSION-1"
    with pytest.raises(ValidationError):
        ContextPack.model_validate(example)


def test_unknown_evidence_reference_is_rejected(example):
    example["tensions"][0]["evidence_ids"] = ["EV-9999"]
    with pytest.raises(ValidationError, match="unknown ids"):
        ContextPack.model_validate(example)


def test_duplicate_ids_are_rejected(example):
    example["playbook"]["hooks"][1]["id"] = "HOOK-01"
    with pytest.raises(ValidationError, match="duplicate"):
        ContextPack.model_validate(example)


def test_quote_must_be_exact_substring(example):
    example["tensions"][0]["quotes"][0]["text"] = "Healthy snacks are a SCAM"
    with pytest.raises(ValidationError, match="exact substring"):
        ContextPack.model_validate(example)


def test_safe_to_assert_needs_strong_and_observed(example):
    example["tensions"][0]["safe_to_assert"] = True  # label is moderate
    with pytest.raises(ValidationError, match="safe_to_assert"):
        ContextPack.model_validate(example)


def test_do_first_must_be_three_unless_thin(example):
    example["do_first"] = example["do_first"][:2]
    with pytest.raises(ValidationError, match="exactly 3"):
        ContextPack.model_validate(example)
    example["coverage"]["thin_evidence"] = True
    ContextPack.model_validate(example)


def test_evidence_text_max_280(example):
    example["evidence"][0]["text"] = "x" * 281
    with pytest.raises(ValidationError):
        ContextPack.model_validate(example)


def test_document_rejects_raw_author_name():
    with pytest.raises(ValidationError, match="sha256"):
        Document(id="d1", run_id="r1", platform="reddit", source_unit="reddit:r/x",
                 url="https://example.com", text="hi", author_hash="Jane Example")


def test_brief_input_limits():
    assert BriefInput(brief="Gen Z and meal prep").time_window_days == 180
    with pytest.raises(ValidationError):
        BriefInput(brief="Gen Z and meal prep", time_window_days=45)
    with pytest.raises(ValidationError):
        BriefInput(brief="Gen Z and meal prep", brand_voice="x" * 201)


def test_plan_result_is_question_or_plan(example):
    interp = example["brief"]["interpreted"]
    question = {"question": "Which country?", "options": ["NL", "DE", "global"]}
    assert PlanResult(interpretation=interp, clarifying_questions=[question]).plan is None
    with pytest.raises(ValidationError, match="exactly one"):
        PlanResult(interpretation=interp)


def test_every_field_has_a_description():
    assert missing_descriptions() == []


def test_generated_docs_are_up_to_date():
    """docs/SCHEMA.md is generated; if this fails run: uv run python -m ctxpack.cli export-schema"""
    md = (REPO_DIR / "docs" / "SCHEMA.md").read_text(encoding="utf-8")
    js = (REPO_DIR / "docs" / "schema" / "context-pack.schema.json").read_text(encoding="utf-8")
    assert md == build_markdown()
    assert js == build_json_schema()


def test_a_1_1_pack_is_migrated_to_1_2_without_a_guessed_goal():
    """V11: the old free-text goal becomes goals or a goal note; the understanding is built in code; a guessed
    intent is dropped."""
    import json as _json

    from ctxpack.schemas.migrate import migrate
    from ctxpack.schemas.pack import ContextPack

    old = _json.loads(EXAMPLE.read_text(encoding="utf-8"))
    old["schema_version"] = "1.1"
    old["brief"]["interpreted"].pop("understanding", None)
    old["brief"]["interpreted"]["intent"] = "launch a snack"
    old["brief"]["intake"] = {"goal": "Positioning", "offer": "oat bars", "audience_roles": ["parents"]}
    new = ContextPack.model_validate(migrate(old)).model_dump(mode="json")
    b = new["brief"]
    assert new["schema_version"] == "1.3" and b["intake"]["goals"] == ["positioning"]
    assert b["interpreted"]["intent"] == "Positioning"
    u = b["interpreted"]["understanding"]
    assert (u["goal"]["source"], u["offer"]["source"], u["who"]["source"]) == ("answer", "answer", "answer")
    old["brief"]["intake"] = {"goal": "a content calendar"}
    again = ContextPack.model_validate(migrate(old)).model_dump(mode="json")["brief"]
    assert again["intake"]["goals"] == [] and again["intake"]["goal_note"] == "a content calendar"
    assert again["interpreted"]["understanding"]["offer"]["source"] == "none"      # never assumed
