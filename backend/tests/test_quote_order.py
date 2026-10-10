"""Spreading a pack's quotes: only the order changes, and the first quote avoids posts already shown above."""

import copy
import json
from pathlib import Path

from ctxpack.synthesis.quote_order import spread_quotes

FIXTURE_PACKS = Path(__file__).parent / "fixtures" / "packs"


def q(ev: str) -> dict:
    return {"evidence_id": ev, "text": f"words of {ev}"}


def pack(**sections) -> dict:
    data = {"evidence": [{"id": f"EV-000{i}"} for i in range(1, 8)], "snapshot": {"findings": []},
            "section_order": ["want-stops", "landscape"], "motivations": [], "landscape": {"themes": []}}
    data.update(sections)
    return data


def test_a_later_item_leads_with_a_post_not_shown_above():
    data = pack(motivations=[{"id": "MOT-01", "quotes": [q("EV-0001"), q("EV-0002")]}],
                landscape={"themes": [{"id": "THM-01", "quotes": [q("EV-0001"), q("EV-0003")]}]})
    spread_quotes(data)
    assert data["motivations"][0]["quotes"][0]["evidence_id"] == "EV-0001"        # first on the page: unchanged
    assert [x["evidence_id"] for x in data["landscape"]["themes"][0]["quotes"]] == ["EV-0003", "EV-0001"]


def test_the_summary_keeps_its_quotes_and_later_items_avoid_them():
    data = pack(motivations=[{"id": "MOT-01", "quotes": [q("EV-0001"), q("EV-0002")]}])
    data["snapshot"]["findings"] = [{"quote": q("EV-0001")}]
    spread_quotes(data)
    assert data["motivations"][0]["quotes"][0]["evidence_id"] == "EV-0002"


def test_an_item_with_nothing_new_keeps_its_order():
    data = pack(motivations=[{"id": "MOT-01", "quotes": [q("EV-0001")]},
                             {"id": "MOT-02", "quotes": [q("EV-0001")]}])
    spread_quotes(data)
    assert data["motivations"][1]["quotes"] == [q("EV-0001")]


def test_tension_sides_lead_with_an_unshown_post():
    data = pack(motivations=[{"id": "MOT-01", "quotes": [q("EV-0001")]}],
                tensions=[{"id": "TEN-01", "want": {"text": "w", "evidence_ids": ["EV-0001", "EV-0004"]},
                           "but": {"text": "b", "evidence_ids": ["EV-0005"]}}])
    spread_quotes(data)
    assert data["tensions"][0]["want"]["evidence_ids"] == ["EV-0004", "EV-0001"]
    assert data["tensions"][0]["but"]["evidence_ids"] == ["EV-0005"]


def test_on_real_packs_quotes_are_only_reordered_and_a_second_pass_changes_nothing():
    for path in sorted(FIXTURE_PACKS.glob("*.json")):
        before = json.loads(path.read_text(encoding="utf-8"))
        after = copy.deepcopy(before)
        spread_quotes(after)

        def quote_sets(d: dict) -> list:
            out: list = []

            def walk(o):
                if isinstance(o, dict):
                    if isinstance(o.get("quotes"), list):
                        out.append(sorted(json.dumps(x, sort_keys=True) for x in o["quotes"]))
                    for k, v in o.items():
                        if k != "digest":
                            walk(v)
                elif isinstance(o, list):
                    for v in o:
                        walk(v)
            walk(d)
            return out

        assert quote_sets(after) == quote_sets(before), path.name          # nothing added, lost or reworded
        again = copy.deepcopy(after)
        spread_quotes(again)
        assert again == after, path.name                                     # stable
