"""Schema migrations for stored packs: every older version is read and turned into the current one.

1.0 -> 1.1 (changes V1-V10, one version for all of them; each step adds its part here). The steps are
idempotent and also run on packs saved as 1.1 before a later step existed:
  V2  brief.interpreted.market (one ISO code or "global") -> markets[] (+ market label, languages_excluded);
      done by Interpretation's own validator, so runs saved before V2 read the same way.
  V3  brief.intake (empty) and evidence[].role ("unknown"): model defaults, nothing to convert.
  V4  motivations of kind "pain" -> pain_points[] (MOT-xx -> PAIN-xx everywhere the id appears);
      relations, sections_meta and performance_takeaways start empty.
Packs are never written back in an older version.
"""

from __future__ import annotations

import copy
import re
from typing import Any


def needs_migration(pack: dict[str, Any]) -> bool:
    from ctxpack.schemas.pack import SCHEMA_VERSION

    return pack.get("schema_version") != SCHEMA_VERSION or "pain_points" not in pack


def migrate(pack: dict[str, Any]) -> dict[str, Any]:
    """A pack dict in any known version -> the current version (a copy; the input is not changed)."""
    from ctxpack.schemas.pack import OLDER_VERSIONS, SCHEMA_VERSION

    version = pack.get("schema_version")
    if version not in OLDER_VERSIONS + (SCHEMA_VERSION,) or not needs_migration(pack):
        return pack
    out = copy.deepcopy(pack)
    out["schema_version"] = SCHEMA_VERSION
    if "pain_points" not in out:
        out = _move_pains(out)
    return out


def migrate_1_0_to_1_1(pack: dict[str, Any]) -> dict[str, Any]:
    return migrate(pack)


def _move_pains(pack: dict[str, Any]) -> dict[str, Any]:
    """V4: pain motivations become pain points; their ids are renamed wherever they are referenced."""
    mots = pack.get("motivations") or []
    pains = [m for m in mots if m.get("kind") == "pain"]
    pack["motivations"] = [m for m in mots if m.get("kind") != "pain"]
    mapping = {m["id"]: f"PAIN-{n:02d}" for n, m in enumerate(pains, 1)}
    pack["pain_points"] = [{**{k: v for k, v in m.items() if k != "kind"}, "type": "pain_point"} for m in pains]
    return rename_ids(pack, mapping) if mapping else pack


def rename_ids(value: Any, mapping: dict[str, str]) -> Any:
    """Every exact id, and every id inside text (e.g. "[MOT-02]" in the digest), renamed."""
    if not mapping:
        return value
    pattern = re.compile(r"(?<![\w-])(" + "|".join(map(re.escape, mapping)) + r")(?![\w-])")

    def walk(v: Any) -> Any:
        if isinstance(v, dict):
            return {k: walk(x) for k, x in v.items()}
        if isinstance(v, list):
            return [walk(x) for x in v]
        if isinstance(v, str):
            return mapping.get(v) or pattern.sub(lambda m: mapping[m.group(1)], v)
        return v

    return walk(value)


def current(pack: dict[str, Any]) -> dict[str, Any]:
    """A stored pack as the current version, fully validated (for raw dicts read from the database)."""
    from ctxpack.schemas.pack import ContextPack

    if not needs_migration(pack):
        return pack
    return ContextPack.model_validate(pack).model_dump(mode="json")
