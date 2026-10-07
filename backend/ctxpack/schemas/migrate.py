"""Schema migrations for stored packs: every older version is read and turned into the current one.

1.0 -> 1.1 (changes V1-V10, one version for all of them; each step adds its part here):
  V2  brief.interpreted.market (one ISO code or "global") -> markets[] (+ market label, languages_excluded);
      done by Interpretation's own validator, so runs saved before V2 read the same way.
  V3  brief.intake (empty) and evidence[].role ("unknown"): model defaults, nothing to convert.
Packs are never written back in an older version.
"""

from __future__ import annotations

from typing import Any


def migrate(pack: dict[str, Any]) -> dict[str, Any]:
    """A pack dict in any known version -> the current version (a copy; the input is not changed)."""
    from ctxpack.schemas.pack import OLDER_VERSIONS, SCHEMA_VERSION

    version = pack.get("schema_version")
    if version == SCHEMA_VERSION or version not in OLDER_VERSIONS:
        return pack
    out = dict(pack)
    if version == "1.0":
        out = migrate_1_0_to_1_1(out)
    return out


def migrate_1_0_to_1_1(pack: dict[str, Any]) -> dict[str, Any]:
    out = dict(pack)
    out["schema_version"] = "1.1"
    # V2: interpretation.market -> markets[] happens in Interpretation's validator (no change needed here).
    return out


def current(pack: dict[str, Any]) -> dict[str, Any]:
    """A stored pack as the current version, fully validated (for raw dicts read from the database)."""
    from ctxpack.schemas.pack import SCHEMA_VERSION, ContextPack

    if pack.get("schema_version") == SCHEMA_VERSION:
        return pack
    return ContextPack.model_validate(pack).model_dump(mode="json")
