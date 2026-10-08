"""Hand-off options (change V9): what each export is for, how long it is and what is inside.

Written for marketers: purpose and length in pages (words / modes.yaml exports.words_per_page),
never tokens or file formats first. The page shows these; the mirror gets them as handoff.json.
"""

from __future__ import annotations

from ctxpack.exports.common import cfg, inline


def length_label(words: int) -> str:
    pages = words / cfg()["words_per_page"]
    if pages <= 0.6:
        return "half a page"
    if pages < 1.4:
        return "about 1 page"
    return f"about {round(pages)} pages"


def _first(text: str, n: int = 140) -> str:
    line = next((x for x in text.splitlines() if x.strip() and not x.startswith(("#", "*Pack", "|"))), "")
    line = inline(line.lstrip("-> ").replace("*", ""))
    return line if len(line) <= n else line[:n - 1].rsplit(" ", 1)[0] + "…"


def handoff_options(pack: dict) -> list[dict]:
    from ctxpack.exports.markdown import to_markdown
    from ctxpack.exports.prompt_block import to_prompt_block
    from ctxpack.exports.quick_brief import to_quick_brief

    quick, prompt, report = to_quick_brief(pack), to_prompt_block(pack), to_markdown(pack)
    posts = len(pack.get("content_calendar", []))
    weeks = max([e["week"] for e in pack.get("content_calendar", [])] or [0])
    first_post = next((b for b in pack.get("post_briefs", [])), None)
    return [
        {"kind": "quick", "title": "Quick brief", "action": "copy", "more": False,
         "purpose": "Paste into ChatGPT or Claude to start writing.",
         "length": length_label(len(quick.split())), "preview": _first(quick)},
        {"kind": "prompt", "title": "Brief for your AI writer", "action": "copy", "more": False,
         "purpose": "Everything an AI copywriter needs: audience, language, rules, post ideas.",
         "length": length_label(len(prompt.split())), "preview": _first(prompt)},
        {"kind": "md", "title": "Full report", "action": "copy", "more": False,
         "purpose": "For Notion, Google Docs or sharing with your team. Use Print for a PDF.",
         "length": length_label(len(report.split())), "preview": _first(report.split("## Summary", 1)[-1])},
        {"kind": "calendar", "title": "Content calendar", "action": "download", "more": False,
         "purpose": "Import into Notion or a spreadsheet: one row per post idea.",
         "length": f"{posts} post ideas over {weeks} weeks" if posts else "no post ideas in this pack",
         "preview": f"First: {inline(first_post['angle'] or first_post['hook'])}" if first_post else ""},
        {"kind": "skill", "title": "Teach Claude this research", "action": "download", "more": True,
         "purpose": "Install once and Claude remembers this audience in every chat.",
         "length": "a small file to upload", "preview": "Their words, tensions, objections, hooks, channels, posts."},
        {"kind": "json", "title": "For developers", "action": "download", "more": True,
         "purpose": "The data file behind this page, and the API.",
         "length": "data file", "preview": f"Pack {pack['pack_id']}, schema {pack['schema_version']}."},
    ]
