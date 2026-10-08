"""Static mirror of the featured packs (guide B15): demo insurance on GitHub Pages.

Builds the same web app in read-only mode (VITE_MIRROR=1) and writes the data it reads:

  mirror/data/packs.json                         the featured list (same shape as GET /api/v1/packs)
  mirror/data/packs/<id>/context_pack.json      the pack (as published in featured/)
  mirror/data/packs/<id>/brief.md, prompt_block.txt, digest.json, content_calendar.csv, skill.zip
  mirror/data/evals.json                         eval results + human ratings (as GET /api/v1/evals)
  mirror/404.html                                the app again, so deep links work on GitHub Pages

Only finished, featured packs (already privacy-checked, no cost events) go in; never documents,
secrets or keys. Free: no database, no network, no paid API.

Run from backend/: uv run python -m scripts.build_mirror [--base /signal-context-packs/] [--out ../mirror]
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
from pathlib import Path

import typer

from ctxpack.config import REPO_DIR

FEATURED = REPO_DIR / "featured"
FRONTEND = REPO_DIR / "frontend"


def featured_packs() -> list[dict]:
    """featured/pk_*.json (evals.json and evals_human.json are not packs)."""
    from ctxpack.schemas.migrate import current

    return [current(json.loads(p.read_text(encoding="utf-8"))) for p in sorted(FEATURED.glob("*.json"))
            if not p.stem.startswith("evals")]


def card(p: dict) -> dict:
    """One entry of the featured list, as the API's service.featured() builds it."""
    i = p["brief"]["interpreted"]
    return {"pack_id": p["pack_id"], "brief": p["brief"]["text"], "topic": i["topic"], "market": i["market"],
            "audience": i["audience"], "mode": p["mode"], "generated_at": p["generated_at"],
            "coverage_grade": p["snapshot"]["coverage_grade"], "thin_evidence": p["coverage"]["thin_evidence"]}


def write_data(out: Path, packs: list[dict]) -> list[str]:
    """Everything the mirror reads, under out/data. Returns the pack ids written."""
    from ctxpack.evaluation import published
    from ctxpack.exports import write_exports
    from ctxpack.exports.featured import privacy_problems

    data = out / "data"
    for p in packs:
        problems = privacy_problems(p)
        if problems:
            raise SystemExit(f"privacy check failed for {p['pack_id']}: {problems[:3]}")
        paths = write_exports(p, data / "packs" / p["pack_id"])
        paths["skill"].rename(paths["skill"].with_name("skill.zip"))
    (data / "packs.json").write_text(json.dumps([card(p) for p in packs], ensure_ascii=False, indent=1),
                                     encoding="utf-8")
    (data / "evals.json").write_text(json.dumps(published(), ensure_ascii=False, indent=1), encoding="utf-8")
    return [p["pack_id"] for p in packs]


def build_app(out: Path, base: str) -> None:
    env = {**os.environ, "VITE_MIRROR": "1"}
    subprocess.run(["npx", "vite", "build", "--base", base, "--outDir", str(out), "--emptyOutDir"],
                   cwd=FRONTEND, env=env, check=True)
    shutil.copyfile(out / "index.html", out / "404.html")   # GitHub Pages: deep links load the app
    (out / ".nojekyll").write_text("", encoding="utf-8")


def main(base: str = typer.Option("/signal-context-packs/", help="URL path the mirror is served from"),
         out: Path = typer.Option(REPO_DIR / "mirror", help="Output folder (not committed)")) -> None:
    out = out.resolve()
    build_app(out, base)
    ids = write_data(out, featured_packs())
    print(f"mirror built in {out} with {len(ids)} featured pack(s): {', '.join(ids)}")


if __name__ == "__main__":
    typer.run(main)
