"""Full report (brief.md, "Copy for Notion / Docs"), in pack-page order (PRD S3; exports audit 2026-10-10).

The document a team reads to decide: a one-page summary, then the audience, the plan and the guardrails, then the
method and limits at the end. Written for people: strength in words with counts (never colour-only), dates as
dates, no item or evidence ids in the text (the online pack and context_pack.json keep them), and a "Check with
legal first" note on everything the compliance check flagged. Weaker (speculative) items are one line each; post
briefs are short here - the full drafts are in the content calendar export. Quotes are real people's words and
carry the quote-reuse note.
"""

from __future__ import annotations

from ctxpack.config import load_yaml
from ctxpack.exports.calendar_csv import pack_link
from ctxpack.exports.common import DISCLAIMER, HOOKS_NOTE, cell, inline, privacy_line
from ctxpack.exports.plain import (CHANNEL_NAMES, FORMAT_NAMES, NEVER_LABEL, channel, evidence_line, fmt,  # noqa: F401
                                   guardrails, human_date, legal_note, sentence, strength)
from ctxpack.synthesis.guardrail_check import named_terms
from ctxpack.schemas.plan import confirmed_goal

_INDEX: dict[str, str] = {}   # item id -> short claim, set per export (links show text, not ids)


def _quotes(item: dict, limit: int = 1) -> list[str]:
    return [f"  > {inline(q['text'])}" for q in item.get("quotes", [])[:limit]]


def _meta(pack: dict, name: str) -> list[str]:
    """V4: the section's so-what line, its "also relevant" links, and why it is empty when it is."""
    m = (pack.get("sections_meta") or {}).get(name) or {}
    out = []
    if m.get("so_what"):
        out.append(f"*So what: {inline(m['so_what'])}*")
    if m.get("see_also"):
        out.append("*Also relevant (in another section): " + "; ".join(_INDEX.get(i, i) for i in m["see_also"]) + "*")
    if m.get("empty_reason"):
        out.append(f"- {inline(m['empty_reason'])}" + (" Next: " + "; ".join(m["next_steps"]) + "."
                                                        if m.get("next_steps") else ""))
    return out


def _claims(items: list[dict], title_key: str | None = None) -> list[str]:
    """Items with emerging or better in full (one quote each); speculative ones on one line.
    Every item, quote and number stays in context_pack.json."""
    out = []
    weak = [it for it in items if (it.get("confidence") or {}).get("label") == "speculative"]
    for it in items:
        if it in weak:
            continue
        title = f"**{inline(it[title_key])}** - " if title_key and it.get(title_key) else ""
        out.append(f"- {title}{inline(it['claim'])} *({strength(it)})*")
        out += _quotes(it)
    if weak:
        out.append("- *Also seen (weaker evidence, speculative):* "
                   + "; ".join(inline(it.get(title_key) or it["claim"]) if title_key else inline(it["claim"])
                               for it in weak))
    return out or ["- None found."]


STATUS_WORDS = {"confirmed": "Confirmed by the posts", "contradicted": "Contradicted by the posts",
                "not_seen": "Not seen in the posts"}


def unit_words(unit: str) -> str:
    """"reddit:r/MealPrepSunday" -> "r/MealPrepSunday on Reddit"; "youtube:search:x" -> 'YouTube search: "x"'."""
    platform, _, target = unit.partition(":")
    name = channel(platform) if platform != "web" else "Web"
    if target.startswith("search:"):
        return f'{name} search: "{target[7:]}"'
    if platform == "web":
        return target or unit
    return f"{target} on {name}" if target else name


def to_markdown(pack: dict) -> str:
    """Same parts and order as the pack page (V9): Summary, Understand your audience, Act on it, The research.
    Inside a part, sections follow the pack's section_order (V12: the user's goals decide it)."""
    _INDEX.clear()
    for name in ("pain_points", "tensions", "motivations", "objections", "segments", "moments"):
        _INDEX.update({it["id"]: inline(it["claim"])[:90] for it in pack.get(name, [])})
    _INDEX.update({o["id"]: inline(o["opportunity"])[:90] for o in pack.get("opportunities", [])})
    _INDEX.update({it["id"]: inline(it["claim"])[:90] for it in pack["landscape"]["themes"]})
    b = pack["brief"]
    i = b["interpreted"]
    snap = pack["snapshot"]
    cov = pack["coverage"]
    pb = pack["playbook"]
    g = guardrails(pack)
    chips = load_yaml("goals")["goals"]
    L: list[str] = []
    add = L.append

    topic = inline(i["topic"])
    add(f"# {topic[:1].upper() + topic[1:]} ({i['market']})")
    add("")
    goal = confirmed_goal(b.get("intake"))
    add(f"*Made {human_date(pack['generated_at'])} · {'Standard' if pack['mode'] == 'standard' else 'Quick'} research"
        + (f" · Goals: {inline(goal)}" if goal else "") + f" · Posts from the last {i['time_window_days']} days"
        + (f" ({dq['dated_share']:.0%} of posts dated)" if (dq := cov.get("data_quality") or {}).get("dated_share")
           is not None else "") + "*  ")
    add(f"*Brief:* {inline(b['text'])}  ")
    add(f"*Audience:* {sentence(i['audience'])}  ")
    add(f"*Online version with every post behind every finding:* {pack_link(pack)}")
    add("")
    add(f"> {evidence_line(pack)}")

    # ---- SUMMARY ----------------------------------------------------------------------------
    add("\n## Summary\n")
    for blk in snap.get("for_goals") or []:  # V12: what the pack means for each goal, main goal first
        add(f"### For your goal: {chips[blk['goal']]['chip']}")
        add(f"**{inline(blk['headline'])}**")
        if blk.get("success_measure"):
            add(f"- How you'll know it worked: {inline(blk['success_measure'])}")
        add("")
    add("### What we heard most clearly")
    for f in snap.get("findings") or []:
        add(f"- **{inline(f['text'])}** *({f['strength_text']}; good enough to: {f['good_enough_to']})*")
        if f.get("quote"):
            add(f"  > {inline(f['quote']['text'])}")
            if f.get("quote_en"):
                add(f"  > *In English:* {inline(f['quote_en'])[:280]}")
    if not snap.get("findings"):
        L += [f"- {inline(t['text'])}" for t in snap["five_truths"][:3]]
    if pos := snap.get("position"):
        add("\n### Recommended position")
        add(f"**{sentence(pos['statement'])}**  ")
        add(f"For: {sentence(pos['for_whom'])}  ")
        add(f"The doubt it answers: {sentence(pos['against_doubt'])}")
        if note := legal_note(pack, text=pos["statement"]):
            add(f"\n*{note}*")
    add("\n### Your plan: do this first")
    for n, d in enumerate(pack["do_first"], 1):
        add(f"{n}. **{inline(d['action'])}** {sentence(d['why'])} *(effort: {d['effort']}, impact: {d['impact']}"
            + (f"; for: {chips[d['goal']]['chip']}" if d.get("goal") else "") + ")*")
        if d.get("success_measure"):
            add(f"   - How you'll know it worked: {inline(d['success_measure'])}")
        if note := legal_note(pack, d["id"], d["action"]):
            add(f"   - *{note}*")
    if pack.get("news_hooks"):
        add("\n### Ride this now")
        for h in pack["news_hooks"][:2]:
            add(f"- **{inline(h['headline'])}** ({human_date(h['date'])}) - {inline(h['why_it_matters'])} "
                f"[source]({h['source_url']}) *(outside source)*")
    if snap.get("top_opportunity"):
        add(f"\n**Top opportunity:** {inline(snap['top_opportunity']['text'])}  ")
    if snap.get("top_risk"):
        add(f"**Top risk:** {inline(snap['top_risk']['text'])}")
    add(f"\n*{pack['guardrails']['quote_reuse_note']}*")

    # ---- UNDERSTAND YOUR AUDIENCE -----------------------------------------------------------
    add("\n## Understand your audience\n")
    main, blocks = L, {}

    def section(sid: str):  # V12: each page section collects its own lines; parts emit them in section_order
        blocks[sid] = []
        return blocks[sid], blocks[sid].append

    L, add = section("their-words")
    add("### Their words")
    v = pack["voice"]
    add(f"**Tone:** {inline(v['tone'])}  ")
    if v.get("code_switching"):
        add(f"**Mixing languages:** {inline(v['code_switching'])}  ")
    if v["category_words_they_use"]:
        add(f"**What they call it:** {inline(', '.join(v['category_words_they_use']))}")
    add("\n| Their word | Meaning | Strength |")
    add("|---|---|---|")
    for x in v["lexicon"]:
        add(f"| **{cell(x['term'])}** | {cell(x['meaning'])} | {cell(strength(x))} |")
    if v["phrases"]:
        add("\n**Phrases they repeat:** " + "; ".join(f"\"{inline(p['text'])}\"" for p in v["phrases"]))
    add("\n**Say this:**")
    L += [f"- {inline(s)}" for s in g["say_this"]] or ["- -"]
    add("\n**Not this:**")
    L += [f"- {inline(s)}" for s in g["not_this"]] or ["- -"]

    L, add = section("want-stops")
    add("\n### What they want")
    L += _meta(pack, "motivations")
    for kind in ("need", "pain", "job"):  # pains: pain_points since 1.1 (kept here for older packs)
        items = [m for m in pack["motivations"] if m["kind"] == kind]
        if items:
            add(f"**{kind.capitalize()}s**")
            L += _claims(items)
    if not pack["motivations"]:
        add("- None found.")
    add("\n### What stops them")
    L += _meta(pack, "pain_points")
    if pack.get("pain_points"):
        add("**What gets in their way**")
        L += _claims(pack["pain_points"])
    L += _meta(pack, "objections")
    if pack["objections"]:
        add("\n**Why they would say no**")
        L += _claims(pack["objections"])
    handling = {h["objection_id"]: h["response"] for h in pb["objection_handling"]}
    if handling:
        add("\n**How to answer them:**")
        L += [f"- *{_INDEX.get(oid, 'Objection')}:* {inline(r)}" for oid, r in handling.items()]
    add("\n### Tensions: where wanting meets what stops them")
    L += _meta(pack, "tensions")
    for t in pack["tensions"]:
        add(f"- **{inline(t['claim'])}** *({strength(t)})*")
        add(f"  - Want: {inline(t['want']['text'])}")
        add(f"  - But: {inline(t['but']['text'])}")
    if not pack["tensions"]:
        add("- None found.")

    L, add = section("segments")
    add("\n### Segments")
    L += _meta(pack, "segments")
    if pack["segments"] or not (pack.get("sections_meta") or {}).get("segments", {}).get("empty_reason"):
        L += _claims(pack["segments"], "name")

    L, add = section("generic")
    add("\n### A generic AI answer vs. what people actually say")
    gvf = snap["generic_vs_found"]
    if gvf.get("comparison"):
        add("| A generic answer says | What the posts show |")
        add("|---|---|")
        for row in gvf["comparison"]:
            add(f"| {cell(row['generic_point'])} | {STATUS_WORDS[row['status']]} |")
        if gvf["what_we_found"]:
            add("\n**New - what a generic answer misses:**")
            L += [f"- {inline(f['text'])}" for f in gvf["what_we_found"]]
    else:
        add("| Generic answer | What we found |")
        add("|---|---|")
        gp, found = gvf["generic_points"][:6], gvf["what_we_found"]
        for n in range(max(len(gp), len(found))):
            left = cell(gp[n]) if n < len(gp) else ""
            right = cell(found[n]["text"]) if n < len(found) else ""
            add(f"| {left} | {right} |")

    L, add = section("landscape")
    add("\n### Landscape")
    L += _meta(pack, "themes")
    L += _claims(pack["landscape"]["themes"], "label")
    if pack["landscape"].get("whats_new"):
        add("\n**New in the last 30 days**")
        L += _claims(pack["landscape"]["whats_new"])
    for lens in pack["landscape"]["platform_lens"]:
        add(f"\n**{channel(lens['platform'])}** ({lens['kept_posts']} posts): {inline(lens['tone'])} "
            f"What is unique: {inline(lens['what_is_unique'])}")
    if pack["moments"]:
        add("\n**When it matters**")
        L += _claims(pack["moments"], "name")
    culture = [c for part in pack["culture"].values() for c in part]
    if culture:
        add("\n**Culture and codes**")
        L += _claims(culture, "name")
    if pack["competitors"]:
        add("\n| Brand | Mentions | Share | How they talk about it | Praised | Mocked |")
        add("|---|---|---|---|---|---|")
        for c in pack["competitors"][:8]:
            add(f"| {cell(c['name'])} | {c['mentions']} | {c['share_of_mentions']:.0%} | {cell(c['tone'])} | "
                f"{cell(', '.join(c['praised']))} | {cell(', '.join(c['mocked']))} |")

    if pack.get("brand_perception"):
        L, add = section("brand")
        L += brand_section(pack["brand_perception"])
    order = pack.get("section_order") or list(blocks)
    L, add = main, main.append
    for sid in sorted(blocks, key=lambda x: order.index(x) if x in order else len(order)):
        L += blocks[sid]

    # ---- ACT ON IT --------------------------------------------------------------------------
    add("\n## Act on it\n")
    blocks = {}
    L, add = section("plan")
    if pack.get("post_briefs"):
        L.extend(posts_section(pack, compact=True))
    else:
        add("### Your plan: this week")
        add("| Day | Platform | Format | Hook | Angle | Why now |")
        add("|---|---|---|---|---|---|")
        hooks = {h["id"]: h for h in pb["hooks"]}
        for w in pb["this_week"]:
            add(f"| {w['day']} | {channel(w['platform'])} | {cell(w['format'])} | {cell(hooks[w['hook_id']]['text'])} "
                f"| {cell(w['angle'])} | {cell(w['why_now'])} |")

    L, add = section("channels")
    add("\n### Channels")
    for c in pack["channel_plan"]:
        add(f"{c['priority']}. **{channel(c['platform'])}** - {inline(c['why'])}  ")
        add(f"   Formats: {inline(', '.join(c['formats']))}. Where: {inline(', '.join(c['communities_or_hashtags'])) or '-'}. "
            f"Tone: {inline(c['tone_note'])}" + (f" Posts a week: {c['posts_per_week']}." if c.get("posts_per_week") else ""))
        if c.get("timing"):
            add("   When: " + "; ".join(
                f"{inline(t['label'])} ({inline(t['when'])}, "
                + ("seen in posts)" if t["claim_type"] == "observed" else f"outside source, [link]({t['source_url']}))")
                for t in c["timing"]))

    L, add = section("performs")
    add("\n### What performs")
    L += _meta(pack, "what_performs")
    for t in pack.get("performance_takeaways", []):
        add(f"- **{inline(t['takeaway'])}** {inline(t['why'])} *(our reading)*")
    if pack.get("performance_takeaways"):
        add("\n*Example posts:*")
    L += [f"- {channel(p['platform'])} {inline(p['format'])} (more engagement than {p['engagement_percentile']:.0f}% "
          f"of posts): {inline(p['why_it_worked'])} *(our reading)*" for p in pack["what_performs"][:3]] \
        or ["- No engagement data in this pack."]

    L, add = section("opportunities")
    add("\n### Opportunities")
    L += _meta(pack, "opportunities")
    opps = sorted(pack["opportunities"], key=lambda o: o["status"] != "supported")
    for o in opps[:5]:
        check = "" if o["status"] == "supported" else "; check before acting"
        add(f"- **{inline(o['opportunity'])}** *({o['confidence']['label']}; {o['distinct_authors']} people in "
            f"{len(o['communities'])} communit{'y' if len(o['communities']) == 1 else 'ies'}{check})*")
        if o["existing_solutions"]:
            add("  - Already out there: " + "; ".join(f"[{inline(x['name'])}]({x['url']})" for x in o["existing_solutions"]))
        elif o.get("search_note"):
            add(f"  - {inline(o['search_note']).capitalize()}.")
        if note := legal_note(pack, o["id"]):
            add(f"  - *{note}*")
    if opps[5:]:
        add("- *Also seen (early signals):* " + "; ".join(inline(o["opportunity"])[:90] for o in opps[5:]))
    if not pack["opportunities"] and not (pack.get("sections_meta") or {}).get("opportunities"):
        add("- None found.")

    L, add = section("guardrails")
    add("\n### Guardrails")
    add(f"- **{NEVER_LABEL}:** {inline('; '.join(g['never_claim'])) or '-'}")
    add(f"- **Sensitivities:** {inline('; '.join(g['sensitivities'])) or '-'}")
    add(f"- **Quotes:** {g['quote_reuse_note']}")
    if flags := pack["compliance_flags"]:
        areas: dict[str, int] = {}
        for f in flags:
            areas[f["rule_area"]] = areas.get(f["rule_area"], 0) + 1
        add(f"\n**Check with legal first** *(not legal advice)*: {len(flags)} items in this pack were flagged. "
            "Each one carries its own note above, with safer wording.")
        if terms := named_terms(flags):
            add(f"- Wording flagged most: {', '.join(terms[:8])}")
        L += [f"- {area} ({n})" for area, n in sorted(areas.items(), key=lambda x: -x[1])[:4]]
    add("\n### Hooks, creative brief and keywords")
    add(f"*{HOOKS_NOTE}*")
    for h in pb["hooks"][:8]:
        add(f"- {inline(h['text'])}")
        if note := legal_note(pack, h["id"], h["text"]):
            add(f"  - *{note}*")
    if cb := pb.get("creative_brief"):
        add("\n**Creative brief**")
        for key in ("objective", "audience", "insight", "message", "tone"):
            add(f"- **{key.capitalize()}:** {inline(cb[key])}")
        if cb["mandatories"]:
            add(f"- **Mandatories:** {inline('; '.join(cb['mandatories']))}")
        if cb["avoid"]:
            add(f"- **Avoid:** {inline('; '.join(cb['avoid']))}")
    k = pb["keywords"]
    add("\n**Keywords**")
    for key in ("seo", "paid", "negatives", "hashtags"):
        add(f"- **{'SEO' if key == 'seo' else key.capitalize()}:** {inline(', '.join(k[key])) or '-'}")
    if pb["targets"]:
        add("\n**Public communities and creators**")
        L += [f"- {inline(t['name'])} ({t['kind']}, {channel(t['platform'])}){' ' + t['url'] if t.get('url') else ''}"
              for t in pb["targets"]]

    L, add = main, main.append
    for sid in sorted(blocks, key=lambda x: order.index(x) if x in order else len(order)):
        L += blocks[sid]

    # ---- THE RESEARCH (method and limits) ---------------------------------------------------
    add("\n## The research: method and limits\n")
    add("### Blind spots")
    L += [f"- {inline(s['text'])}" for s in pack["blind_spots"]]
    add("\n### How the posts were collected")
    n = cov["counts"]
    add(f"{n['collected']} posts collected; {n['duplicates']} duplicates, {n['spam']} spam and {n['out_of_window']} "
        f"outside the time window removed; {n['kept']} kept ({n['undated']} without a date); {n['relevant']} on topic. "
        f"The research agent made {cov['loop']['tool_calls']} moves and finished because "
        f"{cov['loop']['finish_reason'].replace('_', ' ')}"
        f"{'; the remaining planned sources were collected automatically' if cov['loop']['fallback_used'] else ''}"
        f"{'; more posts were collected from sources that were already working' if cov['loop']['top_up_used'] else ''}.")
    if pack.get("hypotheses"):
        add("\n**What the plan expected, and what the posts showed**\n")
        add("| Expected | Result | Why |")
        add("|---|---|---|")
        for h in pack["hypotheses"]:
            add(f"| {cell(h['statement'])} | {h['status']} | {cell(h['why'])} |")
    add("\n**Sources used:**")
    L += [f"- {unit_words(s['source_unit'])}: {s['kept']} kept, {s['relevant_share']:.0%} on topic - "
          f"{inline(s['reason'])}" for s in cov["sources_used"][:6]] or ["- -"]
    if cov["sources_dropped"]:
        add("\n**Sources dropped:**")
        L += [f"- {unit_words(s['source_unit'])}: {inline(s['reason'])}" for s in cov["sources_dropped"]]
    add("\n**Privacy:** authors are stored only as salted hashes; personal details are removed. "
        f"{g['quote_reuse_note']} {privacy_line()}")
    add("\n**How to read the strength labels:** " + " ".join(
        f"{w['words']}." for w in load_yaml("scoring")["plain_labels"].values())
        + f" Every finding links to its posts in the online pack: {pack_link(pack)}")
    if prov := pack.get("provenance"):  # data audit 8
        add("\n**Made with:** " + ", ".join(f"{role} {model}" for role, model in prov["models"].items())
            + f"; code {prov['code_version']}. Pack {pack['pack_id']}.")
    add(f"\n*{DISCLAIMER}*")
    return "\n".join(L) + "\n"


def brand_section(bp: dict) -> list[str]:
    """V12: how people see the user's brand - numbers from code, then the verified findings."""
    out = ["\n### How people see your brand", f"*{inline(bp['note'])}*" if bp.get("note") else ""]
    if bp["brands"]:
        out += ["", "| Brand | Posts | Unasked | Share of voice (unasked) | Feeling | Praised | Criticised |",
                "|---|---|---|---|---|---|---|"]
        for r in bp["brands"]:
            mix = ", ".join(f"{x['stance']} {x['share']:.0%}" for x in r["stance_mix"]) or "-"
            sov = f"{r['share_of_voice']:.0%}" if r.get("share_of_voice") is not None else "-"
            out.append(f"| {cell(r['name'])}{' (parent)' if r['is_parent'] else ''} | {r['mentions']} | "
                       f"{r['unprompted']} | {sov} | {cell(mix)} | {cell(', '.join(r['aspects_praised'])) or '-'} | "
                       f"{cell(', '.join(r['aspects_criticised'])) or '-'} |")
        own = bp["brands"][0]
        if own.get("relation_mix"):
            out.append("\n**Next to the parent brand** (" + f"{own['with_parent']} posts name both): " + ", ".join(
                f"{x['relation'].replace('_', ' ')} {x['share']:.0%}" for x in own["relation_mix"]))
    if bp["findings"]:
        out.append("")
        out += _claims(bp["findings"])
    return out


def posts_section(pack: dict, compact: bool = False) -> list[str]:
    """V8: the calendar as a table, then each brief. compact (the report): no ids, no drafts (they are in the
    content calendar export). Full (the skill's posts.md): ids, receipts and drafts for an AI tool."""
    briefs = {b["id"]: b for b in pack["post_briefs"]}
    drafts = {d["post_brief_id"]: d for d in pack.get("drafts", [])}
    words = {x["id"]: x["term"] for x in pack["voice"]["lexicon"]}
    out = ["\n### Your plan: post briefs and content calendar\n", HOOKS_NOTE, ""]
    if pack.get("content_calendar"):
        out += ["| Week | Day | Channel | Post | Status |", "|---|---|---|---|---|"]
        for e in pack["content_calendar"]:
            b = briefs[e["post_brief_id"]]
            ref = "" if compact else f" [{b['id']}]"
            out.append(f"| {e['week']} | {e['suggested_day'].capitalize()} | {channel(e['channel'])} "
                       f"| {cell(b['angle'] or b['hook'])}{ref} | idea |")
        out.append("")
    for n, b in enumerate(pack["post_briefs"], 1):
        head = f"Post {n}" if compact else b["id"]
        out.append(f"#### {head}: {inline(b['angle'] or b['hook'])}")
        out.append(f"*{channel(b['channel'])}, {fmt(b['format'])}; for {inline(b['role'])}; strength {b['confidence']}*  ")
        out.append(f"**Hook:** {inline(b['hook'])}  ")
        if (nws := b.get("news_hook_id")) and (hook := next((h for h in pack.get("news_hooks", []) if h["id"] == nws), None)):
            out.append(f"**Rides the news:** {inline(hook['headline'])}" + ("" if compact else f" [{nws}]") + "  ")
        if not compact:
            out.append(f"**Goal:** {inline(b['goal'])}  ")
            out.append(f"**Structure:** {inline(b['structure'].replace('->', '→'))}  ")
        if not compact:   # the report keeps hook, call to action and how you'll know; the rest is in the calendar
            out += [f"- {inline(k['text'])} *[{', '.join(k['item_ids'])}; posts {', '.join(k['evidence_ids'])}]*"
                    for k in b["key_points"]]
            if b["their_words_to_use"]:
                out.append(f"**Their words:** {', '.join(inline(words.get(w, w)) for w in b['their_words_to_use'])}  ")
        out.append(f"**Call to action:** {inline(b['cta'])}  ")
        if b["avoid"] and not compact:
            out.append(f"**Avoid:** {inline('; '.join(b['avoid']))}  ")
        if b.get("success_measure"):
            out.append(f"**How you'll know it worked:** {inline(b['success_measure'])}  ")
        if note := legal_note(pack, b["id"], b["hook"]):
            out.append(f"*{note}*  ")
        d = drafts.get(b["id"])
        if d and not compact:
            out += ["", f"**{d['label']}** ({d['voice']} voice"
                    + (f"; {d['removed_sentences']} unsupported sentence(s) removed" if d["removed_sentences"] else "")
                    + ")", ""]
            if d.get("title"):
                out.append(f"> **{inline(d['title'])}**  ")
            out += [f"> {line}" if line.strip() else ">" for line in d["body"].splitlines()]
        out.append("")
    if compact:
        out.append("*Key points, their words, what to avoid and full drafts for each post are in the Content "
                   "calendar export and the Brief for your AI writer.*")
    return out
