"""Guardrails that never contradict themselves (exports audit 2026-10-10).

never_claim holds the wording the compliance check flagged (e.g. 'slimmer' or 'eiwitboost' as implied health
claims under EU Reg. 1924/2006). A "say this" phrase that uses that wording would tell a writer to do exactly what
the legal check warns against, so it is dropped; anything else that uses it (the position, a hook, a move) is shown
with a "check with legal first" note instead.

What counts as flagged wording, on whole words only:
- a whole flagged phrase ("filling, high protein" inside "easy, filling, high protein"), or the phrase itself
  when it is two or more words of a flagged phrase ("nét wat slimmer");
- a term the compliance check names in quote marks in its reason ("'Slimmer' is a vague health claim").
A single ordinary word that merely appears in a flagged phrase ("lekker" in "Spotgoedkoop of gewoon lekker?")
does not count: the reason names what is risky.
"""

from __future__ import annotations

import re

_QUOTED = re.compile(r"['‘\"“]([^'’\"”]{3,40})['’\"”]")


def _inside(small: str, big: str) -> bool:
    """`small` appears in `big` as whole words ("lekker" is not inside "lekkere")."""
    return re.search(rf"(?<!\w){re.escape(small)}(?!\w)", big) is not None


def named_terms(flags: list[dict]) -> list[str]:
    """Short terms (1-3 words) the compliance reasons put in quote marks."""
    safer = " ".join((f.get("safer_wording") or "").casefold() for f in flags)   # what the check recommends
    terms = [m.strip() for f in flags for m in _QUOTED.findall(f.get("why") or "")]
    return _unique(t for t in terms if 1 <= len(t.split()) <= 3 and not _inside(t.casefold(), safer))


def _unique(items) -> list[str]:
    seen: dict[str, str] = {}
    for x in items:
        seen.setdefault(x.casefold(), x)
    return list(seen.values())


def flagged_words(phrase: str, never_claim: list[str], flags: list[dict] | None = None) -> list[str]:
    """The flagged wording `phrase` uses (empty = no conflict)."""
    p = phrase.casefold().strip()
    if not p:
        return []
    out = [r.strip() for r in never_claim if (rc := r.casefold().strip())
           and (_inside(rc, p) or (len(p.split()) >= 2 and _inside(p, rc)))]
    out += [t for t in named_terms(flags or []) if _inside(t.casefold(), p)]
    return _unique(out)


def clean_say_this(say_this: list[str], never_claim: list[str], flags: list[dict] | None = None) -> list[str]:
    """"Say this" without any phrase that uses wording the legal check flagged."""
    return [s for s in say_this if not flagged_words(s, never_claim, flags)]
