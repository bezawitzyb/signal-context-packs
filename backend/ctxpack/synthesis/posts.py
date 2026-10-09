"""Post briefs, drafts and the content calendar (change V8, PRD 6.1e).

Post briefs come back from the playbook call; code keeps only what it can trace:
a key point keeps the pack items it names and gets its evidence ids from them
(never from the model); a brief with too few key points, or on a channel with no
evidence and not used by the user, is dropped. Drafts are ONE extra call in the
playbook stage (brand voice is used there and nowhere else); code then removes
every sentence that uses a guardrail phrase or states a number the cited posts
do not contain. The calendar is built in code from the channel plan's cadence,
its timing chips, this week's plan and dated news hooks.
"""

from __future__ import annotations

import re
from datetime import date, timedelta
from typing import Any

from pydantic import BaseModel, Field

from ctxpack.config import load_yaml
from ctxpack.llm.client import load_prompt, structured, untrusted
from ctxpack.schemas.enums import PostChannel, PostFormat

LEVELS = ["speculative", "emerging", "moderate", "strong"]
DAYS = ("monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday")
# channel plan platform -> where a post goes (review sites are listened to, not posted on)
PLAN_TO_POST = {"reddit": "reddit", "tiktok": "tiktok", "youtube": "youtube", "instagram": "instagram",
                "linkedin": "linkedin", "x": "x", "facebook": "facebook", "web_forum": "web_forum",
                "web_editorial": "blog"}
# words a user may type for a channel they already use (V3 intake is free text)
_CHANNEL_WORDS = [("linkedin", "linkedin"), ("instagram", "instagram"), ("insta", "instagram"),
                  ("tiktok", "tiktok"), ("youtube", "youtube"), ("reddit", "reddit"), ("twitter", "x"),
                  ("facebook", "facebook"),
                  ("newsletter", "newsletter"), ("e-mail", "newsletter"), ("email", "newsletter"),
                  ("mailing", "newsletter"), ("blog", "blog"), ("website", "blog"), ("seo", "blog"),
                  ("forum", "web_forum")]


def cfg() -> dict:
    return load_yaml("modes")["posts"]


# --------------------------------------------------------------------------
# Post briefs (validated from the playbook call)
# --------------------------------------------------------------------------


class KeyPointOut(BaseModel):
    text: str
    item_ids: list[str] = Field(default_factory=list)


class PostBriefOut(BaseModel):
    channel: str
    role: str = ""
    goal: str = ""
    hook: str = ""
    hook_id: str | None = None
    angle: str = ""
    key_points: list[KeyPointOut] = Field(default_factory=list)
    structure: str = ""
    format: str = "text_post"
    their_words_to_use: list[str] = Field(default_factory=list)
    cta: str = ""
    avoid: list[str] = Field(default_factory=list)
    news_hook_id: str | None = None
    based_on: list[str] = Field(default_factory=list)
    success_measure: str = ""


def user_channels(intake: dict | None) -> list[str]:
    """The user's own channels (intake.channels_in_use, free text) as post channels, in their order."""
    out: list[str] = []
    for said in (intake or {}).get("channels_in_use") or []:
        low = f" {str(said).casefold()} "
        hits = [(low.find(word), ch) for word, ch in _CHANNEL_WORDS if word in low]
        hits += [(m.start(), "x") for m in re.finditer(r"(?<![\w.])x(?:\.com)?(?![\w])", low)]
        for _, ch in sorted(hits):  # in the order the user wrote them
            if ch not in out:
                out.append(ch)
    return out


def item_index(s: dict) -> dict[str, dict]:
    """Every pack item that can carry a key point: id -> item (with evidence_ids and confidence)."""
    from ctxpack.synthesis.write import INSIGHT_SECTIONS

    index = {it["id"]: it for name in INSIGHT_SECTIONS for it in s.get(name, [])}
    index |= {o["id"]: o for o in s.get("opportunities", [])}
    return index


def _label(item: dict) -> str | None:
    conf = item.get("confidence")
    label = conf.get("label") if isinstance(conf, dict) else conf
    return label if label in LEVELS else None


def validate_briefs(raw: list[PostBriefOut], s: dict, *, hooks: dict[str, dict], hook_id_of: dict[str, str],
                    channels: list[dict], intake: dict | None, news: list[dict] = (),
                    guardrails: dict | None = None, stats: Any = None) -> list[dict]:
    """Briefs whose every key point traces to pack items; the user's channels first."""
    c = cfg()
    index = item_index(s)
    lexicon = {it["id"] for it in s.get("lexicon", [])}
    news_ids = {h["id"] for h in news}
    g = guardrails or s.get("guardrails_draft") or {}
    phrases = {p.casefold(): p for p in (g.get("not_this", []) + g.get("never_claim", []))}
    mine = user_channels(intake)
    allowed = set(mine) | {PLAN_TO_POST[ch["platform"]] for ch in channels if ch["platform"] in PLAN_TO_POST}

    def drop(why: str) -> None:
        if stats is not None:
            stats.drop(why)

    def items_of(ids: list[str]) -> list[str]:
        """Item ids that exist; a hook stands for the items it is built on."""
        out: list[str] = []
        for raw_id in ids:
            i = raw_id.strip().upper()
            i = hook_id_of.get(i, i)
            if i in index:
                out.append(i)
            elif i in hooks:
                out += [w for w in hooks[i]["why_ids"] if w in index]
        return list(dict.fromkeys(out))

    kept: list[dict] = []
    for b in raw:
        channel = b.channel.strip().lower()
        if channel not in PostChannel.__members__ or channel not in allowed:
            drop("post_brief_channel_without_evidence")
            continue
        points = []
        for kp in b.key_points[:c["key_points_max"]]:
            ids = items_of(kp.item_ids)
            evidence = list(dict.fromkeys(e for i in ids for e in index[i].get("evidence_ids", [])
                                          [:c["evidence_per_key_point"]]))
            if kp.text.strip() and ids and evidence:
                points.append({"text": kp.text.strip(), "item_ids": ids, "evidence_ids": evidence})
            else:
                drop("key_point_without_evidence")
        if len(points) < c["key_points_min"]:
            drop("post_brief_under_min_key_points")
            continue
        used = list(dict.fromkeys(items_of(b.based_on) + [i for p in points for i in p["item_ids"]]))
        labels = [lab for i in used if (lab := _label(index[i]))]
        hook_id = hook_id_of.get((b.hook_id or "").strip().upper())
        nws = (b.news_hook_id or "").strip().upper()
        fmt = b.format.strip().lower()
        kept.append({
            "channel": channel, "role": b.role.strip(), "goal": b.goal.strip(),
            "hook": b.hook.strip() or (hooks[hook_id]["text"] if hook_id else ""), "hook_id": hook_id,
            "angle": b.angle.strip(), "key_points": points, "structure": b.structure.strip(),
            "format": fmt if fmt in PostFormat.__members__ else "text_post",
            "their_words_to_use": list(dict.fromkeys(w.strip().upper() for w in b.their_words_to_use
                                                     if w.strip().upper() in lexicon)),
            "cta": b.cta.strip(),
            "avoid": list(dict.fromkeys(phrases[a.strip().casefold()] for a in b.avoid
                                        if a.strip().casefold() in phrases)),
            "news_hook_id": nws if nws in news_ids else None,
            "based_on": used, "success_measure": b.success_measure.strip(),
            "confidence": min(labels, key=LEVELS.index) if labels else "speculative"})
    rank = {ch: n for n, ch in enumerate(mine)}
    kept.sort(key=lambda b: rank.get(b["channel"], len(rank)))   # stable: the model's order inside a channel
    kept = kept[:c["briefs_max"]]
    for n, b in enumerate(kept, 1):
        b["id"] = f"PST-{n:02d}"
    if stats is not None and len(kept) < c["briefs_min"]:
        stats.drop(f"post_briefs_short_{c['briefs_min'] - len(kept)}")
    return kept


# --------------------------------------------------------------------------
# Drafts (one call in the playbook stage) and their checks in code
# --------------------------------------------------------------------------


class DraftOut(BaseModel):
    post_brief_id: str
    title: str | None = None
    body: str = ""


class DraftList(BaseModel):
    drafts: list[DraftOut] = Field(default_factory=list)


_SENTENCE = re.compile(r"[^.!?\n]+(?:[.!?]+|\n|$)")
_LIST_MARK = re.compile(r"^\s*(?:\d{1,2}[.)]|(?:slide|step|day|week|part|tip|scene)\s*\d{1,2}\b[:.)-]?)", re.I)
_NUMBER = re.compile(r"[$€£]\s?\d[\d.,]*|\d[\d.,]*\s?(?:%|percent|procent|prozent|euro|eur|usd|kcal|kg|g\b)|\d+(?:[.,]\d+)?",
                     re.I)


def _numbers(text: str) -> set[str]:
    return {re.sub(r"[^\d]", "", m) for m in _NUMBER.findall(text or "") if re.sub(r"[^\d]", "", m)}


def check_draft(body: str, *, allowed_numbers: set[str], forbidden: list[str], max_chars: int) -> tuple[str, int]:
    """(clean body, sentences removed). A sentence goes when it uses a forbidden phrase, or states a number
    (amount, share, price) that the brief's cited posts do not contain. List markers ("1.", "Slide 2") are not
    claims. The result is cut at a sentence end to max_chars."""
    low_forbidden = [f.casefold() for f in forbidden if len(f.strip()) >= 3]
    out, removed = [], 0
    for line in body.splitlines(keepends=True):
        kept_line = []
        for sentence in _SENTENCE.findall(line):
            core = _LIST_MARK.sub("", sentence)
            if any(f in sentence.casefold() for f in low_forbidden) or (_numbers(core) - allowed_numbers):
                removed += 1
                continue
            kept_line.append(sentence)
        text = "".join(kept_line)
        if text.strip() or not line.strip():
            out.append(text if text.endswith("\n") or not line.endswith("\n") else text + "\n")
    clean = re.sub(r"\n{3,}", "\n\n", "".join(out)).strip()
    if len(clean) > max_chars:
        cut = clean[:max_chars]
        end = max(cut.rfind(". "), cut.rfind("! "), cut.rfind("? "), cut.rfind("\n"))
        clean = (cut[:end + 1] if end > max_chars // 2 else cut).rstrip()
    return clean, removed


def drafts_prompt(briefs: list[dict], s: dict, evidence: dict[str, dict], brand_voice: str | None,
                  brief_text: str) -> str:
    c = cfg()
    lex = {it["id"]: it for it in s.get("lexicon", [])}
    g = s.get("guardrails_draft") or {}
    parts = [f"{brief_text}\n\nBrand voice: {brand_voice or 'none - write neutral-professional'}",
             f"Say this: {'; '.join(g.get('say_this', []))}", f"Not this: {'; '.join(g.get('not_this', []))}"]
    for b in briefs:
        words = "; ".join(f"{lex[w]['term']} = {lex[w]['meaning']}" for w in b["their_words_to_use"] if w in lex)
        posts = "\n".join(untrusted(e, evidence[e]["text"]) for p in b["key_points"] for e in p["evidence_ids"]
                          if e in evidence)
        parts.append(
            f"--- {b['id']} | {b['channel']} | {b['format']} | at most {c['draft_chars'][b['format']]} characters\n"
            f"For: {b['role']}\nGoal: {b['goal']}\nHook: {b['hook']}\nAngle: {b['angle']}\n"
            f"Structure: {b['structure']}\nKey points:\n" + "\n".join(f"- {p['text']}" for p in b["key_points"])
            + f"\nTheir words: {words or '-'}\nCall to action: {b['cta']}\nAvoid: {'; '.join(b['avoid']) or '-'}"
            + "\nWhat people actually wrote (the only source for facts and numbers):\n" + posts)
    return "\n\n".join(parts)


def _fake_drafts(user: str) -> dict:
    ids = re.findall(r"^--- (PST-\d+) \|", user, flags=re.M)
    return {"drafts": [{"post_brief_id": i, "title": None,
                        "body": "Fake draft opening line.\nWe asked people what gets in the way. "
                                "Most said 90% of it is time. Tell us yours in the comments!"} for i in ids]}


async def write_drafts(briefs: list[dict], s: dict, evidence: list[dict], brand_voice: str | None,
                       brief_text: str) -> tuple[list[dict], float]:
    """(drafts for the first briefs, cost). Code removes what the evidence does not support."""
    c = cfg()
    first = briefs[:c["drafts"]]
    if not first:
        return [], 0.0
    ev = {e["id"]: e for e in evidence}
    res = await structured("reasoner", load_prompt("drafts"), drafts_prompt(first, s, ev, brand_voice, brief_text),
                           DraftList, "record_drafts", description="Record the drafts.",
                           max_tokens=c["draft_max_tokens"], fake=_fake_drafts)
    by_id = {b["id"]: b for b in first}
    g = s.get("guardrails_draft") or {}
    drafts: list[dict] = []
    for d in res.data.drafts:
        b = by_id.pop(d.post_brief_id.strip().upper(), None)
        if not b or not d.body.strip():
            continue
        cited = [e for p in b["key_points"] for e in p["evidence_ids"]]
        allowed = set().union(*(_numbers(ev[e]["text"]) | _numbers(ev[e].get("text_en") or "")
                                for e in cited if e in ev))
        body, removed = check_draft(d.body, allowed_numbers=allowed,
                                    forbidden=g.get("not_this", []) + g.get("never_claim", []) + b["avoid"],
                                    max_chars=c["draft_chars"][b["format"]])
        if not body:
            continue
        title, _ = check_draft(d.title or "", allowed_numbers=allowed, forbidden=b["avoid"], max_chars=200)
        drafts.append({"id": f"DRF-{len(drafts) + 1:02d}", "post_brief_id": b["id"], "channel": b["channel"],
                       "format": b["format"], "title": title or None, "body": body,
                       "voice": "brand" if brand_voice else "neutral", "evidence_ids": list(dict.fromkeys(cited)),
                       "removed_sentences": removed})
    return drafts, res.usd


# --------------------------------------------------------------------------
# Content calendar (code)
# --------------------------------------------------------------------------


def _weekday(text: str) -> str | None:
    low = (text or "").casefold()
    return next((d for d in DAYS if d in low), None)


def build_calendar(briefs: list[dict], channels: list[dict], this_week: list[dict], news: list[dict],
                   start: date | None = None) -> list[dict]:
    """4 weeks of post ideas: a news-hook brief in its week, days from timing chips or this week's plan,
    never more posts a week on a channel than its plan recommends."""
    c = cfg()
    start = start or date.today()
    weeks = c["calendar_weeks"]
    plan_of = {PLAN_TO_POST.get(ch["platform"]): ch for ch in channels if ch["platform"] in PLAN_TO_POST}
    news_by_id = {h["id"]: h for h in news}
    plan_days = {PLAN_TO_POST.get(w["platform"]): w["day"] for w in this_week}
    used: dict[tuple[str, int], int] = {}
    taken_days: dict[int, set[str]] = {}
    out: list[dict] = []

    def cap(channel: str) -> int:
        n = (plan_of.get(channel) or {}).get("posts_per_week") or c["posts_per_week_default"]
        return max(1, min(int(n), c["posts_per_week_max"]))

    def free(channel: str, week: int) -> bool:
        return used.get((channel, week), 0) < cap(channel)

    def day_for(b: dict, week: int) -> tuple[str, str, str]:
        ch = plan_of.get(b["channel"]) or {}
        for t in ch.get("timing", []):
            if (d := _weekday(t.get("when", "")) or _weekday(t.get("label", ""))):
                how = "seen in posts" if t.get("claim_type") == "observed" else "from a cited source"
                return d, f"{t['label']} ({t['when']}; {how})", "channel_timing"
        if b["channel"] in plan_days:
            return plan_days[b["channel"]], "the day this week's plan uses for this channel", "spread"
        day = next((d for d in c["calendar_days"] if d not in taken_days.get(week, set())), c["calendar_days"][0])
        return day, "spread across the month", "spread"

    for b in briefs:
        hook = news_by_id.get(b.get("news_hook_id") or "")
        placed = False
        delta = (date.fromisoformat(hook["date"]) - start).days if hook else weeks * 7
        if hook and delta < weeks * 7:  # recent news: week 1; an upcoming date: its own week and weekday
            week = max(1, delta // 7 + 1)
            if free(b["channel"], week):
                day = DAYS[date.fromisoformat(hook["date"]).weekday()] if delta >= 0 else day_for(b, week)[0]
                out.append({"week": week, "suggested_day": day, "channel": b["channel"], "post_brief_id": b["id"],
                            "timing_reason": f"rides the news: {hook['headline']} ({hook['date']})",
                            "timing_kind": "news_hook"})
                placed = True
        if not placed:
            options = [w for w in range(1, weeks + 1) if free(b["channel"], w)]
            if not options:
                continue
            week = min(options, key=lambda w: (sum(1 for e in out if e["week"] == w), w))
            day, reason, kind = day_for(b, week)
            out.append({"week": week, "suggested_day": day, "channel": b["channel"], "post_brief_id": b["id"],
                        "timing_reason": reason, "timing_kind": kind})
        entry = out[-1]
        used[(entry["channel"], entry["week"])] = used.get((entry["channel"], entry["week"]), 0) + 1
        taken_days.setdefault(entry["week"], set()).add(entry["suggested_day"])
    out.sort(key=lambda e: (e["week"], DAYS.index(e["suggested_day"])))
    for n, e in enumerate(out, 1):
        e.update(id=f"CAL-{n:02d}", status="idea")
    return out


def week_start(generated: date) -> date:
    """Calendar week 1 starts on the Monday after the pack is made."""
    return generated + timedelta(days=(7 - generated.weekday()) % 7 or 7)
