"""Brand-perception numbers (change V12), all in code from extracted brand mentions - no model writes a number.

A post belongs to the user's brand when one of its extracted brand mentions matches an alias of the brand
(case and spacing ignored; a mention containing the alias counts, so "Lidl Deluxe range" matches "Lidl
Deluxe"). The parent brand is matched only on mentions that are not the user's brand. A post is "prompted"
when the search that found it named the brand (its source unit contains an alias), else "unprompted":
people bringing the brand up unasked, the awareness signal. Short-form posts are never counted.
"""

from __future__ import annotations

from collections import Counter
from typing import Any

from ctxpack.analysis.metrics import author_key
from ctxpack.config import load_yaml

STANCES = ("positive", "negative", "mixed", "neutral")
RELATIONS = ("same_as_parent", "part_of_parent", "distinct", "unclear")


def _norm(text: str) -> str:
    return " ".join(str(text).casefold().split())


def matches(name: str, aliases: list[str]) -> bool:
    """A mention names the brand when it equals or contains one of its aliases (case and spacing ignored)."""
    n = _norm(name)
    return any(a and _norm(a) in n for a in aliases)


def mentions_of(doc: Any, aliases: list[str], exclude: list[str] = ()) -> list[dict]:
    """The doc's extracted mentions of the brand (never a mention of `exclude`, e.g. the user's brand)."""
    out = []
    for m in (doc.extraction or {}).get("brand_mentions") or []:
        if matches(m.get("name", ""), aliases) and not (exclude and matches(m.get("name", ""), exclude)):
            out.append(m)
    return out


def prompted(doc: Any, aliases: list[str]) -> bool:
    """Found by a search that named the brand: the source unit (platform:query or target) contains an alias."""
    unit = _norm(doc.source_unit or "")
    return any(a and _norm(a) in unit for a in aliases)


def _shares(values: list[str], keys: tuple[str, ...], key_name: str) -> list[dict]:
    counts = Counter(v for v in values if v in keys)
    total = sum(counts.values())
    return [{key_name: k, "share": round(counts[k] / total, 3)} for k in keys if counts[k]] if total else []


def aspect_words(aspect: str | None) -> list[str]:
    """One aspect per item: the model sometimes lists several in one ("scones, quality, taste")."""
    return [a for a in (_norm(x) for x in re_split(aspect or "")) if a]


def re_split(text: str) -> list[str]:
    return [x.strip() for x in text.replace(";", ",").split(",")]


def _aspects(mentions: list[dict], stance: str, most: int) -> list[str]:
    counts = Counter(a for m in mentions if m.get("stance") == stance for a in aspect_words(m.get("aspect")))
    return [a for a, _ in counts.most_common(most)]


def stats(docs: list[Any], aliases: list[str], name: str, *, exclude: list[str] = (), is_parent: bool = False,
          parent: list[str] = ()) -> tuple[dict, list[Any]]:
    """(BrandStats dict, the brand's member docs) for one brand over the relevant, counted docs."""
    cfg = load_yaml("scoring")["brand"]
    counted = [d for d in docs if d.is_relevant and not d.short_form]
    members = [d for d in counted if mentions_of(d, aliases, exclude)]
    ments = [m for d in members for m in mentions_of(d, aliases, exclude)]
    unprompted = [d for d in counted if not prompted(d, aliases)]
    branded = [d for d in unprompted if (d.extraction or {}).get("brand_mentions")]
    mine = [d for d in branded if mentions_of(d, aliases, exclude)]
    with_parent = [d for d in members if parent and mentions_of(d, parent, aliases)]
    out = {
        "name": name, "is_parent": is_parent, "mentions": len(members),
        "unprompted": len([d for d in members if not prompted(d, aliases)]),
        "share_of_voice": round(len(mine) / len(branded), 3) if branded else None,
        "distinct_authors": len({author_key(d) for d in members}),
        "platforms": sorted({str(d.platform) for d in members}),
        "stance_mix": _shares([m.get("stance", "neutral") for m in ments], STANCES, "stance"),
        "relation_mix": [] if is_parent else _shares([m.get("relation") for m in ments if m.get("relation")],
                                                     RELATIONS, "relation"),
        "with_parent": len(with_parent),
        "aspects_praised": _aspects(ments, "positive", cfg["aspects_max"]),
        "aspects_criticised": _aspects(ments, "negative", cfg["aspects_max"]),
    }
    return out, members


def bases(members: list[Any], aliases: list[str]) -> dict[str, list[Any]]:
    """The groups of the brand's posts a finding may rest on (the writer picks one; counts come from it):
    all, by stance, by aspect and stance, and by relation to the parent."""
    groups: dict[str, list[Any]] = {"all": list(members)}
    for d in members:
        for m in mentions_of(d, aliases):
            keys = [f"stance:{m.get('stance', 'neutral')}"]
            keys += [f"aspect:{a}:{m.get('stance', 'neutral')}" for a in aspect_words(m.get("aspect"))]
            if m.get("relation"):
                keys.append(f"relation:{m['relation']}")
            for k in keys:
                if d not in groups.setdefault(k, []):
                    groups[k].append(d)
    return groups


# Which bases a finding of each kind may rest on (V12): a differentiation claim counts only posts that relate
# the brand to its parent, praise only positive posts, criticism only negative or mixed ones.
KIND_BASES = {"perception": ("all", "stance:", "aspect:"), "awareness": ("all",),
              "praise": ("stance:positive", "aspect:"), "criticism": ("stance:negative", "stance:mixed", "aspect:"),
              "differentiation": ("relation:",)}


def basis_fits(kind: str, basis: str) -> bool:
    """True when the basis can carry a finding of this kind (aspect bases must match praise / criticism)."""
    if not any(basis.startswith(p) for p in KIND_BASES.get(kind, ())):
        return False
    if basis.startswith("aspect:") and kind in ("praise", "criticism"):
        stance = basis.rsplit(":", 1)[-1]
        return stance == "positive" if kind == "praise" else stance in ("negative", "mixed")
    return True
