"""Pack exports: Markdown, prompt block, skill, views."""

from __future__ import annotations

import json
from pathlib import Path


def write_exports(pack: dict, out_dir: Path) -> dict[str, Path]:
    """Every export of one pack into out_dir (UTF-8): context_pack.json, digest.json, brief.md,
    prompt_block.txt and the skill zip. Returns {kind: path}."""
    from ctxpack.exports.markdown import to_markdown
    from ctxpack.exports.prompt_block import to_prompt_block
    from ctxpack.exports.skill import skill_zip
    from ctxpack.exports.views import digest_view

    out_dir.mkdir(parents=True, exist_ok=True)
    paths = {"json": out_dir / "context_pack.json", "digest": out_dir / "digest.json",
             "markdown": out_dir / "brief.md", "prompt_block": out_dir / "prompt_block.txt"}
    paths["json"].write_text(json.dumps(pack, ensure_ascii=False, indent=1, default=str), encoding="utf-8")
    paths["digest"].write_text(json.dumps(digest_view(pack), ensure_ascii=False, indent=1, default=str),
                               encoding="utf-8")
    paths["markdown"].write_text(to_markdown(pack), encoding="utf-8")
    paths["prompt_block"].write_text(to_prompt_block(pack), encoding="utf-8")
    for old in out_dir.glob("*.zip"):  # a renamed skill must not leave its old zip behind
        old.unlink()
    name, data = skill_zip(pack)
    paths["skill"] = out_dir / name
    paths["skill"].write_bytes(data)
    return paths
