"""Prompt block export (<= 1,800 tokens): paste into any AI tool before asking for content.

do first, lexicon, tensions, guardrails, channel plan, top hooks, this week and a
usage line. Lists shrink until it fits; the guardrails and the agent rules are
never trimmed.
"""

from __future__ import annotations

from ctxpack.exports.common import DISCLAIMER, cfg, inline, tokens


def to_prompt_block(pack: dict) -> str:
    i = pack["brief"]["interpreted"]
    g = pack["guardrails"]
    pb = pack["playbook"]
    sizes = {"lexicon": 20, "tensions": 4, "hooks": 8, "channels": 4, "do_first": 3, "week": 5}

    def build() -> str:
        L = [f"AUDIENCE CONTEXT ({pack['pack_id']}, {pack['generated_at'][:10]}): {inline(i['audience'])} in "
             f"{i['market']}, about {inline(i['topic'])}. From {pack['coverage']['counts']['relevant']} real public "
             f"posts{' (thin evidence: treat as early signals)' if pack['coverage']['thin_evidence'] else ''}.",
             "USE: write in their words, build on the tensions, follow the guardrails. Only claims marked "
             "SAFE may be stated as fact; say \"people say...\" for the rest. Cite ids (e.g. TEN-01) when you "
             "explain a choice.", "", "DO FIRST:"]
        L += [f"- {inline(d['action'])} [{d['id']}]" for d in pack["do_first"][:sizes["do_first"]]]
        L += ["", "THEIR WORDS (term = meaning):"]
        L += [f"- {inline(x['term'])} = {inline(x['meaning'])}" for x in pack["voice"]["lexicon"][:sizes["lexicon"]]]
        L += [f"Tone: {inline(pack['voice']['tone'])}", "", "TENSIONS (want / but):"]
        for t in pack["tensions"][:sizes["tensions"]]:
            safe = " SAFE" if t["safe_to_assert"] else ""
            L.append(f"- [{t['id']}, {t['confidence']['label']}{safe}] want: {inline(t['want']['text'])} / but: "
                     f"{inline(t['but']['text'])}")
        L += ["", "GUARDRAILS:", f"- Say: {inline('; '.join(g['say_this']))}",
              f"- Not: {inline('; '.join(g['not_this']))}",
              f"- Never claim: {inline('; '.join(g['never_claim'])) or '-'}",
              f"- Sensitive: {inline('; '.join(g['sensitivities'])) or '-'}",
              f"- {g['quote_reuse_note']}", "", "CHANNELS:"]
        L += [f"{c['priority']}. {c['platform']}: {inline(c['why'])} Formats: {inline(', '.join(c['formats']))}"
              for c in pack["channel_plan"][:sizes["channels"]]]
        L += ["", "TOP HOOKS:"]
        L += [f"- {inline(h['text'])} [{h['id']}]" for h in pb["hooks"][:sizes["hooks"]]]
        L += ["", "THIS WEEK:"]
        L += [f"- {w['day']}: {w['platform']} {inline(w['format'])} - {w['hook_id']} - {inline(w['angle'])}"
              for w in pb["this_week"][:sizes["week"]]]
        L += ["", "RULES FOR AI TOOLS:"] + [f"- {r}" for r in pack["instructions_for_agents"]]
        L += ["", DISCLAIMER]
        return "\n".join(L) + "\n"

    text = build()
    limit = cfg()["prompt_block_max_tokens"]
    for key in ("lexicon", "hooks", "channels", "tensions", "week") * 20:
        if tokens(text) <= limit:
            break
        sizes[key] = max(1, sizes[key] - 1)
        text = build()
    return text
