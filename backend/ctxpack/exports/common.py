"""Shared helpers for exports: token estimates, safe inline text, badges."""

from __future__ import annotations

import re

from ctxpack.config import load_yaml


# Plain words every export carries (commercial messaging; not in the pack itself).
DISCLAIMER = ("AI-assisted analysis of public online conversations; it may contain errors. "
              "Compliance flags are not legal advice.")
HOOKS_NOTE = ("Drafts written by AI from the research. Review before use; items marked CHECK WITH LEGAL "
              "need sign-off.")


def privacy_line() -> str:
    from ctxpack.config import get_settings

    return f"Collected posts are deleted after {get_settings().retention_days} days. Author names are never stored."


def cfg() -> dict:
    return load_yaml("modes")["exports"]


def tokens(text: str) -> int:
    """Conservative token estimate (no API call): characters / chars_per_token."""
    return int(len(text) / cfg()["chars_per_token"]) + 1


def inline(text: str | None) -> str:
    """One line, no angle brackets (no XML-like tags from scraped text in skills or prompts)."""
    text = re.sub(r"\s+", " ", text or "").strip()
    return text.replace("<", "‹").replace(">", "›")


def cell(text: str | None) -> str:
    """Safe Markdown table cell."""
    return inline(text).replace("|", "\\|")


def badge(item: dict) -> str:
    """Confidence in words, never colour-only: "moderate, 6 of 225 posts, observed"."""
    c = item.get("confidence") or {}
    n = item.get("counts") or {}
    parts = [c.get("label", "")]
    if n:
        parts.append(f"{n['matching']} of {n['of_total']} posts")
    if item.get("claim_type"):
        parts.append(item["claim_type"])
    if item.get("safe_to_assert"):
        parts.append("safe to state")
    return ", ".join(p for p in parts if p)


def slug(*words: str, max_chars: int = 64) -> str:
    """lowercase-hyphen slug: letters and numbers only (accents dropped), at most max_chars."""
    import unicodedata

    text = unicodedata.normalize("NFKD", " ".join(words)).encode("ascii", "ignore").decode().lower()
    out = re.sub(r"[^a-z0-9]+", "-", text).strip("-")
    for reserved in ("anthropic", "claude"):  # not allowed in skill names
        out = out.replace(reserved, "")
    out = re.sub(r"-+", "-", out).strip("-")
    return out[:max_chars].rstrip("-") or "context-pack"
