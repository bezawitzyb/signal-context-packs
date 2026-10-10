"""Playbook call (F4-11, PRD FR-D3): ONE reasoner call from verified items - the only call that sees brand voice.

do_first (3), channel_plan (>= 3, with posts_per_week), hooks (10-15), creative
brief, objection handling, keywords, targets, this_week (5) and post briefs (5-8,
V8; validated in synthesis/posts.py). Code keeps only references to
items that exist in the verified pack: an action, channel or hook whose
why_ids are all unknown is dropped ("no channel without evidence"), hooks
are renumbered and this_week follows them.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any

from pydantic import BaseModel, Field, field_validator

from ctxpack.config import load_yaml
from ctxpack.llm.client import load_prompt, structured, untrusted
from ctxpack.schemas.enums import Level, Platform, TargetKind
from ctxpack.synthesis import posts
from ctxpack.synthesis.write import INSIGHT_SECTIONS

DAYS = ("monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday")


def _level(value: object) -> str:
    v = str(value or "").strip().lower()
    return v if v in Level.__members__ else "medium"


class DoFirstOut(BaseModel):
    action: str
    why: str = ""
    why_ids: list[str] = Field(default_factory=list)
    effort: str = "medium"
    impact: str = "medium"
    owner_hint: str = ""
    success_measure: str = ""
    goal: str | None = None

    _effort = field_validator("effort", mode="before")(_level)
    _impact = field_validator("impact", mode="before")(_level)


class ChannelOut(BaseModel):
    platform: str
    why: str = ""
    why_ids: list[str] = Field(default_factory=list)
    formats: list[str] = Field(default_factory=list)
    communities_or_hashtags: list[str] = Field(default_factory=list)
    tone_note: str = ""
    posts_per_week: int | None = None


class HookOut(BaseModel):
    text: str
    why_ids: list[str] = Field(default_factory=list)


class CreativeBriefOut(BaseModel):
    objective: str = ""
    audience: str = ""
    insight: str = ""
    message: str = ""
    tone: str = ""
    mandatories: list[str] = Field(default_factory=list)
    avoid: list[str] = Field(default_factory=list)
    item_ids: list[str] = Field(default_factory=list)


class HandlingOut(BaseModel):
    objection_id: str
    response: str


class KeywordsOut(BaseModel):
    seo: list[str] = Field(default_factory=list)
    paid: list[str] = Field(default_factory=list)
    negatives: list[str] = Field(default_factory=list)
    hashtags: list[str] = Field(default_factory=list)


class TargetOut(BaseModel):
    name: str
    kind: str = "community"
    platform: str
    url: str | None = None
    why_ids: list[str] = Field(default_factory=list)


class PositionOut(BaseModel):
    statement: str = ""
    for_whom: str = ""
    against_doubt: str = ""
    item_ids: list[str] = Field(default_factory=list)


class PlanPostOut(BaseModel):
    day: str
    platform: str
    format: str
    hook_id: str
    angle: str
    moment_id: str | None = None
    news_hook_id: str | None = None
    why_now: str = ""


class GoalBlockOut(BaseModel):
    goal: str
    headline: str = ""
    first_moves: list[str] = Field(default_factory=list)
    success_measure: str = ""
    item_ids: list[str] = Field(default_factory=list)


class PlaybookOut(BaseModel):
    position: PositionOut | None = None
    for_goals: list[GoalBlockOut] = Field(default_factory=list)
    do_first: list[DoFirstOut] = Field(default_factory=list)
    channel_plan: list[ChannelOut] = Field(default_factory=list)
    hooks: list[HookOut] = Field(default_factory=list)
    creative_brief: CreativeBriefOut | None = None
    objection_handling: list[HandlingOut] = Field(default_factory=list)
    keywords: KeywordsOut = Field(default_factory=KeywordsOut)
    targets: list[TargetOut] = Field(default_factory=list)
    this_week: list[PlanPostOut] = Field(default_factory=list)
    post_briefs: list[posts.PostBriefOut] = Field(default_factory=list)


# --------------------------------------------------------------------------
# Prompt
# --------------------------------------------------------------------------


def _line(it: dict, section: str) -> str:
    c = it.get("confidence", {})
    head = f"{it['id']} | {section} | {c.get('label', '-')} | {it.get('counts', {}).get('matching', '-')} posts"
    flags = f" | non_obvious {it.get('non_obvious', False)} | safe_to_assert {it.get('safe_to_assert', False)}"
    if section == "tensions":
        return head + flags + f" | {it['claim']} (want: {it['want']['text']} / but: {it['but']['text']})"
    return head + flags + f" | {it.get('label') or it.get('name') or ''} {it['claim']}".rstrip()


def build_prompt(s: dict, brief: str, brand_voice: str | None, news: list[dict] = (),
                 intake: dict | None = None) -> str:
    lines = [_line(it, name) for name in INSIGHT_SECTIONS if name not in ("lexicon", "phrases") for it in s[name]]
    lines += [f"{o['id']} | opportunity | score {o['score']:.2f} | {o['title']}: {o['description']}"
              for o in s["opportunities"]]
    lines += [f"{c['id']} | competitor | {c['mentions']} mentions | {c['name']}: {c['tone']}" for c in s["competitors"]]
    lines += [f"{p['id']} | platform_lens | {p['platform']} ({p['kept_posts']} posts): {p['tone']}"
              for p in s["platform_lens"]]
    lines += [f"{p['id']} | what_performs | {p['platform']} {p['format']}: {p['why_it_worked']}"
              for p in s["what_performs"]]
    lines += [f"{h['id']} | hypothesis | {h['status']} | {h['statement']}" for h in s["hypotheses"]]
    lines += [_line(it, "brand_perception") for it in s.get("brand_findings", [])]
    lines += [f"{h['id']} | news_hook | {h['date']} | {h['headline']}: {h['why_it_matters']}" for h in news]
    words = ([f"{it['id']}: {it['term']} = {it['meaning']}" for it in s["lexicon"]]
             + [f"{it['id']}: {it['text']}" for it in s["phrases"]])
    g = s.get("guardrails_draft", {})
    voice = s.get("voice", {})
    mine = posts.user_channels(intake)
    goals = [str(g) for g in (intake or {}).get("goals") or []]
    return (f"{brief}\n\nBrand voice: {brand_voice or 'none (stay brand-neutral)'}\n"
            f"The user's own channels: {', '.join(mine) if mine else 'not given (use your channel plan)'}\n"
            f"Goal ids for the goal blocks, main first: {', '.join(goals) if goals else 'none given'}\n\n"
            "Verified items (id | section | confidence | posts | flags | text):\n" + "\n".join(lines)
            + "\n\nAudience words (lexicon and phrases):\n" + untrusted("audience_words", "\n".join(words))
            + f"\n\nVoice: {voice.get('tone', '')}\nCode-switching: {voice.get('code_switching') or 'none'}"
            + f"\nSay this: {'; '.join(g.get('say_this', []))}\nNot this: {'; '.join(g.get('not_this', []))}")


def _fake(user: str) -> dict:
    ids = re.findall(r"^(\w+-\d+) \|", user, flags=re.M)
    ten = next((i for i in ids if i.startswith("TEN")), ids[0] if ids else "THM-01")
    mom = next((i for i in ids if i.startswith("MOM")), None)
    nws = next((i for i in ids if i.startswith("NWS")), None)
    obj = [i for i in ids if i.startswith("OBJ")][:2]
    backed = [i for i in ids if i.split("-")[0] in ("TEN", "PAIN", "OBJ", "THM", "MOT", "SEG", "MOM")] or [ten]
    goals = re.search(r"^Goal ids for the goal blocks, main first: (.+)$", user, flags=re.M)
    goal_ids = [] if not goals or goals.group(1) == "none given" else [g.strip() for g in goals.group(1).split(",")]
    brp = [i for i in ids if i.startswith("BRP")]
    return {
        "position": {"statement": "Fake position", "for_whom": "Fake audience", "against_doubt": "Fake doubt",
                     "item_ids": [ten]},
        "for_goals": [{"goal": g, "headline": f"Fake headline for {g}", "first_moves": [f"DO-0{n % 3 + 1}"],
                       "success_measure": "Fake goal measure",
                       "item_ids": brp[:1] if g == "brand_perception" and brp else [ten]}
                      for n, g in enumerate(goal_ids)],
        "do_first": [{"action": f"Fake action {n}", "why": "Fake.", "why_ids": [ids[n % len(ids)]],
                      "effort": "low", "impact": "high", "owner_hint": "social team",
                      "success_measure": "Fake measure", "goal": goal_ids[0] if goal_ids else None}
                     for n in range(3)],
        "channel_plan": [{"platform": p, "why": "Fake.", "why_ids": [ten], "formats": ["post"]}
                         for p in ("web_forum", "instagram", "tiktok")],
        "hooks": [{"text": f"Fake hook {n} lekker", "why_ids": [ten]} for n in range(1, 11)],
        "creative_brief": {"objective": "Fake", "audience": "Fake", "insight": "Fake", "message": "Fake",
                           "tone": "dry", "item_ids": [ten]},
        "objection_handling": [{"objection_id": o, "response": "Fake."} for o in obj],
        "keywords": {"seo": ["chips"], "paid": ["borrelnootjes"], "negatives": ["recept"], "hashtags": ["#borrel"]},
        "targets": [{"name": "forum.fok.nl", "kind": "community", "platform": "web_forum", "why_ids": [ten]}],
        "this_week": [{"day": d, "platform": "instagram", "format": "reel", "hook_id": f"HOOK-{n:02d}",
                       "angle": "Fake", "moment_id": mom, "news_hook_id": nws if n == 1 else None,
                       "why_now": "Fake."}
                      for n, d in enumerate(DAYS[:5], 1)],
        "post_briefs": [{"channel": ch, "role": "Fake role", "goal": "Fake goal", "hook": f"Fake brief hook {n}",
                         "hook_id": f"HOOK-{n:02d}", "angle": "Fake angle",
                         "key_points": [{"text": f"Fake point {k}", "item_ids": [backed[(n + k) % len(backed)]]}
                                        for k in range(3)],
                         "structure": "story -> lesson -> question", "format": fmt,
                         "their_words_to_use": [i for i in ids if i.startswith("LEX")][:2], "cta": "Fake CTA",
                         "avoid": [], "news_hook_id": nws if n == 1 else None, "based_on": [ten],
                         "success_measure": "Fake post measure"}
                        for n, (ch, fmt) in enumerate([("instagram", "carousel"), ("tiktok", "short_video"),
                                                       ("web_forum", "text_post"), ("instagram", "text_post"),
                                                       ("tiktok", "short_video"), ("web_forum", "text_post")], 1)],
    }


# --------------------------------------------------------------------------
# Validation (code)
# --------------------------------------------------------------------------


@dataclass
class PlaybookStats:
    dropped: dict[str, int] = field(default_factory=dict)
    hooks_without_tension: int = 0

    def drop(self, what: str) -> None:
        self.dropped[what] = self.dropped.get(what, 0) + 1


def known_ids(s: dict) -> set[str]:
    sections = INSIGHT_SECTIONS + ["opportunities", "competitors", "platform_lens", "what_performs", "hypotheses",
                                   "risks", "brand_findings"]
    return {it["id"] for name in sections for it in s.get(name, [])}


def validate(out: PlaybookOut, s: dict, stats: PlaybookStats, news: list[dict] = (),
             intake: dict | None = None) -> dict[str, Any]:
    """Playbook parts with ids, every reference pointing at an existing item."""
    known = known_ids(s)
    platforms = set(Platform.__members__)

    def refs(ids: list[str]) -> list[str]:
        return list(dict.fromkeys(i.strip().upper() for i in ids if i.strip().upper() in known))

    goals = [str(g) for g in (intake or {}).get("goals") or []]
    do_first, do_id_of = [], {}
    for n, o in enumerate(out.do_first, 1):
        if (why := refs(o.why_ids)) and len(do_first) >= 3:
            continue
        if why:
            do_id_of[f"DO-{n:02d}"] = f"DO-{len(do_first) + 1:02d}"
            goal = (o.goal or "").strip().lower()
            do_first.append({"id": f"DO-{len(do_first) + 1:02d}", "action": o.action, "why": o.why, "why_ids": why,
                             "effort": o.effort, "impact": o.impact, "owner_hint": o.owner_hint,
                             "success_measure": o.success_measure.strip(), "goal": goal if goal in goals else None})
        else:
            stats.drop("do_first_without_evidence")
    blocks = {}
    for o in out.for_goals:  # V12: one block per confirmed goal, in the user's order; references checked
        goal = o.goal.strip().lower()
        if goal not in goals or goal in blocks or not o.headline.strip():
            stats.drop("goal_block_invalid")
            continue
        blocks[goal] = {"goal": goal, "headline": o.headline.strip(), "success_measure": o.success_measure.strip(),
                        "first_moves": list(dict.fromkeys(do_id_of[m.strip().upper()] for m in o.first_moves
                                                          if m.strip().upper() in do_id_of)),
                        "item_ids": refs(o.item_ids)}
    for_goals = [blocks[g] for g in goals if g in blocks]
    channels = []
    for o in out.channel_plan:
        why = refs(o.why_ids)
        if o.platform not in platforms or not why:
            stats.drop("channel_without_evidence_or_platform")
            continue
        cadence = o.posts_per_week if o.posts_per_week and 1 <= o.posts_per_week <= 7 else None
        channels.append({"id": f"CHN-{len(channels) + 1:02d}", "priority": len(channels) + 1,
                         "platform": o.platform, "why": o.why, "why_ids": why, "formats": o.formats,
                         "communities_or_hashtags": o.communities_or_hashtags, "tone_note": o.tone_note,
                         "posts_per_week": cadence})

    hooks, hook_id_of = [], {}
    for n, o in enumerate(out.hooks, 1):
        why = refs(o.why_ids)
        if not why or len(hooks) >= 15:
            stats.drop("hook_without_evidence_or_over_15")
            continue
        if not any(i.startswith("TEN-") for i in why):
            stats.hooks_without_tension += 1
        hook_id_of[f"HOOK-{n:02d}"] = f"HOOK-{len(hooks) + 1:02d}"
        hooks.append({"id": hook_id_of[f"HOOK-{n:02d}"], "text": o.text.strip(), "why_ids": why})

    cb = None
    if out.creative_brief:
        cb = {**out.creative_brief.model_dump(), "item_ids": refs(out.creative_brief.item_ids)}
    objections = {it["id"] for it in s["objections"]}
    handling = [{"objection_id": o.objection_id.strip().upper(), "response": o.response}
                for o in out.objection_handling if o.objection_id.strip().upper() in objections]
    targets = [{"name": o.name, "kind": o.kind, "platform": o.platform, "url": o.url, "why_ids": refs(o.why_ids)}
               for o in out.targets if o.kind in TargetKind.__members__ and o.platform in platforms]
    moments = {it["id"] for it in s["moments"]}
    news_ids = {h["id"] for h in news}
    week = []
    for o in out.this_week:
        hook = hook_id_of.get(o.hook_id.strip().upper())
        if not hook or o.day.strip().lower() not in DAYS or o.platform not in platforms or len(week) >= 5:
            stats.drop("plan_post_invalid")
            continue
        moment = (o.moment_id or "").strip().upper()
        nws = (o.news_hook_id or "").strip().upper()
        week.append({"id": f"PLN-{len(week) + 1:02d}", "day": o.day.strip().lower(), "platform": o.platform,
                     "format": o.format, "hook_id": hook, "angle": o.angle,
                     "moment_id": moment if moment in moments else None,
                     "news_hook_id": nws if nws in news_ids else None, "why_now": o.why_now})
    briefs = posts.validate_briefs(out.post_briefs, s, hooks={h["id"]: h for h in hooks}, hook_id_of=hook_id_of,
                                   channels=channels, intake=intake, news=news, stats=stats)
    position = None
    if out.position and out.position.statement.strip():
        if pos_ids := refs(out.position.item_ids):
            position = {"statement": out.position.statement.strip(), "for_whom": out.position.for_whom.strip(),
                        "against_doubt": out.position.against_doubt.strip(), "item_ids": pos_ids}
        else:
            stats.drop("position_without_evidence")
    return {"position": position, "do_first": do_first[:3], "for_goals": for_goals, "channel_plan": channels,
            "playbook": {"hooks": hooks, "creative_brief": cb, "objection_handling": handling,
                         "keywords": out.keywords.model_dump(), "targets": targets, "this_week": week},
            "post_briefs": briefs}


async def write_playbook(s: dict, brief: str, brand_voice: str | None, news: list[dict] = (),
                         intake: dict | None = None,
                         evidence: list[dict] = ()) -> tuple[dict, PlaybookStats, float]:
    """(validated playbook parts with post briefs and drafts, stats, cost). Brand voice is used in this
    stage (this call and the drafts call) and nowhere else."""
    res = await structured("reasoner", load_prompt("playbook"), build_prompt(s, brief, brand_voice, news, intake),
                           PlaybookOut, "record_playbook", description="Record the playbook.",
                           max_tokens=load_yaml("modes")["synthesis"]["playbook_max_tokens"],
                           fake=_fake)
    stats = PlaybookStats()
    parts = validate(res.data, s, stats, news, intake)
    parts["drafts"], usd = await posts.write_drafts(parts["post_briefs"], s, list(evidence), brand_voice, brief)
    return parts, stats, res.usd + usd
