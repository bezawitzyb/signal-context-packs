"""Command line: uv run python -m ctxpack.cli <command>.

doctor  checks secrets (set / not set ONLY), Anthropic, Apify, the
        database and the data folder. It never prints a secret value,
        length or prefix.
"""

import typer
from rich.console import Console

from ctxpack.config import SECRET_NAMES, get_settings, model_for, sqlalchemy_url

app = typer.Typer(no_args_is_help=True, add_completion=False)
console = Console()

OK = "[green]✔[/green]"
BAD = "[red]✘[/red]"


def _fail_reason(exc: Exception) -> str:
    """Error type plus HTTP status if any - never the message text, which could echo config."""
    status = getattr(exc, "status_code", None)
    return f"{type(exc).__name__}" + (f" (HTTP {status})" if status else "")


def _check_anthropic(settings) -> tuple[bool, str]:
    import anthropic

    client = anthropic.Anthropic(api_key=settings.anthropic_api_key.get_secret_value())
    model = model_for("worker")
    resp = client.messages.create(
        model=model,
        max_tokens=5,
        messages=[{"role": "user", "content": "Reply with the word OK."}],
    )
    return True, f"{model} answered ({resp.usage.input_tokens + resp.usage.output_tokens} tokens, < $0.001)"


def _check_apify(settings) -> tuple[bool, str]:
    from apify_client import ApifyClient

    user = ApifyClient(settings.apify_api_token.get_secret_value()).user().get()
    return (user is not None), "account reachable" if user else "no user info returned"


def _check_database(settings) -> tuple[bool, str]:
    from sqlalchemy import create_engine, text

    engine = create_engine(sqlalchemy_url(settings.database_url.get_secret_value()))
    try:
        with engine.connect() as conn:
            value = conn.execute(text("SELECT 1")).scalar_one()
    finally:
        engine.dispose()
    return value == 1, "SELECT 1 ok"


@app.command()
def doctor() -> None:
    """Check secrets (set / not set), Anthropic, Apify, database and data folder."""
    settings = get_settings()
    all_ok = True

    console.print("[bold]Secrets[/bold] (set / not set only)")
    for name in SECRET_NAMES:
        is_set = settings.is_set(name)
        all_ok &= is_set
        console.print(f"  {OK if is_set else BAD} {name}: {'set' if is_set else 'not set'}")
    guest = settings.is_set("GUEST_RUN_KEY")  # optional: temporary tester access
    console.print(f"  {OK} GUEST_RUN_KEY: {'set (guest access ON - delete it to revoke)' if guest else 'not set (no guest access)'}")

    console.print("[bold]Services[/bold]")
    checks = [
        ("Anthropic", "ANTHROPIC_API_KEY", _check_anthropic),
        ("Apify", "APIFY_API_TOKEN", _check_apify),
        ("Database", "DATABASE_URL", _check_database),
    ]
    for label, secret, check in checks:
        if not settings.is_set(secret):
            console.print(f"  {BAD} {label}: skipped ({secret} not set)")
            all_ok = False
            continue
        try:
            ok, detail = check(settings)
        except Exception as exc:  # report the type only, never the text
            ok, detail = False, f"failed: {_fail_reason(exc)}"
        all_ok &= ok
        console.print(f"  {OK if ok else BAD} {label}: {detail}")

    data = settings.data_path
    data.mkdir(parents=True, exist_ok=True)
    console.print(f"  {OK} Data folder: {data}")

    if all_ok:
        console.print("[bold green]All checks passed.[/bold green]")
    else:
        console.print("[bold red]Some checks failed - see the ✘ lines above.[/bold red]")
        raise typer.Exit(code=1)


@app.command("export-schema")
def export_schema() -> None:
    """Write docs/schema/context-pack.schema.json and docs/SCHEMA.md from the Pydantic models."""
    from ctxpack.config import REPO_DIR
    from ctxpack.schemas.schema_doc import write_all

    for path in write_all(REPO_DIR / "docs"):
        console.print(f"{OK} wrote {path.relative_to(REPO_DIR)}")


@app.command()
def catalog() -> None:
    """Print the source catalogue: actors, fallbacks, limits and unit types."""
    from ctxpack.config import load_yaml

    cat = load_yaml("catalog")

    def actor(a: dict | None) -> str:
        return f"{a['id']} ({a['success_30d']:.0%} ok)" if a else "none verified"

    console.print(f"[bold]Sources[/bold] (actors verified {cat['verified_on']})")
    for name, src in cat["sources"].items():
        console.print(f"\n[bold]{name}[/bold]  units: {', '.join(src['unit_types'])}")
        if src["kind"] == "web":
            rows = [("tool", src["tool"]), ("limits", "modes.yaml web_pages_per_call_max")]
        else:
            comments, groups = src.get("comments"), src.get("groups")
            rows = [
                ("actor", actor(src["actor"])),
                ("fallback", actor(src.get("fallback"))),
                ("comments", f"{actor(comments['actor'])}, fallback {actor(comments.get('fallback'))}" if comments else "-"),
                ("limits", ", ".join(src["actor"]["limit_inputs"])),
            ] + ([("groups", f"{actor(groups['actor'])}, fallback {actor(groups.get('fallback'))}")] if groups else [])
        for label, value in rows:
            console.print(f"  {label:<9}{value}", soft_wrap=False, highlight=False)


@app.command()
def tool(
    name: str = typer.Argument(..., help="search_reddit, search_tiktok, search_youtube, search_instagram, search_linkedin, search_x, "
                                         "search_facebook, "
                                         "web_search, fetch_and_segment or get_trends"),
    targets: list[str] = typer.Argument(..., help="Target(s): r/name, #tag, query, URL(s) or trend terms"),
    topic: str = typer.Option("", help="Brief topic for the relevance check (default: the target)"),
    market: str = typer.Option("global", help="ISO country code, e.g. NL"),
    language: str = typer.Option("en", help="ISO 639-1, e.g. nl"),
    limit: int = typer.Option(20, help="Items wanted"),
    mode: str = typer.Option("quick"),
    window: int = typer.Option(180, help="Time window in days"),
    fixtures: bool = typer.Option(False, "--fixtures", help="Replay fixtures: no network, no cost"),
    record: bool = typer.Option(False, "--record", help="Save a sanitised fixture (names -> user_N)"),
) -> None:
    """Run ONE tool and print the summary the agent would see (results kept in memory only)."""
    import asyncio
    import json
    import os

    from ctxpack.collect import tools as t
    from ctxpack.collect.relevance import BriefContext

    if fixtures:
        os.environ["USE_FIXTURES"] = "true"
        os.environ["LLM_FAKE"] = "true"
        get_settings.cache_clear()
    if not fixtures and not get_settings().is_set("AUTHOR_HASH_SALT"):
        console.print(f"{BAD} AUTHOR_HASH_SALT not set - run the doctor command")
        raise typer.Exit(1)
    stored: list = []
    ctx = t.RunContext(run_id="cli", mode=mode, window_days=window, record=record,
                       brief=BriefContext(topic=topic or " ".join(targets), market=market, languages=[language],
                                          countries=[market.upper()] if len(market) == 2 else []),
                       store=lambda docs, replaced: stored.extend(docs))
    args: dict = {"reason": "manual CLI test"}
    if name in ("search_reddit", "search_tiktok", "search_x"):
        args |= {"target": targets[0], "limit": limit}
    elif name in ("search_youtube", "search_linkedin", "search_facebook"):
        args |= {"query": targets[0], "limit": limit}
    elif name == "search_instagram":
        args |= {"hashtag": targets[0], "limit": limit}
    elif name == "web_search":
        args |= {"query": " ".join(targets), "country": market, "language": language}
    elif name == "fetch_and_segment":
        args |= {"urls": targets}
    elif name == "get_trends":
        args |= {"terms": targets, "geo": "" if market == "global" else market}
    else:
        console.print(f"{BAD} unknown tool {name}")
        raise typer.Exit(1)

    started = __import__("time").monotonic()
    summary = asyncio.run(t.call_tool(ctx, name, args))
    seconds = __import__("time").monotonic() - started
    if record and name == "web_search" and summary.get("status") == "ok":
        from ctxpack.collect import web
        data = json.loads(web.DISCOVER_FIXTURE.read_text(encoding="utf-8")) if web.DISCOVER_FIXTURE.exists() else {}
        data[web.discover_key(args["query"], market, language)] = {"pages": [
            {k: p[k] for k in ("url", "page_type", "language", "why")} for p in summary["pages"]]}
        web.DISCOVER_FIXTURE.write_text(json.dumps(data, ensure_ascii=False, indent=1), encoding="utf-8")
    console.print_json(json.dumps(summary, ensure_ascii=False, default=str))
    console.print(f"took {seconds:.0f} s | cost: Apify ${ctx.apify_usd:.4f}, Anthropic ${ctx.llm_usd:.4f}"
                  f" | documents kept in memory: {len(stored)}")


@app.command()
def classify(
    topic: str = typer.Argument(..., help="Brief topic, e.g. \"meal prep\""),
    sentences: list[str] = typer.Argument(..., help="Sentences to screen (one worker call)"),
    language: str = typer.Option("en", help="ISO 639-1, e.g. nl"),
) -> None:
    """One real worker call: relevance verdicts for a few sentences, with tokens and cost.

    The cost is added to today's spend table (daily cap checked first).
    """
    import asyncio
    import json

    from ctxpack.collect.relevance import BriefContext, classify as screen
    from ctxpack.llm.client import tracking

    texts = {f"s{i}": s for i, s in enumerate(sentences, 1)}
    with tracking() as t:
        outcome = asyncio.run(screen(texts, BriefContext(topic=topic, languages=[language])))
    for sid, text in texts.items():
        v = outcome.verdicts.get(sid)
        console.print(f"[bold]{sid}[/bold] {text}")
        console.print_json(json.dumps(v.model_dump() if v else {"verdict": "missing"}))
    console.print(f"calls: {t.calls} | tokens in {t.input_tokens} (cache read {t.cache_read_tokens}, "
                  f"cache write {t.cache_write_tokens}) out {t.output_tokens} | cost ${t.spent_usd:.5f}")


def _ready_db() -> None:
    """Data audit 3: a local SQLite database is migrated; a shared (Postgres) database is only CHECKED - this
    code never changes the live schema behind the owner's back. Behind -> a plain message and `migrate`."""
    from ctxpack import db

    if db.get_engine().dialect.name == "sqlite":
        db.migrate()
        return
    if problems := db.schema_problems():
        console.print(f"{BAD} the database is behind this code ({', '.join(problems[:6])}"
                      f"{', ...' if len(problems) > 6 else ''}). Run: uv run python -m ctxpack.cli migrate",
                      highlight=False)
        raise typer.Exit(1)
    db.SCHEMA_READY.set()


@app.command("label-sample")
def label_sample(
    kind: str = typer.Argument(..., help="relevance (posts from the database) or claims (from a pack)"),
    size: int = typer.Option(100, help="Rows to label (relevance: about 100; claims: about 50)"),
    pack_id: str = typer.Option("", "--pack", help="claims: the pack to sample (featured file or database)"),
    run_id: str = typer.Option("", "--run", help="relevance: only this run's posts"),
) -> None:
    """Data audit 9: a spreadsheet to label by hand, in data/labels/ (git-ignored: it holds post text). Free."""
    import csv

    from ctxpack import db
    from ctxpack import evaluation as ev

    folder = get_settings().data_path / "labels"
    folder.mkdir(parents=True, exist_ok=True)
    if kind == "relevance":
        db.init_engine()
        _ready_db()
        docs = db.get_documents(run_id) if run_id else [d for r in db.list_runs(200) for d in db.get_documents(r.id)]
        header, rows = ev.RELEVANCE_COLUMNS, ev.relevance_sample(docs, size)
        path = folder / "relevance.csv"
    elif kind == "claims":
        if not pack_id:
            console.print(f"{BAD} claims need --pack PACK_ID")
            raise typer.Exit(1)
        from ctxpack.db import FEATURED_DIR

        file = FEATURED_DIR / f"{pack_id}.json"
        if file.exists():
            import json

            pack = json.loads(file.read_text(encoding="utf-8"))
        else:
            db.init_engine()
            _ready_db()
            pack = db.get_pack(pack_id)
        if pack is None:
            console.print(f"{BAD} pack {pack_id} not found")
            raise typer.Exit(1)
        header, rows = ev.CLAIM_COLUMNS, ev.claim_sample(pack, size)
        path = folder / f"claims_{pack_id}.csv"
    else:
        console.print(f"{BAD} kind must be relevance or claims")
        raise typer.Exit(1)
    with path.open("w", encoding="utf-8", newline="") as f:
        w = csv.writer(f)
        w.writerow(header)
        w.writerows(rows)
    console.print(f"{OK} {len(rows)} rows -> {path}\n   {ev.LABEL_HELP[kind]}; then: label-score {kind} {path}",
                  highlight=False)


@app.command("label-score")
def label_score(kind: str = typer.Argument(..., help="relevance or claims"),
                file: str = typer.Argument(..., help="The labelled spreadsheet (CSV)")) -> None:
    """Data audit 9: compare your labels with the model (relevance precision / recall, or human entailment). Free."""
    import csv
    import json

    from ctxpack import evaluation as ev

    with open(file, encoding="utf-8", newline="") as f:
        rows = list(csv.DictReader(f))
    console.print_json(json.dumps(ev.score_labels(kind, rows)))


@app.command()
def migrate(dry_run: bool = typer.Option(False, "--dry-run", help="Only list what is missing")) -> None:
    """Bring the database up to this code: new tables, nullable columns, enum labels, then named steps (each once,
    recorded in schema_migrations). Only ever adds. The app also runs it at start before serving the API."""
    from ctxpack import db

    db.init_engine()
    problems = db.schema_problems()
    if not problems:
        console.print(f"{OK} the database is up to date")
        return
    console.print("missing: " + ", ".join(problems), highlight=False)
    if dry_run:
        return
    applied = db.migrate()
    console.print(f"{OK} applied: " + (", ".join(applied) or "nothing"), highlight=False)


def _print_plan(out) -> None:
    """Interpretation, then the question or the plan, then the estimate."""
    res, est = out.result, out.estimate
    i = res.interpretation
    assumed = {a.value for a in i.assumed}
    console.print("[bold]Here's what I understood[/bold]")
    u = i.understanding
    for name, inp, extra in (("goals", u.goal, ""), ("offer", u.offer, f" [{u.offer_stage.value}]" if u.offer_stage else ""),
                             ("who", u.who, ""), ("markets", u.markets, ""), ("key question", u.key_question, "")):
        where = {"brief": f'from your brief: "{inp.brief_quote}"', "answer": "your answer", "assumed": "assumed",
                 "none": inp.status.value}[inp.source.value]
        console.print(f"  {name:<20}{(inp.value or '-') + extra} [dim]({where})[/dim]", highlight=False)
    for name in ("topic", "languages", "category", "compliance_category", "competitors", "time_window_days"):
        value = getattr(i, name)
        value = ", ".join(value) if isinstance(value, list) else getattr(value, "value", value)
        tag = " [yellow](assumed)[/yellow]" if name in assumed else ""
        console.print(f"  {name:<20}{value or '-'}{tag}", highlight=False)
    if res.interpretation.languages_excluded:
        console.print("  left out:           " + "; ".join(f"{e.language} ({e.reason})"
                                                       for e in res.interpretation.languages_excluded), highlight=False)
    if res.clarifying_questions:
        console.print(f"\n[bold]{len(res.clarifying_questions)} question(s)[/bold]")
        for q in res.clarifying_questions:
            console.print(f"  [bold]{q.id}[/bold] {q.question} [dim]({q.fills.value}"
                          f"{', pick several' if q.multi_select else ''}{', required' if q.required else ''})[/dim]",
                          highlight=False)
            if q.why_it_helps:
                console.print(f"      [dim]why: {q.why_it_helps}[/dim]", highlight=False)
            for n, option in enumerate(q.options, 1):
                console.print(f"      {n}. {option}", highlight=False)
    else:
        p = res.plan
        console.print("\n[bold]Hypotheses[/bold]")
        for h in p.hypotheses:
            console.print(f"  [dim]{h.id}[/dim] {h.statement}", highlight=False)
        console.print("[bold]Research questions[/bold]")
        for q in p.research_questions:
            console.print(f"  [dim]{q.id}[/dim] {q.text}", highlight=False)
        console.print("[bold]Here's where I'll start[/bold]")
        for u in p.starting_units:
            console.print(f"  [cyan]{u.platform.value}[/cyan] {u.kind.value} [bold]{u.target}[/bold]", highlight=False)
            console.print(f"      why: {u.reason}", highlight=False)
            for q in u.queries:
                console.print(f"      [dim]{q.language}[/dim] \"{q.query}\"", highlight=False)
    console.print(f"\n[bold]Estimate[/bold] ({est.mode.value}): typically ${est.typical_usd_low:.2f}-"
                  f"{est.typical_usd_high:.2f}, hard cap ${est.max_usd:.2f}; about {est.typical_minutes} min; "
                  f"at most {est.max_tool_calls} tool calls in {est.collection_secs // 60} min of collection")


def _intake_from(questions, answers, before=None):
    """(Intake, edits) from CLI answers - the same rules as the web app (service.intake_from_answers)."""
    from ctxpack.api.service import intake_from_answers
    from ctxpack.schemas.plan import Intake

    raw, edits = intake_from_answers([q.model_dump(mode="json") for q in questions], answers, skip_all=False,
                                     before=before.model_dump(mode="json") if before else None)
    return Intake.model_validate(raw), edits or None


def _given_intake(goals: list[str], offer: str, offer_stage: str, brand: str = "", parent_brand: str = ""):
    """--goal / --offer / --offer-stage / --brand / --parent-brand as an intake (None when nothing was given);
    a plain error otherwise."""
    from ctxpack.schemas.plan import Intake

    if not (goals or offer or offer_stage or brand):
        return None
    try:
        return Intake.model_validate({"goals": goals, "offer": offer or None, "offer_stage": offer_stage or None,
                                      "brand": brand or None, "parent_brand": parent_brand or None})
    except ValueError as exc:
        console.print(f"{BAD} {exc}", highlight=False)
        raise typer.Exit(1) from None


def _ask_cli(q) -> dict:
    """One answer typed in the terminal; the goal, offer and brand questions are asked again until answered."""
    if q.fills.value == "brand":
        while not (name := typer.prompt(f"{q.id}: your brand", default="", show_default=False).strip()):
            console.print("  this one cannot be skipped: type the brand name", highlight=False)
        parent = typer.prompt("   parent brand (Enter if none)", default="", show_default=False).strip()
        return {"id": q.id, "brand": name, "parent_brand": parent or None}
    hint = ("number(s) in priority order like 3,1" if q.multi_select else "a number") + ", plus your own words"
    while True:
        raw = typer.prompt(f"{q.id}: {hint}" + ("" if q.required else ", or Enter to skip"), default="",
                           show_default=False).strip()
        head, _, rest = raw.partition(" ")
        picks = [int(x) for x in head.split(",") if x.isdigit()]
        if picks and all(1 <= n <= len(q.options) for n in picks):
            chosen = [q.options[n - 1] for n in picks]
            if q.fills.value == "goal" and "Brand perception" in chosen:
                brand = typer.prompt("   your brand (for Brand perception)", default="", show_default=False).strip()
                parent = typer.prompt("   parent brand (Enter if none)", default="", show_default=False).strip()
                return {"id": q.id, "chosen": chosen, "text": rest.strip() or None, "brand": brand or None,
                        "parent_brand": parent or None}
            return {"id": q.id, "chosen": chosen, "text": rest.strip() or None}
        if q.required:
            console.print("  this one cannot be skipped: pick at least one number first", highlight=False)
            continue
        return {"id": q.id, "text": raw} if raw else {"id": q.id, "skipped": True}


@app.command()
def plan(
    brief: str = typer.Argument(..., help='The brief, e.g. "Gen Z and meal prep"'),
    mode: str = typer.Option("quick", help="quick or standard (for the estimate)"),
    window: int = typer.Option(0, help="Time window in days (default from modes.yaml)"),
    agent: bool = typer.Option(False, "--agent", help="Act like an agent: never a clarifying question"),
    answer: str = typer.Option("", help="Your own words for the first optional question (goal and offer: their "
                                       "first chip; others skipped)"),
    as_json: bool = typer.Option(False, "--json", help="Print the raw result as JSON"),
    fixtures: bool = typer.Option(False, "--fixtures", help="LLM_FAKE: no network, no cost"),
) -> None:
    """ONE reasoner call: interpretation + clarifying question or starting plan, with the estimate."""
    import asyncio
    import json
    import os

    from ctxpack.agent.interpret import interpret
    from ctxpack.llm.client import tracking

    if fixtures:
        os.environ["LLM_FAKE"] = "true"
        get_settings.cache_clear()

    async def go(intake=None, edits=None):
        return await interpret(brief, mode=mode, window_days=window or None, allow_question=not agent,
                               intake=intake, edits=edits)

    with tracking() as t:
        out = asyncio.run(go())
        qs = out.result.clarifying_questions
        if qs and answer:  # chips for the required goal and offer questions (first chip), the text for the first
            answers = [{"id": q.id, "chosen": [q.options[0]]} for q in qs if q.required]
            free = next((q for q in qs if not q.required), None)
            if free:
                answers.append({"id": free.id, "text": answer})
            intake, edits = _intake_from(qs, answers)
            out = asyncio.run(go(intake, edits))
    if as_json:
        console.print_json(json.dumps({"result": out.result.model_dump(mode="json"),
                                       "estimate": out.estimate.model_dump(mode="json")}, ensure_ascii=False))
    else:
        _print_plan(out)
    console.print(f"calls: {t.calls} | tokens in {t.input_tokens} out {t.output_tokens} | cost ${t.spent_usd:.4f}")


# --------------------------------------------------------------------------
# research: plan -> approve -> agent loop, printed live (Step 2.5)
# --------------------------------------------------------------------------


def _event_line(e) -> str | None:
    """One readable line per live event (scraped text never appears in events)."""
    p, t = e.payload, e.type.value
    if t == "stage":
        return f"[bold]STAGE[/bold] {p.get('stage')}"
    if t == "agent_call":
        return (f"[cyan]CALL[/cyan]  #{p['seq']} {p['tool']} {p.get('source_unit') or ''}\n"
                f"      [dim]reason:[/dim] {p.get('reason') or '-'}")
    if t == "agent_result":
        if p.get("collected"):
            terms = ", ".join(p.get("new_terms", [])[:5])
            return (f"      -> #{p['seq']} {p['status']}: collected {p['collected']}, kept {p['kept']}, "
                    f"relevant {round(100 * p.get('relevant_share', 0))}%" + (f" | new terms: {terms}" if terms else ""))
        return f"      -> #{p['seq']} {p['status']}"
    if t == "coverage":
        qs = " ".join(f"{q['id']}={q['docs']}" for q in p.get("questions", []))
        return f"[magenta]COVERAGE[/magenta] {qs}"
    if t == "fallback":
        return f"[yellow]FALLBACK[/yellow] {p.get('kind')}: {p.get('reason')}"
    if t == "error":
        return f"[red]ERROR[/red] {p.get('message')}"
    return None


def _print_summary(run) -> None:
    from ctxpack import db
    from ctxpack.orchestrator import cost_lines

    col = run.collection or {}
    counters = next((e.payload for e in reversed(db.get_events(run.id, limit=100000))
                     if e.type.value == "counters"), {})
    console.print(f"\n[bold]FINISH[/bold] {run.status.value} | reason {run.finish_reason} | "
                  f"fallback {run.fallback_used} | top-up {run.top_up_used} | tool calls {run.tool_calls}")
    if counters:
        console.print("[bold]CLEAN[/bold] " + " | ".join(f"{k} {v}" for k, v in counters.items()))
    console.print("[bold]KEPT[/bold]")
    for s in col.get("sources_used", []):
        console.print(f"  {s['source_unit']}: {s['kept']} docs, {round(100 * s['relevant_share'])}% relevant"
                      f" - {s['reason']}", highlight=False)
    console.print("[bold]DROPPED[/bold]")
    for s in col.get("sources_dropped", []):
        console.print(f"  {s['source_unit']}: {s['reason']}", highlight=False)
    console.print("[bold]GAPS[/bold]")
    for g in col.get("gaps", []):
        console.print(f"  {g}", highlight=False)
    console.print(f"[bold]COST[/bold] Apify ${run.cost_apify_usd:.3f} | Anthropic ${run.cost_llm_usd:.3f} | "
                  f"total ${run.cost_apify_usd + run.cost_llm_usd:.3f}")
    for line in cost_lines(run):
        console.print(f"  {line}", highlight=False)
    console.print(f"[bold]RUN[/bold] {run.id} | relevant docs {col.get('relevant_total', 0)} | "
                  f"peak memory {run.peak_mem_mb} MB")



def _execute(run_id: str, brief: str, *, no_apify: bool = False, apify_max: float = -1.0, record: bool = False):
    """Queue a planned run, claim it and run the whole pipeline here, printing live events and the summary."""
    import asyncio
    import signal
    import time

    from ctxpack import db, orchestrator
    from ctxpack.collect import loop

    orchestrator.enqueue(run_id)
    claimed = db.claim_next_run()
    if claimed is None or claimed.id != run_id:
        console.print(f"{BAD} another run is waiting in the queue; run {run_id} stays queued for the worker")
        raise typer.Exit(1)

    async def collect(rid: str) -> None:
        state = orchestrator.loop_state(rid, no_apify=no_apify,
                                        apify_usd_cap=apify_max if apify_max >= 0 else None)
        await loop.run_loop(state)
        if record:
            path = loop.save_transcript(brief, state)
            console.print(f"transcript saved: {path}")

    async def go() -> None:
        signal_loop = asyncio.get_running_loop()
        signal_loop.add_signal_handler(signal.SIGINT, lambda: (
            console.print("[yellow]Stopping - packaging what was collected...[/yellow]"),
            orchestrator.request_stop(run_id)))
        from ctxpack import worker  # the worker's job runner: same heartbeat, so the live service never treats
        #                             a CLI run as crashed and takes it over (audit finding 1)
        task = asyncio.create_task(worker.run_job(run_id, collect=collect))
        last = 0
        while True:
            done = task.done()
            for e in db.get_events(run_id, after_seq=last):
                last = e.seq
                if line := _event_line(e):
                    console.print(line, highlight=False)
            if done:
                break
            await asyncio.sleep(0.5)
        await task

    started = time.monotonic()
    asyncio.run(go())
    final = db.get_run(run_id)
    _print_summary(final)
    if final.pack_id:
        _print_exports(db.get_pack(final.pack_id))
    console.print(f"took {time.monotonic() - started:.0f} s")
    return final


@app.command()
def research(
    brief: str = typer.Argument(..., help='The brief, e.g. "Gen Z and meal prep"'),
    mode: str = typer.Option("quick", help="quick or standard"),
    window: int = typer.Option(0, help="Time window in days (default from modes.yaml)"),
    fixtures: bool = typer.Option(False, "--fixtures", help="Recorded data and fake model: no network, $0"),
    auto_approve: bool = typer.Option(False, "--auto-approve", help="No question, no Enter: run the plan"),
    brand_voice: str = typer.Option("", "--brand-voice", help="One line; used only by the playbook"),
    record: bool = typer.Option(False, "--record", help="Save the agent's tool calls as a fake-mode transcript"),
    no_apify: bool = typer.Option(False, "--no-apify", help="No Apify tools this run: web sources only"),
    apify_max: float = typer.Option(-1.0, "--apify-max", help="Lower Apify cap (USD) for this run"),
    goal: list[str] = typer.Option([], "--goal", help="What the research is for, main goal first (repeatable): "
                                   "content_plan, campaign_launch, positioning, product_validation, market_entry, "
                                   "brand_perception, sales_enablement, understand_audience"),
    offer: str = typer.Option("", "--offer", help="What you offer, in a few words"),
    offer_stage: str = typer.Option("", "--offer-stage", help="idea, launching, selling or no_offer"),
    brand: str = typer.Option("", "--brand", help="Your brand as people write it (needed for brand_perception)"),
    parent_brand: str = typer.Option("", "--parent-brand", help="Its parent brand, if any"),
) -> None:
    """Plan -> show it and wait for Enter -> the agent loop, printed live -> counters, sources, cost."""
    import asyncio
    import os

    from ctxpack import db
    from ctxpack.agent.interpret import interpret
    from ctxpack.llm.client import tracking
    from ctxpack.schemas.enums import Mode, Requester, RunStatus

    if mode not in ("quick", "standard"):
        console.print(f"{BAD} mode must be quick or standard")
        raise typer.Exit(1)
    from ctxpack.config import load_yaml

    given = _given_intake(goal, offer, offer_stage, brand, parent_brand)
    if auto_approve and not (given and given.goals):  # V11: nobody is asked, so the goal must be given
        console.print(f"{BAD} --auto-approve needs --goal (main goal first): "
                      + ", ".join(load_yaml("goals")["goals"]), highlight=False)
        raise typer.Exit(1)
    if auto_approve and given and "brand_perception" in given.goals and not given.brand:
        console.print(f"{BAD} the brand_perception goal needs --brand", highlight=False)
        raise typer.Exit(1)
    if fixtures:
        os.environ["USE_FIXTURES"] = "true"
        os.environ["LLM_FAKE"] = "true"
        os.environ.setdefault("AUTHOR_HASH_SALT", "fixtures-only-not-a-secret")
        get_settings.cache_clear()
        db.init_engine(f"sqlite:///{get_settings().data_path / 'fixtures.db'}")   # never the real database
    else:
        for name in ("ANTHROPIC_API_KEY", "APIFY_API_TOKEN", "AUTHOR_HASH_SALT", "DATABASE_URL"):
            if not get_settings().is_set(name):
                console.print(f"{BAD} {name} not set - run the doctor command")
                raise typer.Exit(1)
        db.init_engine()
    _ready_db()

    run = db.create_run(brief, mode=Mode(mode), requester=Requester.cli)
    if brand_voice:
        db.update_run(run.id, brand_voice=brand_voice[:200])

    async def plan(intake=None, edits=None):
        with tracking(run.id):
            return await interpret(brief, mode=mode, window_days=window or None, allow_question=not auto_approve,
                                   intake=intake, edits=edits)

    out = asyncio.run(plan(given))
    intake = given
    if out.result.clarifying_questions:
        _print_plan(out)
        answers = [_ask_cli(q) for q in out.result.clarifying_questions]
        intake, edits = _intake_from(out.result.clarifying_questions, answers, given)
        out = asyncio.run(plan(intake, edits))
    _print_plan(out)
    db.update_run(run.id, interpretation=out.result.interpretation.model_dump(mode="json"),
                  plan=out.result.plan.model_dump(mode="json"),
                  intake=intake.model_dump(mode="json") if intake else None)
    if not auto_approve:
        typer.prompt("\nPress Enter to start (Ctrl-C to cancel)", default="", show_default=False)

    final = _execute(run.id, brief, no_apify=no_apify, apify_max=apify_max, record=record)
    if final.status == RunStatus.failed:
        raise typer.Exit(1)


@app.command()
def extract(
    from_run: str = typer.Option(..., "--from-run", help="Run id whose saved corpus is extracted"),
    show: int = typer.Option(5, help="Enriched docs to print afterwards"),
    limit: int = typer.Option(0, help="Only this many docs (0 = all still to do)"),
    redo: bool = typer.Option(False, "--redo", help="Extract docs again even if already done"),
    yes: bool = typer.Option(False, "--yes", help="Do not wait for Enter before the paid calls"),
) -> None:
    """Step 3.1 on a saved corpus: extraction for every relevant doc, then a few enriched docs + cost.

    The cost is added to that run (its analysis LLM budget applies) and to today's spend.
    """
    import asyncio
    import json

    from ctxpack import db, orchestrator
    from ctxpack.analysis.extract import estimate_usd, extract_run, pending
    from ctxpack.config import mode_limits
    from ctxpack.llm.client import tracking

    db.init_engine()
    _ready_db()
    run = db.get_run(from_run)
    if run is None or not run.plan:
        console.print(f"{BAD} run {from_run} not found or never planned")
        raise typer.Exit(1)
    if run.finish_reason is None:
        console.print(f"{BAD} run {from_run} has not finished collecting")
        raise typer.Exit(1)

    relevant = db.get_documents(from_run, relevant_only=True)
    todo = pending(from_run, redo=redo, limit=limit or None)
    limit_usd = mode_limits(run.mode)["analysis_llm_usd"]
    console.print(f"run {run.id} ({run.brief_text[:50]}) | relevant docs {len(relevant)} | to extract {len(todo)} "
                  f"({sum(len(d.text) for d in todo)} chars)", highlight=False)
    console.print(f"estimated max cost ${estimate_usd(todo):.2f} | run analysis LLM spend so far "
                  f"${run.cost_analysis_llm_usd or 0:.2f} of ${limit_usd:.2f}", highlight=False)
    if todo and not yes and not get_settings().llm_fake:
        typer.prompt("Press Enter to start (Ctrl-C to cancel)", default="", show_default=False)

    with tracking(run.id, llm_limit_usd=limit_usd, analysis=True) as t:
        before = t.spent_usd
        outcome = asyncio.run(extract_run(run.id, orchestrator.brief_context(run), redo=redo, limit=limit or None))
        spent = t.spent_usd - before

    done = [d for d in db.get_documents(from_run, relevant_only=True) if d.extraction is not None]
    done.sort(key=lambda d: d.id)
    step = max(1, len(done) // show) if show else 0
    for d in done[::step][:show] if show else []:
        console.rule(f"{d.id} | {d.source_unit} | {d.language}", style="dim")
        console.print(f"[bold]text[/bold]    {d.text[:400]}", highlight=False)
        if d.text_en:
            console.print(f"[bold]text_en[/bold] {d.text_en[:400]}", highlight=False)
        console.print_json(json.dumps(d.extraction, ensure_ascii=False))

    console.print(f"\n[bold]EXTRACT[/bold] docs {outcome.extracted} | missing {len(outcome.missing)} | "
                  f"untranslated {outcome.untranslated} | "
                  f"phrases kept {outcome.phrases_kept} dropped (not exact) {outcome.phrases_dropped} | "
                  f"done {len(done)} of {len(relevant)} relevant", highlight=False)
    console.print(f"[bold]COST[/bold] this step ${spent:.4f} in {outcome.calls} calls | tokens in {t.input_tokens} "
                  f"out {t.output_tokens} | run analysis ${t.budget_spent_usd:.3f} of ${limit_usd:.2f} | "
                  f"run LLM total ${t.spent_usd:.3f}", highlight=False)
    if outcome.missing:
        raise typer.Exit(1)


@app.command()
def cluster(
    from_run: str = typer.Option(..., "--from-run", help="Run id whose extracted corpus is clustered"),
    redo: bool = typer.Option(False, "--redo", help="Delete the saved clusters and cluster again"),
    yes: bool = typer.Option(False, "--yes", help="Do not wait for Enter before the paid calls"),
) -> None:
    """Step 3.2 on a saved corpus: one clustering call, the membership check, then the metrics (code).

    Prints clusters with verified-member counts, rejections, platform lens and top opportunities.
    The cost is added to that run (its analysis LLM budget applies) and to today's spend.
    """
    import asyncio

    from ctxpack import db, orchestrator
    from ctxpack.analysis import cluster as clu
    from ctxpack.analysis.metrics import compute_run
    from ctxpack.config import mode_limits
    from ctxpack.llm.client import tracking

    db.init_engine()
    _ready_db()
    run = db.get_run(from_run)
    if run is None or not run.plan or run.finish_reason is None:
        console.print(f"{BAD} run {from_run} not found or has not finished collecting")
        raise typer.Exit(1)
    relevant = db.get_documents(from_run, relevant_only=True)
    if any(d.extraction is None for d in relevant if not d.short_form):
        console.print(f"{BAD} some relevant docs have no extraction yet: run extract --from-run {from_run} first")
        raise typer.Exit(1)
    saved = [] if redo else db.get_clusters(from_run)
    limit_usd = mode_limits(run.mode)["analysis_llm_usd"]
    est = 0.0 if saved and all((c.details or {}).get("verified") for c in saved) else clu.estimate_usd(relevant)
    console.print(f"run {run.id} ({run.brief_text[:50]}) | relevant docs {len(relevant)} | saved clusters "
                  f"{len(saved)}", highlight=False)
    console.print(f"estimated max cost ${est:.2f} | run analysis LLM spend so far "
                  f"${run.cost_analysis_llm_usd or 0:.2f} of ${limit_usd:.2f}", highlight=False)
    if est and not yes and not get_settings().llm_fake:
        typer.prompt("Press Enter to start (Ctrl-C to cancel)", default="", show_default=False)

    with tracking(run.id, llm_limit_usd=limit_usd, analysis=True) as t:
        before = t.spent_usd
        out = asyncio.run(clu.cluster_run(run.id, orchestrator.brief_context(run), redo=redo))
        spent = t.spent_usd - before
    analysis = compute_run(run.id)

    console.print("\n[bold]CLUSTERS[/bold] (verified of proposed; rejected by the check)")
    flagged = []
    for c in db.get_clusters(run.id):
        st = out.by_cluster.get(c.id, {})
        proposed, verified = st.get("proposed", len(c.member_ids)), len(c.verified_member_ids)
        keep = verified / proposed if proposed else 0
        if proposed and keep < 0.7:
            flagged.append(c.id)
        n = c.metrics["counts"]
        extra = f" = {c.details.get('meaning')}" if c.kind == "lexicon" else ""
        console.print(f"  {c.id} {c.kind:<12} {n['matching']:>3} of {n['of_total']} | verified {verified}/{proposed}"
                      f"{' [red]<70%[/red]' if c.id in flagged else ''} | {c.label}{extra}", highlight=False)
        if c.kind not in ("lexicon", "competitor") and c.details.get("point"):
            console.print(f"       [dim]{c.details['point']}[/dim]", highlight=False)
    share = out.verified / out.proposed if out.proposed else 0
    console.print(f"\n[bold]CHECK[/bold] pairs proposed {out.proposed} | verified {out.verified} ({share:.0%}) | "
                  f"rejected {out.rejected} | unchecked {out.unchecked} | invented ids dropped {out.invented_ids} | "
                  f"clusters under 70%: {', '.join(flagged) or 'none'}", highlight=False)
    console.print("[bold]PLATFORM LENS[/bold]")
    for lens in analysis["platform_lens"]:
        top = ", ".join(f"{s['label']} {s['share']:.0%}" for s in lens["theme_shares"][:4])
        emo = ", ".join(f"{e['emotion']} {e['share']:.0%}" for e in lens["emotion_mix"][:4])
        console.print(f"  {lens['platform']}: {lens['kept_posts']} posts | themes: {top} | emotions: {emo}",
                      highlight=False)
    if not analysis["platform_lens"]:
        console.print("  (no platform with 15+ relevant posts)")
    console.print("[bold]COMPETITORS[/bold] " + (", ".join(
        f"{c['name']} {c['mentions']} ({c['share']:.0%})" for c in analysis["competitors"]) or "none with 3+ mentions"),
        highlight=False)
    console.print("[bold]TOP OPPORTUNITIES[/bold] (score if non-obvious; novelty is set in Step 3.4)")
    for o in analysis["opportunities"][:5]:
        comp = o["components"]
        console.print(f"  {o['cluster_id']} {o['score_if_non_obvious']:.2f} | demand {comp['demand']:.2f} "
                      f"dissatisfaction {comp['dissatisfaction']:.2f} saturation {comp['saturation']:.2f} | "
                      f"{o['members']} members | {o['label']}", highlight=False)
    cov = analysis["coverage"]
    console.print(f"[bold]COVERAGE[/bold] grade {cov['grade']} | kept {cov['kept']} | platforms "
                  f"{', '.join(cov['platforms'])} | languages {', '.join(cov['languages'])} | dated "
                  f"{cov['dated_share']:.0%} | whats_new {len(analysis['whats_new'])} | what performs "
                  f"{len(analysis['what_performs'])}", highlight=False)
    console.print(f"[bold]COST[/bold] this step ${spent:.4f} in {out.calls} calls | tokens in {t.input_tokens} "
                  f"out {t.output_tokens} | run analysis ${t.budget_spent_usd:.3f} of ${limit_usd:.2f}"
                  f"{' | resumed: no clustering call' if out.resumed else ''}", highlight=False)


@app.command()
def write(
    from_run: str = typer.Option(..., "--from-run", help="Run id whose clusters are written up"),
    redo: bool = typer.Option(False, "--redo", help="Write the draft again (generic points included)"),
    show: str = typer.Option("tensions,voice,white_space", help="Draft sections to print as JSON"),
    extra_budget: float = typer.Option(0.0, "--extra-budget", min=0.0, max=3.0,
                                       help="Owner-approved one-off USD on top of this run's analysis budget "
                                            "(rebuilds only; modes.yaml is unchanged)"),
    yes: bool = typer.Option(False, "--yes", help="Do not wait for Enter before the paid calls"),
) -> None:
    """Step 3.3 on a saved run: generic baseline, two writer calls, non_obvious -> a DRAFT pack.

    The cost is added to that run (its analysis LLM budget applies) and to today's spend.
    """
    import asyncio
    import json

    from ctxpack import db, orchestrator
    from ctxpack.config import mode_limits
    from ctxpack.llm.client import tracking
    from ctxpack.synthesis import write as wr

    db.init_engine()
    _ready_db()
    run = db.get_run(from_run)
    clusters = db.get_clusters(from_run) if run else []
    if run is None or not clusters or not run.analysis:
        console.print(f"{BAD} run {from_run} has no clusters yet: run cluster --from-run {from_run} first")
        raise typer.Exit(1)
    limit_usd = mode_limits(run.mode)["analysis_llm_usd"] + extra_budget
    if extra_budget:
        console.print(f"[yellow]extra budget ${extra_budget:.2f} on top of this run's analysis budget "
                      f"(owner-approved rebuild)[/yellow]")
    done = bool((run.draft or {}).get("sections")) and not redo
    est = 0.0 if done else wr.estimate_usd(clusters)
    console.print(f"run {run.id} ({run.brief_text[:50]}) | clusters {len(clusters)} | draft saved {done}",
                  highlight=False)
    console.print(f"estimated max cost ${est:.2f} | run analysis LLM spend so far "
                  f"${run.cost_analysis_llm_usd or 0:.2f} of ${limit_usd:.2f}", highlight=False)
    if est and not yes and not get_settings().llm_fake:
        typer.prompt("Press Enter to start (Ctrl-C to cancel)", default="", show_default=False)

    with tracking(run.id, llm_limit_usd=limit_usd, analysis=True) as t:
        before = t.spent_usd
        out = asyncio.run(wr.write_run(run.id, orchestrator.brief_context(run), redo=redo))
        spent = t.spent_usd - before

    draft = db.get_run(run.id).draft
    sections = draft["sections"]
    for name in [x.strip() for x in show.split(",") if x.strip()]:
        console.rule(name, style="dim")
        console.print_json(json.dumps(sections.get(name), ensure_ascii=False))
    console.print("\n[bold]GENERIC POINTS[/bold] (baseline, no evidence)")
    for g in draft["generic_points"]:
        console.print(f"  - {g}", highlight=False)
    written = {n: len(v) for n, v in sections.items() if isinstance(v, list)}
    console.print("[bold]WRITTEN[/bold] " + " | ".join(f"{n} {c}" for n, c in written.items()), highlight=False)
    if out.dropped:
        console.print("[bold]DROPPED[/bold] " + " | ".join(f"{k} {v}" for k, v in out.dropped.items()),
                      highlight=False)
    problems = wr.check_draft(draft, clusters)
    ws = sections["white_space"]
    console.print(f"[bold]CHECK[/bold] evidence ids resolve and belong to their cluster: "
                  f"{'yes' if not problems else 'NO - ' + '; '.join(problems[:5])} | evidence {len(draft['evidence'])}"
                  f" | lexicon {len(sections['lexicon'])} (standard >= 15) | white space non-obvious "
                  f"{sum(w['non_obvious'] for w in ws)} of {len(ws)}", highlight=False)
    console.print(f"[bold]COST[/bold] this step ${spent:.4f} in {out.calls} calls | tokens in {t.input_tokens} "
                  f"out {t.output_tokens} | run analysis ${t.budget_spent_usd:.3f} of ${limit_usd:.2f}"
                  f"{' | resumed: draft already saved' if out.resumed else ''}", highlight=False)
    if problems:
        raise typer.Exit(1)


@app.command()
def verify(
    from_run: str = typer.Option(..., "--from-run", help="Run id whose draft is verified"),
    redo: bool = typer.Option(False, "--redo", help="Verify the draft again"),
    extra_budget: float = typer.Option(0.0, "--extra-budget", min=0.0, max=3.0,
                                       help="Owner-approved one-off USD on top of this run's analysis budget "
                                            "(rebuilds only; modes.yaml is unchanged)"),
    yes: bool = typer.Option(False, "--yes", help="Do not wait for Enter before the paid calls"),
) -> None:
    """Step 3.4 on a saved draft: exact quotes, claim checks, confidence labels.

    The cost is added to that run (its analysis LLM budget applies) and to today's spend.
    """
    import asyncio

    from ctxpack import db
    from ctxpack.config import mode_limits
    from ctxpack.llm.client import tracking
    from ctxpack.synthesis import verify as vf
    from ctxpack.synthesis.write import INSIGHT_SECTIONS

    db.init_engine()
    _ready_db()
    run = db.get_run(from_run)
    draft = (run.draft or {}) if run else {}
    if not draft.get("sections"):
        console.print(f"{BAD} run {from_run} has no draft yet: run write --from-run {from_run} first")
        raise typer.Exit(1)
    limit_usd = mode_limits(run.mode)["analysis_llm_usd"] + extra_budget
    if extra_budget:
        console.print(f"[yellow]extra budget ${extra_budget:.2f} on top of this run's analysis budget "
                      f"(owner-approved rebuild)[/yellow]")
    est = 0.0 if draft.get("verified") and not redo else vf.estimate_usd(draft)
    console.print(f"run {run.id} ({run.brief_text[:50]}) | estimated max cost ${est:.2f} | run analysis LLM "
                  f"spend so far ${run.cost_analysis_llm_usd or 0:.2f} of ${limit_usd:.2f}", highlight=False)
    if est and not yes and not get_settings().llm_fake:
        typer.prompt("Press Enter to start (Ctrl-C to cancel)", default="", show_default=False)

    with tracking(run.id, llm_limit_usd=limit_usd, analysis=True) as t:
        before = t.spent_usd
        rep = asyncio.run(vf.verify_run(run.id, redo=redo))
        spent = t.spent_usd - before

    verified = db.get_run(run.id).draft["verified"]
    s = verified["sections"]
    console.print("\n[bold]LABELS[/bold] (score, label, verdict, safe to assert)")
    for name in INSIGHT_SECTIONS:
        for it in s[name]:
            c = it["confidence"]
            console.print(f"  {it['id']:<7} {c['score']:.2f} {c['label']:<11} {it['verification']['verdict']:<19} "
                          f"{'SAFE ' if it['safe_to_assert'] else '     '}{it['counts']['matching']:>3} posts | "
                          f"{it['claim'][:70]}", highlight=False)
    console.print(f"\n[bold]QUOTES[/bold] checked {rep.quotes_checked} | whitespace fixed {rep.quotes_whitespace_fixed} | "
                  f"removed {rep.quotes_removed} | groundedness {rep.groundedness:.0%}", highlight=False)
    console.print(f"[bold]CLAIMS[/bold] supported {rep.supported} | partially (one level down, inferred) "
                  f"{rep.partially_supported} | not supported (dropped) {rep.not_supported} | unchecked "
                  f"{rep.unchecked} | items dropped without evidence {rep.items_dropped_no_evidence} | phrases "
                  f"dropped {rep.phrases_dropped}", highlight=False)
    console.print("[bold]LABEL COUNTS[/bold] " + " | ".join(f"{k} {v}" for k, v in rep.labels.items())
                  + f" | safe to assert {rep.safe_to_assert} | thin evidence {rep.thin_evidence}", highlight=False)
    if rep.dropped_items:
        console.print(f"[bold]DROPPED[/bold] {', '.join(rep.dropped_items)}", highlight=False)
    console.print(f"[bold]COST[/bold] this step ${spent:.4f} in {rep.calls} calls | run analysis "
                  f"${t.budget_spent_usd:.3f} of ${limit_usd:.2f}{' | resumed: already verified' if rep.resumed else ''}",
                  highlight=False)


@app.command()
def pack(
    from_run: str = typer.Option(..., "--from-run", help="Run id whose verified draft is packaged"),
    brand_voice: str = typer.Option("", help="Brand voice for the playbook only (max 200 chars)"),
    test_hook: list[str] = typer.Option([], "--test-hook", help="Extra text for the compliance check only"),
    redo: bool = typer.Option(False, "--redo", help="Write the playbook again for this brand voice"),
    extra_budget: float = typer.Option(0.0, "--extra-budget", min=0.0, max=3.0,
                                       help="Owner-approved one-off USD on top of this run's analysis budget "
                                            "(rebuilds only; modes.yaml is unchanged)"),
    yes: bool = typer.Option(False, "--yes", help="Do not wait for Enter before the paid calls"),
) -> None:
    """Step 3.5 on a verified draft: playbook + compliance + finalise -> a validated, saved Context Pack.

    The cost is added to that run (its analysis LLM budget applies) and to today's spend.
    """
    import asyncio

    from ctxpack import db
    from ctxpack.config import mode_limits, model_for
    from ctxpack.llm.client import cost_usd, tracking
    from ctxpack.synthesis.finalize import package_run

    db.init_engine()
    _ready_db()
    run = db.get_run(from_run)
    if run is None or not (run.draft or {}).get("verified"):
        console.print(f"{BAD} run {from_run} has no verified draft: run verify --from-run {from_run} first")
        raise typer.Exit(1)
    voice = brand_voice.strip()[:200] or None
    saved = ((run.draft or {}).get("playbooks") or {}).get(voice or "_neutral")
    limit_usd = mode_limits(run.mode)["analysis_llm_usd"] + extra_budget
    if extra_budget:
        console.print(f"[yellow]extra budget ${extra_budget:.2f} on top of this run's analysis budget "
                      f"(owner-approved rebuild)[/yellow]")
    est = 0.0 if saved and not redo and not test_hook else 2 * (
        cost_usd(model_for("reasoner"), 9000, 7000) + cost_usd(model_for("reasoner"), 2500, 2500))
    console.print(f"run {run.id} ({run.brief_text[:50]}) | brand voice: {voice or 'none'} | estimated max cost "
                  f"${est:.2f} | run analysis LLM ${run.cost_analysis_llm_usd or 0:.2f} of ${limit_usd:.2f}",
                  highlight=False)
    if est and not yes and not get_settings().llm_fake:
        typer.prompt("Press Enter to start (Ctrl-C to cancel)", default="", show_default=False)

    with tracking(run.id, llm_limit_usd=limit_usd, analysis=True) as t:
        before = t.spent_usd
        out = asyncio.run(package_run(run.id, brand_voice=voice, use_run_brand_voice=False, redo=redo,
                                      test_hooks=list(test_hook)))
        spent = t.spent_usd - before
    p = db.get_pack(out.pack_id)

    def show(title: str, lines: list[str]) -> None:
        console.print(f"\n[bold]{title}[/bold]")
        for line in lines:
            console.print(f"  {line}", highlight=False, markup=False)  # [brackets] are text here, not styling

    show("DO FIRST", [f"{d['id']} [{d['effort']} effort / {d['impact']} impact, {d['owner_hint']}] {d['action']} "
                      f"<- {', '.join(d['why_ids'])}" for d in p["do_first"]])
    show("CHANNEL PLAN", [f"{c['priority']}. {c['platform']}: {c['why']} <- {', '.join(c['why_ids'])} | formats "
                          f"{', '.join(c['formats'])} | {c['tone_note']}" for c in p["channel_plan"]])
    show("HOOKS", [f"{h['id']} {h['text']} <- {', '.join(h['why_ids'])}" for h in p["playbook"]["hooks"]])
    show("THIS WEEK", [f"{w['day']}: {w['platform']} {w['format']} - {w['hook_id']} - {w['angle']}"
                       f"{' (' + w['moment_id'] + ')' if w['moment_id'] else ''}" for w in p["playbook"]["this_week"]])
    cb = p["playbook"]["creative_brief"] or {}
    show("CREATIVE BRIEF", [f"{k}: {v}" for k, v in cb.items() if v])
    g = p["guardrails"]
    show("GUARDRAILS", [f"say this: {'; '.join(g['say_this'])}", f"not this: {'; '.join(g['not_this'])}",
                        f"never claim: {'; '.join(g['never_claim'])}", f"sensitivities: {'; '.join(g['sensitivities'])}"])
    show("COMPLIANCE FLAGS", [f"{f['id']} {f['item_id']} [{f['category']}] {f['rule_area']}: {f['why']} -> "
                              f"{f['safer_wording']}" for f in p["compliance_flags"]] or ["none"])
    if test_hook:
        flagged = {f["text"]: f for f in out.test_flags}
        show("TEST HOOKS (not in the pack)", [
            f"{h} -> " + (f"[{flagged[h]['category']}] {flagged[h]['rule_area']}: {flagged[h]['safer_wording']}"
                          if h in flagged else "no flag") for h in test_hook])
    from ctxpack.schemas.pack import SCHEMA_VERSION

    console.print(f"\n[bold]PACK[/bold] {out.pack_id} | valid schema {SCHEMA_VERSION} | thin evidence "
                  f"{p['coverage']['thin_evidence']}{': ' + ', '.join(out.bar_short) if out.bar_short else ''}",
                  highlight=False)
    console.print(f"[bold]PLAYBOOK CHECK[/bold] hooks {len(p['playbook']['hooks'])} | hooks without a tension "
                  f"{out.hooks_without_tension} | dropped {out.playbook_dropped or 'none'}"
                  f"{' | reused saved playbook' if out.reused_playbook else ''}", highlight=False)
    console.print(f"[bold]COST[/bold] this step ${spent:.4f} in {out.calls} calls | run analysis "
                  f"${t.budget_spent_usd:.3f} of ${limit_usd:.2f}", highlight=False)
    _print_exports(p)


def _print_exports(p: dict) -> None:
    """Write every export of a pack to data/packs/<pack_id>/ and list the files."""
    from collections import Counter

    from ctxpack.exports import write_exports
    from ctxpack.exports.common import tokens
    from ctxpack.synthesis.write import INSIGHT_SECTIONS

    paths = write_exports(p, get_settings().data_path / "packs" / p["pack_id"])
    items = [it for name in INSIGHT_SECTIONS if name not in ("lexicon", "phrases", "culture", "themes")
             for it in p.get(name, [])] + p["voice"]["lexicon"] + p["voice"]["phrases"] + p["landscape"]["themes"]
    items += [c for part in p["culture"].values() for c in part]
    labels = Counter(it["confidence"]["label"] for it in items)
    console.print("[bold]LABELS[/bold] " + " | ".join(f"{k} {labels.get(k, 0)}"
                                                     for k in ("strong", "moderate", "emerging", "speculative")),
                  highlight=False)
    console.print("[bold]EXPORTS[/bold]")
    for kind, path in paths.items():
        size = path.stat().st_size
        extra = f" (~{tokens(path.read_text(encoding='utf-8'))} tokens)" if path.suffix in (".txt", ".md") else ""
        console.print(f"  {kind:<13} {path} ({size:,} bytes){extra}", highlight=False)


@app.command()
def export(pack_id: str = typer.Argument(..., help="A saved pack id")) -> None:
    """Write every export of a saved pack to data/packs/<pack_id>/ (free: no model calls)."""
    from ctxpack import db

    db.init_engine()
    _ready_db()
    p = db.get_pack(pack_id)
    if p is None:
        console.print(f"{BAD} pack {pack_id} not found")
        raise typer.Exit(1)
    _print_exports(p)


@app.command()
def feature(pack_id: str = typer.Argument(..., help="A finished pack to publish as featured"),
            replaces: str = typer.Option("", "--replaces", help="An older featured pack this one replaces")) -> None:
    """Privacy check, then featured/<pack_id>.json + examples/<slug>.json, .md and the skill folder (free).

    Stops (and writes nothing) on any email, phone, @handle, profile URL or quote over 280 characters.
    These files go into the PUBLIC repo: read them before committing.
    """
    from ctxpack import db
    from ctxpack.exports.featured import feature as write_featured

    db.init_engine()
    _ready_db()
    p = db.get_pack(pack_id)
    if p is None:
        console.print(f"{BAD} pack {pack_id} not found")
        raise typer.Exit(1)
    try:
        paths = write_featured(p)
    except ValueError as exc:
        console.print(f"{BAD} {exc}", highlight=False, markup=False)
        raise typer.Exit(1) from None
    db.set_featured(pack_id)
    console.print(f"{OK} privacy check passed; featured {pack_id}")
    if replaces and replaces != pack_id:
        from ctxpack.db import FEATURED_DIR

        (FEATURED_DIR / f"{replaces}.json").unlink(missing_ok=True)
        db.set_featured(replaces, False)
        console.print(f"  replaced      {replaces} (file removed, no longer featured; still readable by id)")
    for kind, path in paths.items():
        console.print(f"  {kind:<13} {path}", highlight=False)


@app.command("redact-run")
def redact_run_cmd(run_id: str = typer.Argument(..., help="A saved run")) -> None:
    """Re-apply the current redaction to a saved run: documents, draft and packs (free, no model calls).
    Re-export the packs afterwards with: export PACK_ID."""
    from ctxpack import db
    from ctxpack.maintenance import redact_run

    db.init_engine()
    _ready_db()
    rep = redact_run(run_id)
    console.print(f"{OK} run {run_id}: documents changed {rep.documents_changed} | text-fragment links dropped "
                  f"{rep.anchors_cleared} | strings changed {rep.strings_changed} | quotes removed "
                  f"{rep.quotes_removed} | packs re-saved {', '.join(rep.packs_saved) or 'none'}", highlight=False)


@app.command()
def overlap(run_ids: list[str] = typer.Argument(..., help="Two or more run ids")) -> None:
    """How much the runs' source units overlap (eval: briefs share < 50%)."""
    from ctxpack import db
    from ctxpack.orchestrator import source_units, units_overlap

    db.init_engine()
    _ready_db()
    units = {}
    for rid in run_ids:
        run = db.get_run(rid)
        if run is None:
            console.print(f"{BAD} run {rid} not found")
            raise typer.Exit(1)
        units[f"{rid} ({run.brief_text[:40]})"] = source_units(run)
    for name, us in units.items():
        console.print(f"[bold]{name}[/bold]: {', '.join(sorted(us)) or '-'}", highlight=False)
    report = units_overlap(list(units.values()))
    console.print(f"\nshared units: {report['shared']} of {report['total']} "
                  f"= {round(100 * report['share'])}% (target < 50%) | "
                  f"largest pairwise overlap {round(100 * report['max_pairwise'])}%")


# --------------------------------------------------------------------------
# eval: the four test briefs (Step 5.1, Appendix F5, PRD 14)
# --------------------------------------------------------------------------


def _eval_pack(spec: dict, reuse: bool):
    """(pack, run) for a brief that is scored without a new run, or None."""
    import json

    from ctxpack import db
    from ctxpack.db import FEATURED_DIR

    row = None
    if spec.get("reuse_pack"):
        with db.session() as s:
            row = s.get(db.PackRow, spec["reuse_pack"])
        if row is None and (FEATURED_DIR / f"{spec['reuse_pack']}.json").is_file():
            return json.loads((FEATURED_DIR / f"{spec['reuse_pack']}.json").read_text(encoding="utf-8")), None
    elif reuse:
        row = db.latest_pack_for_brief(spec["brief"])
    if row is None:
        return None
    return row.pack, (db.get_run(row.run_id) if row.run_id else None)


def _eval_answer(q, given: dict) -> dict:
    """An eval run's answer: the brief's goals (in order) and offer stage from briefs.yaml, else the first chip."""
    from ctxpack.config import load_yaml

    cfg = load_yaml("goals")
    if q.fills.value == "goal" and given.get("goals"):
        return {"id": q.id, "chosen": [cfg["goals"][g]["chip"] for g in given["goals"]],
                "brand": given.get("brand"), "parent_brand": given.get("parent_brand")}
    if q.fills.value == "brand":
        return {"id": q.id, "brand": given.get("brand") or "", "parent_brand": given.get("parent_brand")}
    if q.fills.value == "offer" and given.get("offer_stage"):
        return {"id": q.id, "chosen": [cfg["offer_stages"][given["offer_stage"]]["chip"]], "text": given.get("offer")}
    return {"id": q.id, "chosen": [q.options[0]]}


def _questions_record(questions) -> dict:
    return {"questions": [{"id": q.id, "question": q.question, "fills": q.fills.value, "options": q.options}
                          for q in questions]}


async def _ask_questions(brief: str, mode: str) -> dict:
    """The brief's clarifying questions, if the planner asks any (one reasoner call; V3)."""
    from ctxpack.agent.interpret import interpret

    out = await interpret(brief, mode=mode, allow_question=True)
    return _questions_record(out.result.clarifying_questions)


@app.command("eval")
def eval_cmd(
    reuse: bool = typer.Option(False, "--reuse", help="No new research runs: score the newest saved pack per brief"),
    only: list[str] = typer.Option([], "--only", help="Only this brief id (evals/briefs.yaml); repeatable"),
    recheck: bool = typer.Option(False, "--recheck", help="Re-check claims and the clarifying question again (paid)"),
    yes: bool = typer.Option(False, "--yes", help="Do not wait for Enter before the paid calls"),
) -> None:
    """Score the eval briefs (PRD 14.3) -> evals/results/<date>.json, copied to featured/evals.json (/evals).

    The two flagship packs are always reused. Without --reuse the other briefs are researched first
    (the expected cost is shown and Enter is needed). Claim re-checks are saved and reused unless --recheck.
    """
    import asyncio

    from ctxpack import db
    from ctxpack import evaluation as ev
    from ctxpack.agent.interpret import interpret
    from ctxpack.config import mode_limits, model_for
    from ctxpack.llm.client import cost_usd, tracking
    from ctxpack.schemas.enums import Mode, Requester

    db.init_engine()
    _ready_db()
    cfg = ev.load_briefs()
    targets = cfg["targets"]
    specs = [b for b in cfg["briefs"] if not only or b["id"] in only]
    if not specs:
        console.print(f"{BAD} no brief matches --only {', '.join(only)}")
        raise typer.Exit(1)

    found: dict[str, tuple] = {}
    to_run: list[dict] = []
    for spec in specs:
        got = _eval_pack(spec, reuse)
        if got is not None:
            found[spec["id"]] = got
        elif reuse or spec.get("reuse_pack"):
            console.print(f"[yellow]skip[/yellow] {spec['id']}: no saved pack for \"{spec['brief']}\"", highlight=False)
        else:
            to_run.append(spec)

    # What still costs money, shown before anything is spent
    n = targets["entailment_sample"]
    ent_usd = 2 * cost_usd(model_for("evaluator"), n * 6 * 120 + 3 * 900, n * 70)
    ask_usd = 2 * cost_usd(model_for("reasoner"), 6000, 1500)
    prev = {sid: ev.previous(sid, pack["pack_id"]) for sid, (pack, _) in found.items()}
    need_ent = [s["id"] for s in specs if s["id"] in found and (recheck or not (prev[s["id"]] or {}).get("entailment"))]
    need_ent += [s["id"] for s in to_run]
    asks = lambda spec: any(k in spec.get("expect", {}) for k in ("questions_max", "questions_fill"))  # noqa: E731
    need_ask = [s["id"] for s in specs if s["id"] in found and asks(s)
                and (recheck or not ((prev[s["id"]] or {}).get("clarifying_question") or {}).get("questions"))]
    lines, typ_lo, typ_hi, worst = [], 0.0, 0.0, 0.0
    for spec in to_run:
        lim = mode_limits(spec["mode"])
        cap = lim["apify_usd"] + lim["llm_usd"] + lim["analysis_llm_usd"]
        typ_lo, typ_hi, worst = typ_lo + lim["typical_usd"][0], typ_hi + lim["typical_usd"][1], worst + cap
        lines.append(f"research {spec['id']} ({spec['mode']}): typically ${lim['typical_usd'][0]:.2f}-"
                     f"{lim['typical_usd'][1]:.2f}, hard cap ${cap:.2f}")
    if need_ent:
        lines.append(f"claim re-check ({model_for('evaluator')}, {n} claims each): {len(need_ent)} pack(s), "
                     f"at most ${ent_usd * len(need_ent):.2f}")
    if need_ask:
        lines.append(f"clarifying-questions check ({len(need_ask)} brief(s)): at most ${ask_usd * len(need_ask):.2f}")
    extra = ent_usd * len(need_ent) + ask_usd * len(need_ask)
    console.print("[bold]EVAL[/bold] " + ", ".join(s["id"] for s in specs), highlight=False)
    for line in lines:
        console.print(f"  {line}", highlight=False)
    if lines:
        console.print(f"  [bold]expected ${typ_lo + extra / 2:.2f}-{typ_hi + extra:.2f}, maximum ${worst + extra:.2f}"
                      f"[/bold] (Apify + Anthropic)", highlight=False)
        if not yes and not get_settings().llm_fake:
            typer.prompt("Press Enter to start (Ctrl-C to cancel)", default="", show_default=False)
    else:
        console.print("  nothing to pay for: everything is reused", highlight=False)

    clarifying: dict[str, dict | None] = {sid: (prev[sid] or {}).get("clarifying_question") for sid in found}
    for spec in to_run:
        run = db.create_run(spec["brief"], mode=Mode(spec["mode"]), requester=Requester.cli)

        async def plan(intake=None, edits=None, brief=spec["brief"], mode=spec["mode"], run_id=run.id):
            with tracking(run_id):
                return await interpret(brief, mode=mode, allow_question=True, intake=intake, edits=edits)

        out = asyncio.run(plan())
        clar = _questions_record(out.result.clarifying_questions)
        intake = None
        if out.result.clarifying_questions:
            _print_plan(out)
            console.print("eval answers goal and offer from the brief's answers, the rest with the first chip",
                          highlight=False)
            intake, edits = _intake_from(out.result.clarifying_questions,
                                         [_eval_answer(q, spec.get("answers") or {})
                                          for q in out.result.clarifying_questions])
            out = asyncio.run(plan(intake, edits))
        _print_plan(out)
        db.update_run(run.id, interpretation=out.result.interpretation.model_dump(mode="json"),
                      plan=out.result.plan.model_dump(mode="json"),
                      intake=intake.model_dump(mode="json") if intake else None)
        final = _execute(run.id, spec["brief"])
        if not final.pack_id:
            console.print(f"{BAD} {spec['id']}: run {run.id} ended {final.status.value} without a pack", highlight=False)
            continue
        found[spec["id"]] = (db.get_pack(final.pack_id), final)
        clarifying[spec["id"]] = clar
        prev[spec["id"]] = None

    async def paid_checks() -> dict[str, dict]:
        """Every paid eval call in ONE event loop (the spend tracker's lock belongs to one loop)."""
        ents: dict[str, dict] = {}
        for spec in specs:
            if spec["id"] not in found:
                continue
            pack = found[spec["id"]][0]
            if spec["id"] in need_ask:
                clarifying[spec["id"]] = await _ask_questions(spec["brief"], spec["mode"])
            ent = (prev.get(spec["id"]) or {}).get("entailment")
            if recheck or not ent:
                console.print(f"re-checking {n} claims of {pack['pack_id']} ({spec['id']})...", highlight=False)
                ent = await ev.recheck_claims(pack, n)
            ents[spec["id"]] = ent
        return ents

    with tracking(None) as t:
        ents = asyncio.run(paid_checks())
        eval_usd = t.spent_usd
    scored = [ev.score_brief(spec, found[spec["id"]][0], found[spec["id"]][1], targets, entailment=ents[spec["id"]],
                             clarifying=clarifying.get(spec["id"]),
                             reused=spec["id"] not in {s["id"] for s in to_run})
              for spec in specs if spec["id"] in found]
    if not scored:
        console.print(f"{BAD} nothing to score")
        raise typer.Exit(1)
    if only and (last := ev.latest()):  # keep the other briefs' latest scores
        done = {b["id"] for b in scored}
        scored = [b for b in last["briefs"] if b["id"] not in done and "units" in b] + scored
        order = [s["id"] for s in cfg["briefs"]]
        scored.sort(key=lambda b: order.index(b["id"]) if b["id"] in order else len(order))
    result = ev.build_result(scored, targets, eval_usd)
    path = ev.save(result)
    _print_eval(result)
    console.print(f"\nsaved {path.relative_to(path.parents[2])} and featured/evals.json | eval checks cost "
                  f"${eval_usd:.3f}", highlight=False)


def _print_eval(result: dict) -> None:
    def mark(ok) -> str:
        return "[green]PASS[/green]" if ok else "[red]FAIL[/red]" if ok is False else "[dim]n/a[/dim]"

    rates = {"quote_groundedness", "claim_entailment", "claims_with_evidence", "relevance_rate", "schema_valid",
             "plan_divergence"}

    def show(name: str, value) -> str:
        if value is None:
            return "-"
        if isinstance(value, dict):
            return f"{value.get('tool_calls')} calls, {value.get('finish_reason')}"
        return f"{round(100 * value, 1)}%" if name in rates else str(value)

    for b in result["briefs"]:
        console.print(f"\n[bold]{b['id']}[/bold] {b['pack_id']} ({b['mode']}, grade {b['coverage_grade']}, "
                      f"{b['relevant_posts']} relevant{', thin evidence' if b['thin_evidence'] else ''})",
                      highlight=False)
        for name, m in b["metrics"].items():
            sim = " SIMULATED" if m.get("simulated") else ""
            console.print(f"  {mark(m['pass'])} {name:<22} {show(name, m['value']):>16}  {m['detail']}{sim}",
                          highlight=False)
        for e in b["expectations"]:
            console.print(f"  {mark(e['pass'])} {e['check']:<40} {e['detail']}", highlight=False)
    console.print("\n[bold]HEADLINE[/bold]")
    for name, m in result["headline"].items():
        console.print(f"  {mark(m['pass'])} {name:<22} {show(name, m['value']):>16}  target {m['target']}  {m['detail']}",
                      highlight=False)


@app.command("demo-check")
def demo_check(
    url: str = typer.Option("https://signal-l2w5.onrender.com", help="The public URL"),
    paid: bool = typer.Option(True, "--paid/--no-paid", help="Include the tiny Anthropic call (< $0.001)"),
) -> None:
    """Before the demo: live service, keep-alive, mirror, MCP, accounts, spend, and the security check.

    The real RUN_KEY is compared inside the check and never printed.
    """
    from ctxpack.demo_check import run_all

    checks = run_all(url, paid=paid)
    for c in checks:
        console.print(OK if c.ok else BAD, end=" ")
        console.print(f"{c.name}: {c.detail}", highlight=False, markup=False)
    bad = [c for c in checks if not c.ok]
    console.print("\n[green]ALL GREEN[/green]" if not bad else f"\n[red]{len(bad)} not green[/red]")
    if bad:
        raise typer.Exit(1)


@app.command("actor-check")
def actor_check() -> None:
    """Free health check of every Apify actor in the catalog: deprecated, success rate, usage, last build,
    rating, live prices vs the catalog, and every input our tools send vs the actor's input schema."""
    from ctxpack.actor_check import run

    reports = run()
    mark = {"ok": OK, "warn": "[yellow]![/yellow]", "fail": BAD}
    for r in reports:
        f = r.facts
        success = f"{f['success_30d']:.1%}" if f.get("success_30d") is not None else "-"
        console.print(mark[r.level], end=" ")
        console.print(f"{r.actor_id}  ({r.role})", highlight=False, markup=False, soft_wrap=True)
        if f:
            console.print(f"    success {success} of {f['runs_30d']:,} runs, {f['users_30d'] or 0:,} users (30 d), "
                          f"build {f['last_build'] or '-'}, rating {f['rating'] or '-'} ({f['reviews']}), "
                          f"{r.inputs_checked} inputs checked", highlight=False, markup=False, soft_wrap=True)
        for finding in r.findings:
            console.print(f"    {finding.level.upper()}: {finding.text}", highlight=False, markup=False,
                          soft_wrap=True)
    fails = sum(r.level == "fail" for r in reports)
    warns = sum(r.level == "warn" for r in reports)
    console.print(f"\n{len(reports)} actor slots: {len(reports) - fails - warns} ok, {warns} to watch, "
                  f"{fails} failing")
    if fails:
        raise typer.Exit(1)


@app.command()
def version() -> None:
    """Print the package version."""
    from importlib.metadata import version as pkg_version

    console.print(pkg_version("ctxpack"))


if __name__ == "__main__":
    app()
