"""The content calendar as a spreadsheet (change V8, PRD 6.1e; exports audit 2026-10-10).

One row per post, in calendar order, ready to import into Notion, Google Sheets, Excel, Trello or a scheduler:
a real date (week 1 starts the Monday after the pack was made; edit freely), the full brief in columns, the draft,
how you will know it worked, and a "Check with legal first" column for anything the compliance check flagged.
UTF-8 with a BOM so Excel and Notion read accents correctly; every cell passes safe_cells (DH11). No quotes and no
post links: the quote-reuse rule keeps real people's words out of planning tools (the pack link leads to them).
"""

from __future__ import annotations

import csv
import io
from datetime import date, datetime, timedelta

from ctxpack.config import get_settings
from ctxpack.exports.common import inline
from ctxpack.exports.plain import CHANNEL_NAMES, FORMAT_NAMES, channel, fmt, legal_note, sentence  # noqa: F401
from ctxpack.exports.safe_cells import safe_row

COLUMNS = ["Date", "Week", "Day", "Channel", "Format", "For whom", "Title", "Hook", "Angle", "Key points",
           "Call to action", "Their words", "Avoid", "How you'll know it worked", "Draft", "Check with legal first",
           "Strength", "Status", "Pack link"]
DAYS = ("monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday")
TITLE_MAX = 100


def pack_link(pack: dict) -> str:
    return f"{get_settings().public_url.rstrip('/')}/packs/{pack['pack_id']}"


def _title(text: str) -> str:
    """A short title that ends on a whole word (never "...the actual figur")."""
    t = inline(text)
    if len(t) <= TITLE_MAX:
        return t
    return t[:TITLE_MAX].rsplit(" ", 1)[0].rstrip(",;:") + "…"


def post_date(pack: dict, week: int, day: str) -> date:
    from ctxpack.synthesis.posts import week_start

    made = datetime.fromisoformat(str(pack["generated_at"]).replace("Z", "+00:00")).date()
    offset = DAYS.index(day.lower()) if day.lower() in DAYS else 0
    return week_start(made) + timedelta(days=(week - 1) * 7 + offset)


def calendar_rows(pack: dict) -> list[list[str]]:
    briefs = {b["id"]: b for b in pack.get("post_briefs", [])}
    drafts = {d["post_brief_id"]: d for d in pack.get("drafts", [])}
    words = {x["id"]: x["term"] for x in pack["voice"]["lexicon"]}
    rows = []
    for e in pack.get("content_calendar", []):
        b = briefs.get(e["post_brief_id"])
        if not b:
            continue
        d = drafts.get(b["id"])
        draft = "\n\n".join(x for x in ((d or {}).get("title") or "", (d or {}).get("body") or "") if x)
        rows.append(safe_row([
            post_date(pack, e["week"], e["suggested_day"]).isoformat(), e["week"], e["suggested_day"].capitalize(),
            channel(e["channel"]), fmt(b["format"]), b["role"], _title(b["angle"] or b["hook"]), b["hook"],
            b["angle"], "\n".join(f"• {sentence(p['text'])}" for p in b["key_points"]), b["cta"],
            ", ".join(words.get(w, w) for w in b["their_words_to_use"]), "; ".join(b["avoid"]),
            b.get("success_measure", ""), draft,
            (legal_note(pack, b["id"], b["hook"]) or legal_note(pack, (d or {}).get("id"))).removeprefix(
                "Check with legal first: "), b["confidence"], "Idea", f"{pack_link(pack)}#{b['id']}"]))
    return rows


def to_calendar_csv(pack: dict) -> bytes:
    """CSV bytes: UTF-8 with BOM, a header row, one row per calendar entry."""
    buf = io.StringIO()
    writer = csv.writer(buf, lineterminator="\r\n")
    writer.writerow(COLUMNS)
    writer.writerows(calendar_rows(pack))
    return buf.getvalue().encode("utf-8-sig")
