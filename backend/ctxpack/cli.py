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
def version() -> None:
    """Print the package version."""
    from importlib.metadata import version as pkg_version

    console.print(pkg_version("ctxpack"))


if __name__ == "__main__":
    app()
