"""Spread the quotes of a pack (UX audit 2026-10-10).

One post often backs several findings, so each finding's FIRST quote kept being the same few posts. Walking the
sections in page order (pack.section_order), each item's quotes are reordered so that the first one is a post not
already shown higher up; nothing is added, removed or reworded, only the order changes. The Summary keeps its
quotes (it restates the top findings) and later items avoid them. Tension sides reorder their evidence ids the
same way. The pack page does the same walk (frontend/src/lib/quotePicks.ts), so older packs match on screen.
"""

from __future__ import annotations

from typing import Any


def _section_items(data: dict, section: str) -> list[dict]:
    culture = data.get("culture") or {}
    return {
        "brand": list((data.get("brand_perception") or {}).get("findings") or []),
        "want-stops": [*(data.get("motivations") or []), *(data.get("pain_points") or []),
                       *(data.get("objections") or []), *(data.get("tensions") or [])],
        "segments": list(data.get("segments") or []),
        "landscape": [*((data.get("landscape") or {}).get("themes") or []), *(data.get("moments") or []),
                      *(culture.get("formats") or []), *(culture.get("communities") or []),
                      *(culture.get("creators") or []), *(culture.get("codes") or [])],
    }.get(section, [])


def spread_quotes(data: dict[str, Any]) -> None:
    """Reorder, in place, each item's quotes (and each tension side's evidence ids) so the first is not a repeat."""
    have = {e["id"] for e in data.get("evidence") or []}
    used = {f["quote"]["evidence_id"] for f in (data.get("snapshot") or {}).get("findings") or []
            if f.get("quote") and f["quote"].get("evidence_id")}

    def first_unused(ids: list[str]) -> str | None:
        return next((i for i in ids if i in have and i not in used), None)

    for section in data.get("section_order") or []:
        for item in _section_items(data, section):
            if "want" in item and "but" in item:          # a tension: each side shows its first post
                for side in (item["want"], item["but"]):
                    ids = side.get("evidence_ids") or []
                    pick = first_unused(ids) or next((i for i in ids if i in have), None)
                    if pick:
                        side["evidence_ids"] = [pick, *[i for i in ids if i != pick]]
                        used.add(pick)
                continue
            quotes = item.get("quotes") or []
            shown = [q for q in quotes if q.get("evidence_id") in have]
            fresh = next((q for q in shown if q["evidence_id"] not in used), None)
            if fresh is not None:
                item["quotes"] = [fresh, *[q for q in quotes if q is not fresh]]
                used.add(fresh["evidence_id"])
                continue
            quoted = {q["evidence_id"] for q in shown}   # every quote repeats: the page shows another post, if any
            other = first_unused([i for i in item.get("evidence_ids") or [] if i not in quoted])
            if pick := other or (shown[0]["evidence_id"] if shown else None):
                used.add(pick)
