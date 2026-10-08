"""Quick brief (change V9): half a page to paste into ChatGPT or Claude before writing.

Audience and goal, the position, the top 3 findings with their strength, their
words, 3 things to say and 3 to avoid. Lists shrink until it fits
modes.yaml exports.quick_brief_max_words; the quote rule always stays.
"""

from __future__ import annotations

from ctxpack.exports.common import cfg, inline


def to_quick_brief(pack: dict) -> str:
    i = pack["brief"]["interpreted"]
    g = pack["guardrails"]
    snap = pack["snapshot"]
    goal = (pack["brief"].get("intake") or {}).get("goal")
    sizes = {"words": 8, "say": 3, "not": 3, "findings": 3}

    def build() -> str:
        L = [f"WHO: {inline(i['audience'])} in {i['market']}, about {inline(i['topic'])}."
             + (f" GOAL: {inline(goal)}." if goal else "")]
        if snap.get("position"):
            p = snap["position"]
            L.append(f"POSITION: {inline(p['statement'])} - for {inline(p['for_whom'])}, answering "
                     f"{inline(p['against_doubt'])}.")
        L.append("WHAT WE HEARD:")
        findings = snap.get("findings") or [{"text": t["text"], "strength_text": ""} for t in snap["five_truths"]]
        L += [f"- {inline(f['text'])}" + (f" ({f['strength_text']})" if f.get("strength_text") else "")
              for f in findings[:sizes["findings"]]]
        lex = pack["voice"]["lexicon"][:sizes["words"]]
        if lex:
            L.append("THEIR WORDS: " + "; ".join(f"{inline(x['term'])} = {inline(x['meaning'])}" for x in lex))
        L.append("DO: " + "; ".join(inline(x) for x in g["say_this"][:sizes["say"]]))
        L.append("DON'T: " + "; ".join(inline(x) for x in (g["not_this"] + g["never_claim"])[:sizes["not"]]))
        L.append("State as fact only what is marked strong; say \"people tell us...\" for the rest. "
                 + g["quote_reuse_note"])
        return "\n".join(L) + "\n"

    text = build()
    limit = cfg()["quick_brief_max_words"]
    for key in ("words", "findings", "say", "not") * 10:
        if len(text.split()) <= limit:
            break
        sizes[key] = max(1, sizes[key] - 1)
        text = build()
    return text
