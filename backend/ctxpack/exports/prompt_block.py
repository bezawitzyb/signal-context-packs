"""Brief for your AI writer (exports audit 2026-10-10): the creative brief for a campaign or a series of posts.

Paste into ChatGPT or Claude, or hand to a copywriter. Plain labelled sections: audience and segments, position,
goals, do first, their words and tone, creative angles (tensions), objections and how to answer them, hooks,
every post brief in full, channels, guardrails and the rules in plain words. Anything the compliance check flagged
carries "Check with legal first". No ids or field names (the pack link at the end leads to them); speculative
items are left out and the brief says so. Lists shrink until it fits modes.yaml exports.prompt_block_max_tokens;
post briefs, guardrails and rules are never trimmed.
"""

from __future__ import annotations

from ctxpack.exports.calendar_csv import pack_link
from ctxpack.exports.common import DISCLAIMER, cfg, inline, tokens
from ctxpack.exports.plain import (NEVER_LABEL, PLAIN_RULES, channel, evidence_line, fmt, guardrails, human_date,
                                   legal_note, sentence, strength)
from ctxpack.config import load_yaml


def _not_speculative(items: list[dict]) -> list[dict]:
    return [it for it in items if (it.get("confidence") or {}).get("label") != "speculative"]


def post_brief_lines(pack: dict, b: dict, n: int, words: dict[str, str]) -> list[str]:
    """One post brief in full, plain words (shared with the calendar's idea of a brief)."""
    L = [f"{n}. {channel(b['channel'])} {fmt(b['format'])} - for {inline(b['role'])} ({b['confidence']})",
         f"   Hook: {sentence(b['hook'])}", f"   Angle: {sentence(b['angle'])}",
         f"   Structure: {inline(b['structure'].replace('->', '→'))}",
         "   Key points:"]
    L += [f"   - {sentence(k['text'])}" for k in b["key_points"]]
    if b["their_words_to_use"]:
        L.append(f"   Their words: {', '.join(inline(words.get(w, w)) for w in b['their_words_to_use'])}")
    L.append(f"   Call to action: {sentence(b['cta'])}")
    if b["avoid"]:
        L.append(f"   Avoid: {'; '.join(inline(a) for a in b['avoid'])}")
    if b.get("success_measure"):
        L.append(f"   How you'll know it worked: {sentence(b['success_measure'])}")
    if note := legal_note(pack, b["id"], b["hook"]):
        L.append(f"   {note}")
    return L


def to_prompt_block(pack: dict) -> str:
    i = pack["brief"]["interpreted"]
    g = guardrails(pack)
    pb = pack["playbook"]
    snap = pack["snapshot"]
    chips = load_yaml("goals")["goals"]
    words = {x["id"]: x["term"] for x in pack["voice"]["lexicon"]}
    segments = _not_speculative(pack["segments"])
    tensions = _not_speculative(pack["tensions"])
    objections = _not_speculative(pack["objections"])
    left_out = sum(len(x) - len(_not_speculative(x)) for x in (pack["segments"], pack["tensions"], pack["objections"]))
    handling = {h["objection_id"]: h["response"] for h in pb["objection_handling"]}
    sizes = {"lexicon": 15, "hooks": 6, "segments": 3, "objections": 3, "tensions": 3, "channels": 4}

    def build() -> str:
        L = [f"CREATIVE BRIEF: {inline(i['topic'])} ({i['market']})",
             f"{evidence_line(pack)} Research from {human_date(pack['generated_at'])}.", "",
             "HOW TO USE THIS BRIEF"] + [f"- {r}" for r in PLAIN_RULES]
        L += ["", "AUDIENCE", sentence(i["audience"])]
        if segments[:sizes["segments"]]:
            L.append("Groups within it:")
            L += [f"- {inline(s.get('name') or '')}: {sentence(s['claim'])} ({strength(s)})"
                  for s in segments[:sizes["segments"]]]
        if p := snap.get("position"):
            L += ["", "POSITION", sentence(p["statement"]), f"For: {sentence(p['for_whom'])}",
                  f"The doubt it answers: {sentence(p['against_doubt'])}"]
            if note := legal_note(pack, text=p["statement"]):
                L.append(note)
        if snap.get("for_goals"):
            L += ["", "GOALS"]
            for blk in snap["for_goals"]:
                L.append(f"- {chips.get(blk['goal'], {}).get('chip', blk['goal'])}: {sentence(blk['headline'])}"
                         + (f" How you'll know: {sentence(blk['success_measure'])}" if blk.get("success_measure")
                            else ""))
        L += ["", "DO FIRST"]
        for n, d in enumerate(pack["do_first"], 1):
            L.append(f"{n}. {sentence(d['action'])}"
                     + (f" How you'll know: {sentence(d['success_measure'])}" if d.get("success_measure") else ""))
            if note := legal_note(pack, d["id"], d["action"]):
                L.append(f"   {note}")
        v = pack["voice"]
        L += ["", "THEIR WORDS"] + [f"- {inline(x['term'])} = {inline(x['meaning'])}"
                                    for x in v["lexicon"][:sizes["lexicon"]]]
        L.append(f"Tone: {sentence(v['tone'])}")
        if v.get("code_switching"):
            L.append(f"Mixing languages: {sentence(v['code_switching'])}")
        if tensions[:sizes["tensions"]]:
            L += ["", "CREATIVE ANGLES (where what they want meets what stops them)"]
            L += [f"- {sentence(t['claim'])} Want: {sentence(t['want']['text'])} But: {sentence(t['but']['text'])} "
                  f"({strength(t)})" for t in tensions[:sizes["tensions"]]]
        if objections[:sizes["objections"]]:
            L += ["", "OBJECTIONS AND HOW TO ANSWER THEM"]
            for o in objections[:sizes["objections"]]:
                L.append(f"- {sentence(o['claim'])} ({strength(o)})"
                         + (f" Answer: {sentence(handling[o['id']])}" if o["id"] in handling else ""))
        L += ["", "HOOKS (opening lines in their words)"]
        for h in pb["hooks"][:sizes["hooks"]]:
            L.append(f"- {sentence(h['text'])}")
            if note := legal_note(pack, h["id"], h["text"]):
                L.append(f"  {note}")
        if pack.get("post_briefs"):
            L += ["", "POST BRIEFS (write these; use only the facts in the key points)"]
            for n, b in enumerate(pack["post_briefs"], 1):
                L += post_brief_lines(pack, b, n, words)
        L += ["", "CHANNELS"]
        L += [f"{c['priority']}. {channel(c['platform'])}: {sentence(c['why'])} Formats: {inline(', '.join(c['formats']))}."
              + (f" Posts a week: {c['posts_per_week']}." if c.get("posts_per_week") else "")
              for c in pack["channel_plan"][:sizes["channels"]]]
        L += ["", "GUARDRAILS", f"- Say: {'; '.join(inline(s) for s in g['say_this']) or '-'}",
              f"- Don't say: {'; '.join(inline(s) for s in g['not_this']) or '-'}",
              f"- {NEVER_LABEL}: {'; '.join(inline(s) for s in g['never_claim']) or '-'}",
              f"- Sensitive: {'; '.join(sentence(s) for s in g['sensitivities']) or '-'}",
              f"- Quotes: {g['quote_reuse_note']}"]
        L += ["", "WHAT THIS BRIEF LEAVES OUT",
              "The research method, post counts per source and the weaker signals"
              + (f" ({left_out} speculative findings)" if left_out else "")
              + f". They are in the full report and the pack: {pack_link(pack)}", "", DISCLAIMER]
        return "\n".join(L) + "\n"

    text = build()
    limit = cfg()["prompt_block_max_tokens"]
    floors = {"lexicon": 8, "hooks": 3, "segments": 1, "objections": 2, "tensions": 2, "channels": 2}
    for key in ("lexicon", "hooks", "segments", "objections", "tensions", "channels") * 20:
        if tokens(text) <= limit:
            break
        sizes[key] = max(floors[key], sizes[key] - 1)
        text = build()
    return text
