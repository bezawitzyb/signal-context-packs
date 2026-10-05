"""Featured packs and examples (guide Step 3.7): the finished pack only, after a fresh privacy check.

featured/<pack_id>.json  - loaded into the database at startup (public: list_packs)
examples/<slug>.json, .md and the skill folder

The pack is copied without cost events (no costs in public files); it never
holds documents or secrets. The privacy check runs first and stops on any
email address, phone number, @handle, profile URL or quote/evidence over
280 characters. The repo is public: nothing is written if a check fails.
"""

from __future__ import annotations

import copy
import io
import json
import zipfile
from pathlib import Path
from typing import Any, Iterator

from ctxpack.collect.cleaning import _EMAIL, _HANDLE, _PHONE_INTL, _PHONE_NATIONAL, _PROFILE_URL, _REDDIT_USER

REPO = Path(__file__).resolve().parents[3]
FEATURED_DIR = REPO / "featured"
EXAMPLES_DIR = REPO / "examples"

CHECKS = [(_EMAIL, "email address"), (_PHONE_INTL, "phone number"), (_PHONE_NATIONAL, "phone number"),
          (_HANDLE, "@handle"), (_PROFILE_URL, "profile URL"), (_REDDIT_USER, "Reddit user name")]
MACHINE_KEYS = {"pack_id", "id", "generated_at", "created_at", "posted_at", "author_hash", "schema_version",
                "date_precision", "seq", "type"}
MAX_QUOTE = 280


def _strings(value: Any, path: str = "") -> Iterator[tuple[str, str]]:
    if isinstance(value, dict):
        for k, v in value.items():
            if k not in MACHINE_KEYS:
                yield from _strings(v, f"{path}.{k}" if path else k)
    elif isinstance(value, list):
        for n, v in enumerate(value):
            yield from _strings(v, f"{path}[{n}]")
    elif isinstance(value, str):
        yield path, value


def privacy_problems(pack: dict) -> list[str]:
    """Everything that must not be published. Empty list = safe to feature."""
    problems = []
    for path, text in _strings(pack):
        for pattern, what in CHECKS:
            if m := pattern.search(text):
                problems.append(f"{path}: {what} ({m.group(0)[:40]})")
    for e in pack.get("evidence", []):
        if len(e["text"]) > MAX_QUOTE:
            problems.append(f"evidence {e['id']}: text over {MAX_QUOTE} characters")
    for path, text in _strings(pack):
        if path.endswith(".text") and ".quotes[" in path and len(text) > MAX_QUOTE:
            problems.append(f"{path}: quote over {MAX_QUOTE} characters")
    return problems


def public_copy(pack: dict) -> dict:
    """The finished pack without cost events."""
    p = copy.deepcopy(pack)
    p["events"] = [e for e in p.get("events", []) if e.get("type") != "cost"]
    return p


def feature(pack: dict, featured_dir: Path = FEATURED_DIR, examples_dir: Path = EXAMPLES_DIR) -> dict[str, Path]:
    """Write the featured pack and the examples. Raises ValueError (and writes nothing) on any privacy problem."""
    from ctxpack.exports.common import slug
    from ctxpack.exports.markdown import to_markdown
    from ctxpack.exports.skill import skill_zip
    from ctxpack.schemas.pack import ContextPack

    p = public_copy(pack)
    problems = privacy_problems(p)
    if problems:
        raise ValueError("privacy check failed - nothing written:\n" + "\n".join(problems[:30]))
    p = ContextPack.model_validate(p).model_dump(mode="json")
    i = p["brief"]["interpreted"]
    name = slug(i["topic"], i["market"], max_chars=48)
    featured_dir.mkdir(parents=True, exist_ok=True)
    examples_dir.mkdir(parents=True, exist_ok=True)
    text = json.dumps(p, ensure_ascii=False, indent=1)
    paths = {"featured": featured_dir / f"{p['pack_id']}.json", "example_json": examples_dir / f"{name}.json",
             "example_md": examples_dir / f"{name}.md"}
    paths["featured"].write_text(text, encoding="utf-8")
    paths["example_json"].write_text(text, encoding="utf-8")
    paths["example_md"].write_text(to_markdown(p), encoding="utf-8")
    _, data = skill_zip(p)
    with zipfile.ZipFile(io.BytesIO(data)) as z:
        z.extractall(examples_dir)
        paths["skill"] = examples_dir / z.namelist()[0].split("/")[0]
    return paths
