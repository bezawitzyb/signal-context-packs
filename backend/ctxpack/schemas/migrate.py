"""Schema migrations for stored packs: every older version is read and turned into the current one.

1.0 -> 1.1 (changes V1-V10, one version for all of them; each step adds its part here). The steps are
idempotent and also run on packs saved as 1.1 before a later step existed:
  V2  brief.interpreted.market (one ISO code or "global") -> markets[] (+ market label, languages_excluded);
      done by Interpretation's own validator, so runs saved before V2 read the same way.
  V3  brief.intake (empty) and evidence[].role ("unknown"): model defaults, nothing to convert.
  V4  motivations of kind "pain" -> pain_points[] (MOT-xx -> PAIN-xx everywhere the id appears);
      relations, sections_meta and performance_takeaways start empty.
  V5  white_space[] and the scored opportunities -> one opportunities[] (status "signal", confidence at
      most emerging, "not checked" for existing solutions); WSP-xx renamed to the new OPP ids.
Packs are never written back in an older version.
"""

from __future__ import annotations

import copy
import re
from typing import Any


def needs_migration(pack: dict[str, Any]) -> bool:
    from ctxpack.schemas.pack import SCHEMA_VERSION

    return pack.get("schema_version") != SCHEMA_VERSION or "pain_points" not in pack or "white_space" in pack


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
    if "white_space" in out:
        out = _opportunities_v5(out)
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


LEVELS = ["speculative", "emerging", "moderate", "strong"]
_WSP_KIND = {"unanswered_question": "content_idea", "unmet_need": "product_idea", "unserved_segment": "positioning"}
NOT_CHECKED = "not checked: made before the existing-solution search"


def cap_emerging(conf: dict) -> dict:
    """A signal is never shown above emerging."""
    label = conf.get("label", "speculative")
    return {**conf, "label": label if LEVELS.index(label) <= 1 else "emerging"}


def _opportunities_v5(pack: dict[str, Any]) -> dict[str, Any]:
    """V5: white space and the scored opportunities become one list of opportunities ("signal")."""
    items = {it["id"]: it for name in ("pain_points", "motivations") for it in pack.get(name, [])}
    out: list[dict] = []
    for o in pack.get("opportunities", []):
        base = next((items[b] for b in o.get("builds_on", []) if b in items), None)
        strength = (base or {}).get("strength", {})
        out.append({"id": o["id"], "type": "opportunity",
                    "opportunity": f"{o.get('title', '').strip()}: {o.get('description', '').strip()}".strip(": "),
                    "kind": "product_idea", "status": "signal",
                    "confidence": cap_emerging((base or {}).get("confidence") or {"score": 0.0, "label": "speculative"}),
                    "distinct_authors": strength.get("distinct_authors", 0), "communities": strength.get("platforms", []),
                    "existing_solutions": [], "search_note": NOT_CHECKED, "evidence_ids": o.get("evidence_ids", [])[:5],
                    "builds_on": o.get("builds_on", []), "related_ids": [], "cluster_id": o.get("cluster_id"),
                    "score": o.get("score"), "components": o.get("components")})
    mapping: dict[str, str] = {}
    for w in pack.get("white_space", []):
        new_id = f"OPP-{len(out) + 1:02d}"
        mapping[w["id"]] = new_id
        out.append({"id": new_id, "type": "opportunity", "opportunity": w["claim"],
                    "kind": _WSP_KIND.get(w.get("kind"), "content_idea"), "status": "signal",
                    "confidence": cap_emerging(w["confidence"]),
                    "distinct_authors": w.get("strength", {}).get("distinct_authors", 0),
                    "communities": w.get("strength", {}).get("platforms", []), "existing_solutions": [],
                    "search_note": NOT_CHECKED, "evidence_ids": w.get("evidence_ids", [])[:5], "builds_on": [],
                    "related_ids": w.get("related_ids", []), "cluster_id": w.get("cluster_id")})
    pack = {k: v for k, v in pack.items() if k != "white_space"}
    pack["opportunities"] = out
    for b in pack.get("blind_spots", []):  # the content-bar line named the old section
        b["text"] = re.sub(r"\bwhite_space (\d+ of \d+)", r"unmet needs \1", b["text"])
    meta = dict(pack.get("sections_meta") or {})
    if "white_space" in meta:
        meta["opportunities"] = meta.pop("white_space")
        pack["sections_meta"] = meta
    if pack.get("snapshot", {}).get("top_opportunity") is None and out:
        pack.setdefault("snapshot", {})["top_opportunity"] = {"item_id": out[0]["id"], "text": out[0]["opportunity"]}
    return rename_ids(pack, mapping)


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
