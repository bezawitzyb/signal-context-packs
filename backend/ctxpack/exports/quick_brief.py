"""Quick brief (change V9; exports audit 2026-10-10): paste into ChatGPT or Claude to write ONE post now.

Who, the main goal, the position (each part on its own labelled line, so languages never mix mid-sentence), the
3 main findings with their strength, their words, say / don't say / don't claim without a legal check, the rules
in plain words, and a last line to fill in. No ids and no quotes (an AI may paste a quote into a public post).
Lists shrink until it fits modes.yaml exports.quick_brief_max_words; the 3 findings and the rules always stay.
"""

from __future__ import annotations

from ctxpack.exports.common import cfg, inline
from ctxpack.exports.plain import NEVER_LABEL, QUICK_RULES, findings, guardrails, legal_note, sentence
from ctxpack.schemas.plan import confirmed_goal


def to_quick_brief(pack: dict) -> str:
    i = pack["brief"]["interpreted"]
    g = guardrails(pack)
    snap = pack["snapshot"]
    goal = confirmed_goal(pack["brief"].get("intake"))
    sizes = {"words": 8, "say": 4, "not": 3, "never": 4}

    def build() -> str:
        L = [f"WHO: {sentence(i['audience'])} Market: {i['market']}. Topic: {sentence(i['topic'])}"]
        if goal:
            L.append(f"GOAL: {sentence(goal)}")
        main = (snap.get("for_goals") or [None])[0]   # what the pack means for the main goal
        if main:
            L.append(f"WHAT THIS MEANS FOR YOUR MAIN GOAL: {sentence(main['headline'])}")
        if p := snap.get("position"):
            L += [f"POSITION: {sentence(p['statement'])}", f"  For: {sentence(p['for_whom'])}",
                  f"  The doubt it answers: {sentence(p['against_doubt'])}"]
            if note := legal_note(pack, text=p["statement"]):
                L.append(f"  {note}")
        L.append("WHAT WE HEARD (strength in brackets):")
        L += [f"- {sentence(f['text'])}" + (f" ({f['strength_text']})" if f.get("strength_text") else "")
              for f in findings(pack, 3)]
        if lex := pack["voice"]["lexicon"][:sizes["words"]]:
            L.append("THEIR WORDS: " + "; ".join(f"{inline(x['term'])} = {inline(x['meaning'])}" for x in lex))
        if say := g["say_this"][:sizes["say"]]:
            L.append("SAY: " + "; ".join(inline(x) for x in say))
        if nots := g["not_this"][:sizes["not"]]:
            L.append("DON'T SAY: " + "; ".join(inline(x) for x in nots))
        if never := g["never_claim"][:sizes["never"]]:
            L.append(f"{NEVER_LABEL.upper()}: " + "; ".join(inline(x) for x in never))
        L.append(f"RULES: {QUICK_RULES}")
        L.append("NOW WRITE: [describe the post you need - channel, format, what it should achieve]")
        return "\n".join(L) + "\n"

    text = build()
    limit = cfg()["quick_brief_max_words"]
    for key in ("words", "never", "say", "not") * 10:
        if len(text.split()) <= limit:
            break
        sizes[key] = max(1, sizes[key] - 1)
        text = build()
    return text
