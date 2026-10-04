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
            comments = src.get("comments")
            rows = [
                ("actor", actor(src["actor"])),
                ("fallback", actor(src.get("fallback"))),
                ("comments", f"{actor(comments['actor'])}, fallback {actor(comments.get('fallback'))}" if comments else "-"),
                ("limits", ", ".join(src["actor"]["limit_inputs"])),
            ]
        for label, value in rows:
            console.print(f"  {label:<9}{value}", soft_wrap=False, highlight=False)


@app.command()
def tool(
    name: str = typer.Argument(..., help="search_reddit, search_tiktok, search_youtube, search_instagram, "
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
                       brief=BriefContext(topic=topic or " ".join(targets), market=market, languages=[language]),
                       store=lambda docs, replaced: stored.extend(docs))
    args: dict = {"reason": "manual CLI test"}
    if name in ("search_reddit", "search_tiktok"):
        args |= {"target": targets[0], "limit": limit}
    elif name == "search_youtube":
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


def _print_plan(out) -> None:
    """Interpretation, then the question or the plan, then the estimate."""
    res, est = out.result, out.estimate
    i = res.interpretation
    assumed = {a.value for a in i.assumed}
    console.print("[bold]Here's what I understood[/bold]")
    for name in ("topic", "market", "languages", "audience", "category", "compliance_category",
                 "competitors", "intent", "time_window_days"):
        value = getattr(i, name)
        value = ", ".join(value) if isinstance(value, list) else getattr(value, "value", value)
        tag = " [yellow](assumed)[/yellow]" if name in assumed else ""
        console.print(f"  {name:<20}{value or '-'}{tag}", highlight=False)
    if res.clarifying_question:
        q = res.clarifying_question
        console.print(f"\n[bold]One question:[/bold] {q.question}")
        for n, option in enumerate(q.options, 1):
            console.print(f"  {n}. {option}")
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


@app.command()
def plan(
    brief: str = typer.Argument(..., help='The brief, e.g. "Gen Z and meal prep"'),
    mode: str = typer.Option("quick", help="quick or standard (for the estimate)"),
    window: int = typer.Option(0, help="Time window in days (default from modes.yaml)"),
    agent: bool = typer.Option(False, "--agent", help="Act like an agent: never a clarifying question"),
    answer: str = typer.Option("", help="Answer to the clarifying question (asked once)"),
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

    async def go(clarification=None):
        return await interpret(brief, mode=mode, window_days=window or None, allow_question=not agent,
                               clarification=clarification)

    with tracking() as t:
        out = asyncio.run(go())
        q = out.result.clarifying_question
        if q and answer:
            out = asyncio.run(go((q.question, answer)))
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
) -> None:
    """Plan -> show it and wait for Enter -> the agent loop, printed live -> counters, sources, cost."""
    import asyncio
    import os
    import signal
    import time

    from ctxpack import db, orchestrator
    from ctxpack.agent.interpret import interpret
    from ctxpack.collect import loop
    from ctxpack.llm.client import tracking
    from ctxpack.schemas.enums import Mode, Requester, RunStatus

    if mode not in ("quick", "standard"):
        console.print(f"{BAD} mode must be quick or standard")
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
    db.create_tables()

    run = db.create_run(brief, mode=Mode(mode), requester=Requester.cli)
    if brand_voice:
        db.update_run(run.id, brand_voice=brand_voice[:200])

    async def plan(clarification=None):
        with tracking(run.id):
            return await interpret(brief, mode=mode, window_days=window or None, allow_question=not auto_approve,
                                   clarification=clarification)

    out = asyncio.run(plan())
    if out.result.clarifying_question:
        _print_plan(out)
        q = out.result.clarifying_question
        answer = typer.prompt("Your answer (a number or your own words)")
        if answer.strip().isdigit() and 1 <= int(answer) <= len(q.options):
            answer = q.options[int(answer) - 1]
        out = asyncio.run(plan((q.question, answer)))
    _print_plan(out)
    db.update_run(run.id, interpretation=out.result.interpretation.model_dump(mode="json"),
                  plan=out.result.plan.model_dump(mode="json"))
    if not auto_approve:
        typer.prompt("\nPress Enter to start (Ctrl-C to cancel)", default="", show_default=False)

    orchestrator.enqueue(run.id)
    claimed = db.claim_next_run()
    if claimed is None or claimed.id != run.id:
        console.print(f"{BAD} another run is waiting in the queue; run {run.id} stays queued for the worker")
        raise typer.Exit(1)

    async def collect(run_id: str) -> None:
        state = orchestrator.loop_state(run_id, no_apify=no_apify,
                                        apify_usd_cap=apify_max if apify_max >= 0 else None)
        await loop.run_loop(state)
        if record:
            path = loop.save_transcript(brief, state)
            console.print(f"transcript saved: {path}")

    async def go() -> None:
        signal_loop = asyncio.get_running_loop()
        signal_loop.add_signal_handler(signal.SIGINT, lambda: (
            console.print("[yellow]Stopping - packaging what was collected...[/yellow]"),
            orchestrator.request_stop(run.id)))
        task = asyncio.create_task(orchestrator.run_pipeline(run.id, collect=collect))
        last = 0
        while True:
            done = task.done()
            for e in db.get_events(run.id, after_seq=last):
                last = e.seq
                if line := _event_line(e):
                    console.print(line, highlight=False)
            if done:
                break
            await asyncio.sleep(0.5)
        await task

    started = time.monotonic()
    asyncio.run(go())
    final = db.get_run(run.id)
    _print_summary(final)
    console.print(f"took {time.monotonic() - started:.0f} s")
    if final.status == RunStatus.failed:
        raise typer.Exit(1)


@app.command()
def overlap(run_ids: list[str] = typer.Argument(..., help="Two or more run ids")) -> None:
    """How much the runs' source units overlap (eval: briefs share < 50%)."""
    from ctxpack import db
    from ctxpack.orchestrator import source_units, units_overlap

    db.init_engine()
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


@app.command()
def version() -> None:
    """Print the package version."""
    from importlib.metadata import version as pkg_version

    console.print(pkg_version("ctxpack"))


if __name__ == "__main__":
    app()
