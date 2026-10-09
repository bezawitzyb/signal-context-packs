"""brief.md export ("Copy for Notion / Docs"), in pack-page order (PRD S3).

Confidence is always written in words with counts (never colour-only). Quotes
are real people's words: shown as quotes with their evidence id, and the
quote-reuse note is repeated next to them.
"""

from __future__ import annotations

from ctxpack.exports.common import DISCLAIMER, HOOKS_NOTE, badge, cell, inline, privacy_line
from ctxpack.config import load_yaml
from ctxpack.schemas.plan import confirmed_goal
from ctxpack.exports.calendar_csv import CHANNEL_NAMES, FORMAT_NAMES



def _quotes(item: dict, limit: int = 1) -> list[str]:
    return [f"  > {inline(q['text'])} ({q['evidence_id']})" for q in item.get("quotes", [])[:limit]]


_LINK = {"comes_from": "comes from", "blocks": "blocks", "related": "related"}
_INDEX: dict[str, str] = {}   # item id -> short claim, set per export (links show text, not bare ids)


def _links(it: dict) -> list[str]:
    """V4: connected items in other sections as one short line - never a restated paragraph."""
    rel = [r for r in it.get("relations", []) if r["id"] in _INDEX]
    if not rel:
        return []
    return ["  - *" + "; ".join(f"{_LINK.get(r['kind'], 'related')}: {_INDEX[r['id']]} [{r['id']}]" for r in rel)
            + "*"]


def _meta(pack: dict, name: str) -> list[str]:
    """V4: the section's so-what line, its "also relevant" links, and why it is empty when it is."""
    m = (pack.get("sections_meta") or {}).get(name) or {}
    out = []
    if m.get("so_what"):
        out.append(f"*So what: {inline(m['so_what'])}*")
    if m.get("see_also"):
        out.append("*Also relevant (in another section): " + "; ".join(
            f"{_INDEX.get(i, i)} [{i}]" for i in m["see_also"]) + "*")
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
        out.append(f"- {title}{inline(it['claim'])} *[{it['id']}; {badge(it)}]*")
        out += _quotes(it)
        out += _links(it)
    if weak:
        out.append("- *Also seen (weaker evidence, speculative):* "
                   + "; ".join(f"{inline(it.get(title_key) or it['claim']) if title_key else inline(it['claim'])} "
                               f"[{it['id']}]" for it in weak))
    return out or ["- None found."]


STATUS_WORDS = {"confirmed": "Confirmed by the posts", "contradicted": "Contradicted by the posts",
                "not_seen": "Not seen in the posts"}


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
    g = pack["guardrails"]
    flags_by_item: dict[str, list[dict]] = {}
    for f in pack["compliance_flags"]:
        flags_by_item.setdefault(f["item_id"], []).append(f)
    L: list[str] = []
    add = L.append

    add(f"# Context Pack: {inline(i['topic'])} ({i['market']})")
    add("")
    add(f"*Brief:* {inline(b['text'])}  ")
    goal = confirmed_goal(b.get("intake"))
    add(f"*Audience:* {inline(i['audience'])}{' | *Goals:* ' + inline(goal) if goal else ''} | *Languages:* "
        f"{', '.join(i['languages'])} | *Mode:* {pack['mode']} | *Window:* {i['time_window_days']} days"
        f"{' | *Brand voice:* ' + inline(b['brand_voice']) if b.get('brand_voice') else ''}")
    add(f"*Pack:* {pack['pack_id']} | *Generated:* {pack['generated_at']} | *Coverage grade:* "
        f"{snap['coverage_grade']}{' (' + inline(snap['grade_note']) + ')' if snap.get('grade_note') else ''} | "
        f"*Relevant posts:* {cov['counts']['relevant']}")
    if cov["thin_evidence"]:
        add("")
        add("> **Thin evidence.** This pack does not meet the minimum content bar; see Blind spots for what is "
            "short. Treat its findings as early signals.")

    # ---- SUMMARY ----------------------------------------------------------------------------
    add("\n## Summary\n")
    if snap.get("represents"):
        add(f"*Who this represents:* {inline(snap['represents'])}")
    chips = load_yaml("goals")["goals"]
    for blk in snap.get("for_goals") or []:  # V12: what the pack means for each goal, main goal first
        add(f"\n### For your goal: {chips[blk['goal']]['chip']}")
        add(f"**{inline(blk['headline'])}**" + (f" *[{', '.join(blk['item_ids'])}]*" if blk["item_ids"] else ""))
        if blk["first_moves"]:
            add(f"- First moves: {', '.join(blk['first_moves'])} (below)")
        if blk.get("success_measure"):
            add(f"- How you'll know it worked: {inline(blk['success_measure'])}")
    add("\n### What we heard most clearly")
    for f in snap.get("findings") or []:
        add(f"- **{inline(f['text'])}** *[{', '.join(f['item_ids'])}; {f['strength_text']}; good enough to: "
            f"{f['good_enough_to']}]*")
        if f.get("quote"):
            add(f"  > {inline(f['quote']['text'])} ({f['quote']['evidence_id']})")
            if f.get("quote_en"):
                add(f"  > *In English (the post):* {inline(f['quote_en'])[:280]}")
    if not snap.get("findings"):
        L += [f"- {inline(t['text'])} *[{', '.join(t['item_ids'])}]*" for t in snap["five_truths"][:3]]
    pos = snap.get("position")
    if pos:
        add("\n### Recommended position")
        add(f"**{inline(pos['statement'])}** - for {inline(pos['for_whom'])}, answering: "
            f"{inline(pos['against_doubt'])} *[{', '.join(pos['item_ids'])}]*")
    add("\n### Your plan: do this first")
    for d in pack["do_first"]:
        add(f"1. **{inline(d['action'])}** - {inline(d['why'])} *[{d['id']}; effort {d['effort']}, impact "
            f"{d['impact']}; {inline(d['owner_hint'])}; based on {', '.join(d['why_ids'])}"
            + (f"; for: {chips[d['goal']]['chip']}" if d.get("goal") else "") + "]*")
        if d.get("success_measure"):
            add(f"   - How you'll know it worked: {inline(d['success_measure'])}")
    if pack.get("news_hooks"):
        add("\n### Ride this now")
        for h in pack["news_hooks"][:2]:
            add(f"- **{inline(h['headline'])}** ({h['date']}, {h['kind']}) - {inline(h['why_it_matters'])} "
                f"[source]({h['source_url']}) *[{h['id']}; external]*")
    if snap.get("top_opportunity"):
        add(f"\n**Top opportunity:** {inline(snap['top_opportunity']['text'])} *[{snap['top_opportunity']['item_id']}]*  ")
    if snap.get("top_risk"):
        add(f"**Top risk:** {inline(snap['top_risk']['text'])} *[{snap['top_risk']['item_id']}]*")

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
        L += [f"- {oid}: {inline(r)}" for oid, r in handling.items()]

    add("\n### Tensions: where wanting meets what stops them")
    L += _meta(pack, "tensions")
    for t in pack["tensions"]:
        add(f"- **{inline(t['claim'])}** *[{t['id']}; {badge(t)}]*")
        add(f"  - Want: {inline(t['want']['text'])} ({', '.join(t['want']['evidence_ids'])})")
        add(f"  - But: {inline(t['but']['text'])} ({', '.join(t['but']['evidence_ids'])})")
        L += _quotes(t)
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
            ids = f" [{', '.join(row['item_ids'])}]" if row["item_ids"] else ""
            add(f"| {cell(row['generic_point'])} | {STATUS_WORDS[row['status']]}{ids} |")
        if gvf["what_we_found"]:
            add("\n**New - what a generic answer misses:**")
            L += [f"- {inline(f['text'])} [{', '.join(f['item_ids'])}]" for f in gvf["what_we_found"]]
    else:
        add("| Generic answer | What we found |")
        add("|---|---|")
        gp, found = gvf["generic_points"][:6], gvf["what_we_found"]
        for n in range(max(len(gp), len(found))):
            left = cell(gp[n]) if n < len(gp) else ""
            right = f"{cell(found[n]['text'])} [{', '.join(found[n]['item_ids'])}]" if n < len(found) else ""
            add(f"| {left} | {right} |")

    L, add = section("landscape")
    add("\n### Landscape")
    L += _meta(pack, "themes")
    L += _claims(pack["landscape"]["themes"], "label")
    if pack["landscape"].get("whats_new"):
        add("\n**New in the last 30 days**")
        L += _claims(pack["landscape"]["whats_new"])
    for lens in pack["landscape"]["platform_lens"]:
        add(f"\n**{lens['platform']}** ({lens['kept_posts']} posts) [{lens['id']}]: {inline(lens['tone'])} "
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
        L.extend(posts_section(pack))
    else:
        add("### Your plan: this week")
        add("| Day | Platform | Format | Hook | Angle | Why now |")
        add("|---|---|---|---|---|---|")
        hooks = {h["id"]: h for h in pb["hooks"]}
        for w in pb["this_week"]:
            add(f"| {w['day']} | {w['platform']} | {cell(w['format'])} | {cell(hooks[w['hook_id']]['text'])} "
                f"[{w['hook_id']}] | {cell(w['angle'])} | {cell(w['why_now'])}"
                + (f" (rides {w['news_hook_id']})" if w.get("news_hook_id") else "") + " |")

    L, add = section("channels")
    add("\n### Channels")
    for c in pack["channel_plan"]:
        add(f"{c['priority']}. **{c['platform']}** - {inline(c['why'])} *[{c['id']}; based on {', '.join(c['why_ids'])}]*  ")
        add(f"   Formats: {inline(', '.join(c['formats']))}. Where: {inline(', '.join(c['communities_or_hashtags'])) or '-'}. "
            f"Tone: {inline(c['tone_note'])}" + (f" Posts a week: {c['posts_per_week']}." if c.get("posts_per_week") else ""))
        if c.get("timing"):
            add("   When: " + "; ".join(
                f"{inline(t['label'])} ({inline(t['when'])}, "
                + (f"seen in posts {', '.join(t['evidence_ids'])})" if t["claim_type"] == "observed"
                   else f"external, [source]({t['source_url']}))") for t in c["timing"]))

    L, add = section("performs")
    add("\n### What performs")
    L += _meta(pack, "what_performs")
    for t in pack.get("performance_takeaways", []):
        add(f"- **{inline(t['takeaway'])}** {inline(t['why'])} *(inferred)* [{t['id']}"
            + (f"; {', '.join(t['post_ids'])}" if t["post_ids"] else "") + "]")
    if pack.get("performance_takeaways"):
        add("\n*Example posts:*")
    L += [f"- {p['platform']} {inline(p['format'])} (engagement percentile {p['engagement_percentile']:.0f}): "
          f"{inline(p['why_it_worked'])} *(inferred)* [{p['id']}, {p['evidence_id']}]" for p in pack["what_performs"]] \
        or ["- No engagement data in this pack."]

    L, add = section("opportunities")
    add("\n### Opportunities")
    L += _meta(pack, "opportunities")
    for o in pack["opportunities"]:
        status = "Supported" if o["status"] == "supported" else "Early signal - check before acting"
        add(f"- **{inline(o['opportunity'])}** *[{o['id']}; {o['kind'].replace('_', ' ')}; {status}; "
            f"{o['confidence']['label']}; {o['distinct_authors']} people in {len(o['communities'])} "
            f"communit{'y' if len(o['communities']) == 1 else 'ies'}]*")
        if o["existing_solutions"]:
            add("  - Already out there: " + "; ".join(f"[{inline(x['name'])}]({x['url']})" for x in o["existing_solutions"]))
        elif o.get("search_note"):
            add(f"  - {inline(o['search_note']).capitalize()}.")
    if not pack["opportunities"] and not (pack.get("sections_meta") or {}).get("opportunities"):
        add("- None found.")

    L, add = section("guardrails")
    add("\n### Guardrails")
    add(f"- **Never claim:** {inline('; '.join(g['never_claim'])) or '-'}")
    add(f"- **Sensitivities:** {inline('; '.join(g['sensitivities'])) or '-'}")
    add(f"- **Quotes:** {g['quote_reuse_note']}")
    if pack["compliance_flags"]:
        add("\n**Compliance flags (check with legal - not legal advice)**")
        L += [f"- {f['id']} on {f['item_id']} ({f['category']}): {inline(f['why'])} Safer: "
              f"{inline(f['safer_wording'])}" for f in pack["compliance_flags"]]

    add("\n### Hooks, creative brief and keywords")
    add(f"*{HOOKS_NOTE}*")
    for h in pb["hooks"]:
        legal = "".join(f" **[check with legal: {f['category']}, {f['id']}]**" for f in flags_by_item.get(h["id"], []))
        add(f"- {inline(h['text'])} *[{h['id']}; {', '.join(h['why_ids'])}]*{legal}")
    cb = pb.get("creative_brief")
    if cb:
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
        add(f"- **{key.upper() if key in ('seo',) else key.capitalize()}:** {inline(', '.join(k[key])) or '-'}")
    if pb["targets"]:
        add("\n**Public communities and creators**")
        L += [f"- {inline(t['name'])} ({t['kind']}, {t['platform']}){' ' + t['url'] if t.get('url') else ''}"
              for t in pb["targets"]]

    L, add = main, main.append
    for sid in sorted(blocks, key=lambda x: order.index(x) if x in order else len(order)):
        L += blocks[sid]

    # ---- THE RESEARCH -----------------------------------------------------------------------
    add("\n## The research\n")
    add("### Blind spots")
    L += [f"- {inline(s['text'])}" for s in pack["blind_spots"]]
    add("\n### Method")
    n = cov["counts"]
    add(f"Collected {n['collected']}, duplicates {n['duplicates']}, spam {n['spam']}, out of window "
        f"{n['out_of_window']}, kept {n['kept']} (undated {n['undated']}), relevant {n['relevant']}. "
        f"Research moves: {cov['loop']['tool_calls']}, finished by {cov['loop']['finish_reason'].replace('_', ' ')}"
        f"{'; remaining planned sources were collected automatically' if cov['loop']['fallback_used'] else ''}"
        f"{'; more evidence was collected from sources already working' if cov['loop']['top_up_used'] else ''}.")
    for spot in pack["blind_spots"]:
        if spot["text"].startswith("Partial pack:"):
            add(f"\n**{inline(spot['text'])}**")
    if pack.get("hypotheses"):
        add("\n**Hypotheses from the plan**\n")
        add("| Hypothesis | Result | Why |")
        add("|---|---|---|")
        for h in pack["hypotheses"]:
            add(f"| {cell(h['statement'])} [{h['id']}] | {h['status']} | {cell(h['why'])} |")
    add("\n**Sources used:**")
    L += [f"- {s['source_unit']} ({s['platform']}): {s['kept']} kept, {s['relevant_share']:.0%} relevant - "
          f"{inline(s['reason'])}" for s in cov["sources_used"][:6]] or ["- -"]
    if cov["sources_dropped"]:
        add("\n**Sources dropped:**")
        L += [f"- {s['source_unit']}: {inline(s['reason'])}" for s in cov["sources_dropped"]]
    add("\n**Privacy:** authors are stored only as salted hashes; personal details are redacted. "
        f"{g['quote_reuse_note']} {privacy_line()}")
    add("\n**How to read the strength labels:** " + " ".join(
        f"{w['words']}." for w in load_yaml("scoring")["plain_labels"].values())
        + " Evidence ids (EV-...) point to the posts in context_pack.json.")
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


def posts_section(pack: dict) -> list[str]:
    """V8: the calendar as a table (pastes into Notion as a database), then each brief and its draft."""
    briefs = {b["id"]: b for b in pack["post_briefs"]}
    drafts = {d["post_brief_id"]: d for d in pack.get("drafts", [])}
    words = {x["id"]: x["term"] for x in pack["voice"]["lexicon"]}
    out = ["\n### Your plan: post briefs and content calendar\n", HOOKS_NOTE, ""]
    if pack.get("content_calendar"):
        out += ["| Week | Day | Channel | Post | Why then | Status |", "|---|---|---|---|---|---|"]
        for e in pack["content_calendar"]:
            b = briefs[e["post_brief_id"]]
            out.append(f"| {e['week']} | {e['suggested_day'].capitalize()} | {CHANNEL_NAMES.get(e['channel'], e['channel'])} "
                       f"| {cell(b['angle'] or b['hook'])} [{b['id']}] | {cell(e['timing_reason'])} | idea |")
        out.append("")
    for b in pack["post_briefs"]:
        out.append(f"#### {b['id']}: {inline(b['angle'] or b['hook'])}")
        out.append(f"*{CHANNEL_NAMES.get(b['channel'], b['channel'])}, {FORMAT_NAMES.get(b['format'], b['format'])}; "
                   f"for {inline(b['role'])}; confidence {b['confidence']}"
                   + (f"; rides {b['news_hook_id']}" if b.get("news_hook_id") else "") + "*  ")
        out.append(f"**Goal:** {inline(b['goal'])}  ")
        out.append(f"**Hook:** {inline(b['hook'])}" + (f" [{b['hook_id']}]" if b.get("hook_id") else "") + "  ")
        out.append(f"**Structure:** {inline(b['structure'].replace('->', '→'))}  ")
        out += [f"- {inline(k['text'])} *[{', '.join(k['item_ids'])}; posts {', '.join(k['evidence_ids'])}]*"
                for k in b["key_points"]]
        if b["their_words_to_use"]:
            out.append(f"**Their words:** {', '.join(inline(words.get(w, w)) for w in b['their_words_to_use'])}  ")
        out.append(f"**Call to action:** {inline(b['cta'])}  ")
        if b["avoid"]:
            out.append(f"**Avoid:** {inline('; '.join(b['avoid']))}  ")
        d = drafts.get(b["id"])
        if d:
            out += ["", f"**{d['label']}** ({d['voice']} voice"
                    + (f"; {d['removed_sentences']} unsupported sentence(s) removed" if d["removed_sentences"] else "")
                    + ")", ""]
            if d.get("title"):
                out.append(f"> **{inline(d['title'])}**  ")
            out += [f"> {line}" if line.strip() else ">" for line in d["body"].splitlines()]
        out.append("")
    return out
