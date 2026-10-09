"""Markets and languages (change V2, PRD FR-A2b). Code, not the model, decides the final geography
and languages: regions expand to countries, a place named in the brief is never "global", and the
languages come from the markets' official languages (weighted) plus English, capped per mode.
Geography lives in config/markets.yaml; the supported languages and caps in config/modes.yaml.
"""

from __future__ import annotations

import re
from typing import Any

from ctxpack.config import load_yaml

GLOBAL = "global"


def _geo() -> dict[str, Any]:
    return load_yaml("markets")


def _lang_cfg() -> dict[str, Any]:
    return load_yaml("modes")["languages"]


def language_name(code: str) -> str:
    return _lang_cfg()["supported"].get(code, code)


def _named(text: str, names: list[str]) -> bool:
    low = f" {text.casefold()} "
    return any(re.search(rf"(?<![\w-]){re.escape(n)}(?![\w-])", low) for n in names)


def places_in(brief: str) -> dict[str, list[str]]:
    """Regions and countries the brief names: {"regions": [...], "countries": [...]}."""
    g = _geo()
    return {"regions": [code for code, r in g["regions"].items() if _named(brief, r["names"])],
            "countries": [code for code, c in g["countries"].items() if _named(brief, c["names"])]}


def normalise(markets: list[dict], brief: str) -> list[dict]:
    """Clean codes, fill a region's countries, and never leave "global" when the brief names a place."""
    g = _geo()
    out: list[dict] = []
    for m in markets:
        code = str(m.get("code", "")).strip()
        lower = code.lower()
        if lower in g["regions"]:
            countries = [c.upper() for c in m.get("countries") or []] or list(g["regions"][lower]["countries"])
            out.append({"code": lower, "countries": countries, "weight": float(m.get("weight") or 1.0),
                        "assumed": bool(m.get("assumed"))})
        elif lower == GLOBAL or not code:
            out.append({"code": GLOBAL, "countries": [], "weight": float(m.get("weight") or 1.0),
                        "assumed": bool(m.get("assumed"))})
        else:
            out.append({"code": code.upper(), "countries": [code.upper()], "weight": float(m.get("weight") or 1.0),
                        "assumed": bool(m.get("assumed"))})
    places = places_in(brief)
    named = places["regions"] or places["countries"]
    if named and all(m["code"] == GLOBAL for m in out):  # "...in Europe" never becomes global
        out = [{"code": r, "countries": list(g["regions"][r]["countries"]), "weight": 1.0, "assumed": False}
               for r in places["regions"]]
        loose = [c for c in places["countries"] if not any(c in m["countries"] for m in out)]
        out += [{"code": c, "countries": [c], "weight": 1.0, "assumed": False} for c in loose]
        for m in out:  # "Europe incl. Germany and Poland": the named countries lead their own region
            if m["code"] in g["regions"]:
                first = [c for c in places["countries"] if c in m["countries"]]
                m["countries"] = first + [c for c in m["countries"] if c not in first]
    if not out:
        out = [{"code": GLOBAL, "countries": [], "weight": 1.0, "assumed": True}]
    total = sum(m["weight"] for m in out) or 1.0
    for m in out:
        m["weight"] = round(m["weight"] / total, 3)
    return out


def label(markets: list[dict]) -> str:
    """Short market label for display and prompts: "NL", "EU (DE, PL, SE, +9)", "global"."""
    parts = []
    for m in markets:
        if m["code"] == GLOBAL:
            parts.append(GLOBAL)
        elif m["code"] in _geo()["regions"]:
            shown = m["countries"][:4]
            more = len(m["countries"]) - len(shown)
            parts.append(f"{m['code'].upper()} ({', '.join(shown)}{f', +{more}' if more > 0 else ''})")
        else:
            parts.append(m["code"])
    return " + ".join(parts)


def countries(markets: list[dict]) -> list[str]:
    """Every country in the markets, highest weight first (for Trends and locale choices)."""
    seen: list[str] = []
    for m in sorted(markets, key=lambda m: -m["weight"]):
        seen += [c for c in m["countries"] if c not in seen]
    return seen


def primary_country(markets: list[dict]) -> str:
    """The country to use when only one fits (Trends geo); "" for global."""
    found = countries(markets)
    return found[0] if found else ""


def choose_languages(markets: list[dict], model_languages: list[str], mode: str,
                     named_countries: list[str] = ()) -> tuple[list[str], list[dict]]:
    """(chosen languages, excluded [{language, reason}]). Weighted by the markets' official languages;
    countries the brief names count extra and their languages are never dropped as "too small".
    English joins global and multi-country briefs (lingua franca); a single-country brief gets it only when it
    is that country's language or the planner chose it (owner's decision 2026-10-09: German briefs stay German,
    no false "English voices missing" blind spot)."""
    cfg = _lang_cfg()
    g = _geo()
    supported = cfg["supported"]
    cap = cfg["max_per_mode"][mode]
    score: dict[str, float] = {}
    def add(country: str, share: float) -> None:
        for n, lang in enumerate(g["countries"].get(country, {}).get("languages", [])):
            score[lang] = score.get(lang, 0.0) + share / (n + 1)  # a country's first language counts most

    for m in markets:
        for c in m["countries"]:
            add(c, m["weight"] / len(m["countries"]))
    keep = set(model_languages)
    for c in named_countries:
        add(c, cfg["named_country_weight"])
        keep.update(g["countries"].get(c, {}).get("languages", [])[:1])
    for lang in model_languages:
        score[lang] = score.get(lang, 0.0) + cfg["model_language_bonus"]
    countries_all = {c for m in markets for c in m["countries"]}
    auto_english = len(countries_all) != 1 or "en" in model_languages
    if auto_english:
        score["en"] = max(score.get("en", 0.0), cfg["english_weight"])
    ranked = sorted(score, key=lambda k: (-score[k], k))
    top_score = max(score.values())
    chosen: list[str] = []
    excluded: list[dict] = []
    for lang in ranked:
        if lang not in supported:
            excluded.append({"language": lang, "reason": "not supported yet"})
        elif lang != "en" and lang not in keep and score[lang] / top_score < cfg["min_share_of_top"]:
            excluded.append({"language": lang, "reason": "only a small share of the chosen markets"})
        elif len(chosen) < cap - (0 if "en" in chosen or lang == "en" or not auto_english else 1):  # English seat
            chosen.append(lang)
        else:
            excluded.append({"language": lang, "reason": (
                f"left out to keep the run fast ({mode.capitalize()} covers up to {cap} languages)"
                + ("; choose Standard to include it" if mode == "quick" else
                   "; it has a smaller share of the chosen markets than the languages kept"))})
    if "en" not in chosen and auto_english:
        chosen.append("en")
    # local languages first, English last unless it leads (e.g. UK, US, global)
    top = max(score[c] for c in chosen)
    chosen.sort(key=lambda k: (k == "en" and score[k] < top, -score[k], k))
    return chosen, excluded
