"""brief.md export ("Copy for Notion / Docs"), in pack-page order (PRD S3).

Confidence is always written in words with counts (never colour-only). Quotes
are real people's words: shown as quotes with their evidence id, and the
quote-reuse note is repeated next to them.
"""

from __future__ import annotations

from ctxpack.exports.common import DISCLAIMER, HOOKS_NOTE, badge, cell, inline, privacy_line



def _quotes(item: dict, limit: int = 1) -> list[str]:
    return [f"  > {inline(q['text'])} ({q['evidence_id']})" for q in item.get("quotes", [])[:limit]]


def _claims(items: list[dict], title_key: str | None = None) -> list[str]:
    """Items with emerging or better in full (one quote each); speculative ones on one line.
    Every item, quote and number stays in context_pack.json."""
    out = []
    weak = [it for it in items if (it.get("confidence") or {}).get("label") == "speculative"]
    for it in items:
        if it in weak:
            continue
        title = f"**{inline(it[title_key])}** - " if title_key and it.get(title_key) else ""
        out.append(f"- {title}{inline(it['claim'])} *[{it['id']}; {badge(it)}]*")
        out += _quotes(it)
    if weak:
        out.append("- *Also seen (weaker evidence, speculative):* "
                   + "; ".join(f"{inline(it.get(title_key) or it['claim']) if title_key else inline(it['claim'])} "
                               f"[{it['id']}]" for it in weak))
    return out or ["- None found."]


def to_markdown(pack: dict) -> str:
    b = pack["brief"]
    i = b["interpreted"]
    snap = pack["snapshot"]
    cov = pack["coverage"]
    pb = pack["playbook"]
    g = pack["guardrails"]
    flags_by_item: dict[str, list[dict]] = {}
    for f in pack["compliance_flags"]:
        flags_by_item.setdefault(f["item_id"], []).append(f)
    L: list[str] = []
    add = L.append

    add(f"# Context Pack: {inline(i['topic'])} ({i['market']})")
    add("")
    add(f"*Brief:* {inline(b['text'])}  ")
    add(f"*Audience:* {inline(i['audience'])} | *Languages:* {', '.join(i['languages'])} | *Mode:* {pack['mode']} | "
        f"*Window:* {i['time_window_days']} days{' | *Brand voice:* ' + inline(b['brand_voice']) if b.get('brand_voice') else ''}")
    add(f"*Pack:* {pack['pack_id']} | *Generated:* {pack['generated_at']} | *Coverage grade:* "
        f"{snap['coverage_grade']} | *Relevant posts:* {cov['counts']['relevant']}")
    if cov["thin_evidence"]:
        add("")
        add("> **Thin evidence.** This pack does not meet the minimum content bar; see Blind spots for what is "
            "short. Treat its findings as early signals.")

    add("\n## Summary\n")
    add("### Do first")
    for d in pack["do_first"]:
        add(f"1. **{inline(d['action'])}** - {inline(d['why'])} *[{d['id']}; effort {d['effort']}, impact "
            f"{d['impact']}; {inline(d['owner_hint'])}; based on {', '.join(d['why_ids'])}]*")
    add("\n### Five truths")
    for t in snap["five_truths"]:
        add(f"- {inline(t['text'])} *[{', '.join(t['item_ids'])}]*")
    if snap.get("top_opportunity"):
        add(f"\n**Top opportunity:** {inline(snap['top_opportunity']['text'])} *[{snap['top_opportunity']['item_id']}]*  ")
    if snap.get("top_risk"):
        add(f"**Top risk:** {inline(snap['top_risk']['text'])} *[{snap['top_risk']['item_id']}]*")
    add("\n### A generic AI answer vs. what people actually say")
    add("| Generic answer | What we found |")
    add("|---|---|")
    gp, found = snap["generic_vs_found"]["generic_points"][:6], snap["generic_vs_found"]["what_we_found"]
    for n in range(max(len(gp), len(found))):
        left = cell(gp[n]) if n < len(gp) else ""
        right = f"{cell(found[n]['text'])} [{', '.join(found[n]['item_ids'])}]" if n < len(found) else ""
        add(f"| {left} | {right} |")

    add("\n## Channels and this week\n")
    for c in pack["channel_plan"]:
        add(f"{c['priority']}. **{c['platform']}** - {inline(c['why'])} *[{c['id']}; based on {', '.join(c['why_ids'])}]*  ")
        add(f"   Formats: {inline(', '.join(c['formats']))}. Where: {inline(', '.join(c['communities_or_hashtags'])) or '-'}. "
            f"Tone: {inline(c['tone_note'])}")
    add("\n| Day | Platform | Format | Hook | Angle | Why now |")
    add("|---|---|---|---|---|---|")
    hooks = {h["id"]: h for h in pb["hooks"]}
    for w in pb["this_week"]:
        add(f"| {w['day']} | {w['platform']} | {cell(w['format'])} | {cell(hooks[w['hook_id']]['text'])} "
            f"[{w['hook_id']}] | {cell(w['angle'])} | {cell(w['why_now'])} |")

    add("\n## Voice\n")
    v = pack["voice"]
    add(f"**Tone:** {inline(v['tone'])}  ")
    if v.get("code_switching"):
        add(f"**Code-switching:** {inline(v['code_switching'])}  ")
    if v["category_words_they_use"]:
        add(f"**What they call the category:** {inline(', '.join(v['category_words_they_use']))}")
    add("\n| Their word | Meaning | Language | Confidence | Id |")
    add("|---|---|---|---|---|")
    for x in v["lexicon"]:
        add(f"| **{cell(x['term'])}** | {cell(x['meaning'])} | {x['language']} | {cell(badge(x))} | {x['id']} |")
    if v["phrases"]:
        add("\n**Recurring phrases:** " + "; ".join(f"\"{inline(p['text'])}\" [{p['id']}]" for p in v["phrases"]))
    add("\n**Say this:**")
    L += [f"- {inline(s)}" for s in g["say_this"]] or ["- -"]
    add("\n**Not this:**")
    L += [f"- {inline(s)}" for s in g["not_this"]] or ["- -"]

    add("\n## Tensions and motivations\n")
    for t in pack["tensions"]:
        add(f"- **{inline(t['claim'])}** *[{t['id']}; {badge(t)}]*")
        add(f"  - Want: {inline(t['want']['text'])} ({', '.join(t['want']['evidence_ids'])})")
        add(f"  - But: {inline(t['but']['text'])} ({', '.join(t['but']['evidence_ids'])})")
        L += _quotes(t)
    if not pack["tensions"]:
        add("- None found.")
    add("")
    for kind in ("need", "pain", "job"):
        items = [m for m in pack["motivations"] if m["kind"] == kind]
        if items:
            add(f"**{kind.capitalize()}s**")
            L += _claims(items)

    add("\n## Segments\n")
    L += _claims(pack["segments"], "name")

    add("\n## Objections and competitors\n")
    L += _claims(pack["objections"])
    handling = {h["objection_id"]: h["response"] for h in pb["objection_handling"]}
    if handling:
        add("\n**How to answer them:**")
        L += [f"- {oid}: {inline(r)}" for oid, r in handling.items()]
    if pack["competitors"]:
        add("\n| Brand | Mentions | Share | How they talk about it | Praised | Mocked |")
        add("|---|---|---|---|---|---|")
        for c in pack["competitors"][:8]:
            add(f"| {cell(c['name'])} | {c['mentions']} | {c['share_of_mentions']:.0%} | {cell(c['tone'])} | "
                f"{cell(', '.join(c['praised']))} | {cell(', '.join(c['mocked']))} |")

    add("\n## Landscape and platform lens\n")
    L += _claims(pack["landscape"]["themes"], "label")
    for lens in pack["landscape"]["platform_lens"]:
        add(f"\n**{lens['platform']}** ({lens['kept_posts']} posts) [{lens['id']}]: {inline(lens['tone'])} "
            f"What is unique: {inline(lens['what_is_unique'])}")
    culture = [c for part in pack["culture"].values() for c in part]
    if culture:
        add("\n**Culture and codes**")
        L += _claims(culture, "name")

    add("\n## What performs\n")
    L += [f"- {p['platform']} {inline(p['format'])} (engagement percentile {p['engagement_percentile']:.0f}): "
          f"{inline(p['why_it_worked'])} *(inferred)* [{p['id']}, {p['evidence_id']}]" for p in pack["what_performs"]] \
        or ["- No engagement data in this pack."]

    add("\n## Moments\n")
    L += _claims(pack["moments"], "name")

    add("\n## White space and opportunities\n")
    L += _claims(pack["white_space"])
    add("")
    for o in pack["opportunities"]:
        c = o["components"]
        add(f"- **{inline(o['title'])}** ({o['score']:.2f}) - {inline(o['description'])} *[{o['id']}; demand "
            f"{c['demand']:.2f} x dissatisfaction {c['dissatisfaction']:.2f} x novelty {c['novelty']:.1f} x "
            f"(1 - saturation {c['saturation']:.2f}); builds on {', '.join(o['builds_on'])}]*")

    add("\n## Playbook\n")
    add("### Hooks")
    add(f"*{HOOKS_NOTE}*")
    for h in pb["hooks"]:
        legal = "".join(f" **[check with legal: {f['category']}, {f['id']}]**" for f in flags_by_item.get(h["id"], []))
        add(f"- {inline(h['text'])} *[{h['id']}; {', '.join(h['why_ids'])}]*{legal}")
    cb = pb.get("creative_brief")
    if cb:
        add("\n### Creative brief")
        for key in ("objective", "audience", "insight", "message", "tone"):
            add(f"- **{key.capitalize()}:** {inline(cb[key])}")
        if cb["mandatories"]:
            add(f"- **Mandatories:** {inline('; '.join(cb['mandatories']))}")
        if cb["avoid"]:
            add(f"- **Avoid:** {inline('; '.join(cb['avoid']))}")
    k = pb["keywords"]
    add("\n### Keywords")
    for key in ("seo", "paid", "negatives", "hashtags"):
        add(f"- **{key.upper() if key in ('seo',) else key.capitalize()}:** {inline(', '.join(k[key])) or '-'}")
    if pb["targets"]:
        add("\n### Public communities and creators")
        L += [f"- {inline(t['name'])} ({t['kind']}, {t['platform']}){' ' + t['url'] if t.get('url') else ''}"
              for t in pb["targets"]]
    if pack["compliance_flags"]:
        add("\n### Compliance flags (check with legal - not legal advice)")
        L += [f"- {f['id']} on {f['item_id']} ({f['category']}): {inline(f['why'])} Safer: "
              f"{inline(f['safer_wording'])}" for f in pack["compliance_flags"]]

    add("\n## Blind spots\n")
    L += [f"- {inline(s['text'])}" for s in pack["blind_spots"]]

    add("\n## Guardrails\n")
    add(f"- **Never claim:** {inline('; '.join(g['never_claim'])) or '-'}")
    add(f"- **Sensitivities:** {inline('; '.join(g['sensitivities'])) or '-'}")
    add(f"- **Quotes:** {g['quote_reuse_note']}")

    add("\n## Method\n")
    n = cov["counts"]
    add(f"Collected {n['collected']}, duplicates {n['duplicates']}, spam {n['spam']}, out of window "
        f"{n['out_of_window']}, kept {n['kept']} (undated {n['undated']}), relevant {n['relevant']}. "
        f"Research moves: {cov['loop']['tool_calls']}, finished by {cov['loop']['finish_reason'].replace('_', ' ')}"
        f"{'; remaining planned sources were collected automatically' if cov['loop']['fallback_used'] else ''}"
        f"{'; more evidence was collected from sources already working' if cov['loop']['top_up_used'] else ''}.")
    for spot in pack["blind_spots"]:
        if spot["text"].startswith("Partial pack:"):
            add(f"\n**{inline(spot['text'])}**")
    add("\n**Sources used:**")
    L += [f"- {s['source_unit']} ({s['platform']}): {s['kept']} kept, {s['relevant_share']:.0%} relevant - "
          f"{inline(s['reason'])}" for s in cov["sources_used"][:6]] or ["- -"]
    if cov["sources_dropped"]:
        add("\n**Sources dropped:**")
        L += [f"- {s['source_unit']}: {inline(s['reason'])}" for s in cov["sources_dropped"]]
    add("\n**Privacy:** authors are stored only as salted hashes; personal details are redacted. "
        f"{g['quote_reuse_note']} {privacy_line()}")
    add(f"\n**Confidence labels:** strong, moderate, emerging, speculative. \"Safe to state\" = strong, "
        f"observed and confirmed by the claim check. Evidence ids (EV-...) point to the posts in context_pack.json.")
    add(f"\n*{DISCLAIMER}*")
    return "\n".join(L) + "\n"
