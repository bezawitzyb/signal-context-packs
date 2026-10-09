"""The content calendar as a Notion-importable CSV (change V8, PRD 6.1e).

One row per calendar entry, in calendar order. UTF-8 with a BOM so Excel and
Notion read accents (Dutch, Polish, German) correctly; every cell passes
safe_cells (DH11). Source links are the public post links behind the brief's
key points; the quotes themselves are not exported (quote-reuse rule).
"""

from __future__ import annotations

import csv
import io

from ctxpack.config import get_settings
from ctxpack.exports.safe_cells import safe_row

COLUMNS = ["Title", "Week", "Day", "Channel", "Audience", "Hook", "Angle", "Key points", "Call to action",
           "Status", "Pack link", "Source links"]
CHANNEL_NAMES = {"reddit": "Reddit", "tiktok": "TikTok", "youtube": "YouTube", "instagram": "Instagram",
                 "linkedin": "LinkedIn", "x": "X", "facebook": "Facebook", "web_forum": "Forums", "blog": "Blog", "newsletter": "Newsletter"}
FORMAT_NAMES = {"text_post": "text post", "carousel": "carousel", "short_video": "short video",
                "blog_article": "blog article", "newsletter": "newsletter"}


def pack_link(pack: dict) -> str:
    return f"{get_settings().public_url.rstrip('/')}/packs/{pack['pack_id']}"


def calendar_rows(pack: dict) -> list[list[str]]:
    briefs = {b["id"]: b for b in pack.get("post_briefs", [])}
    links = {e["id"]: e.get("url") or "" for e in pack.get("evidence", [])}
    rows = []
    for e in pack.get("content_calendar", []):
        b = briefs.get(e["post_brief_id"])
        if not b:
            continue
        sources = list(dict.fromkeys(links[i] for p in b["key_points"] for i in p["evidence_ids"] if links.get(i)))
        title = f"{CHANNEL_NAMES.get(b['channel'], b['channel'])} {FORMAT_NAMES.get(b['format'], b['format'])}: " \
                f"{b['angle'] or b['hook']}"
        rows.append(safe_row([
            title[:120], e["week"], e["suggested_day"].capitalize(), CHANNEL_NAMES.get(e["channel"], e["channel"]),
            b["role"], b["hook"], b["angle"], "\n".join(f"• {p['text']}" for p in b["key_points"]), b["cta"],
            "Idea", f"{pack_link(pack)}#{b['id']}", "\n".join(sources)]))
    return rows


def to_calendar_csv(pack: dict) -> bytes:
    """CSV bytes: UTF-8 with BOM, a header row, one row per calendar entry."""
    buf = io.StringIO()
    writer = csv.writer(buf, lineterminator="\r\n")
    writer.writerow(COLUMNS)
    writer.writerows(calendar_rows(pack))
    return buf.getvalue().encode("utf-8-sig")
