"""Re-apply the current redaction to a saved run (no model calls, no cost).

Used after the redaction rules improve (e.g. first names written inside posts):
documents (text, text_en, extraction), text-fragment anchors, the draft and every
saved pack of the run get the SAME redaction, so quotes stay exact substrings of
their evidence. A quote that no longer matches is removed (never edited by hand),
and every pack is schema-validated before it is saved under its own id.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any

from ctxpack import db
from ctxpack.collect.cleaning import redact

SKIP_KEYS = {"id", "pack_id", "run_id", "doc_id", "url", "permalink", "text_fragment_url", "author_hash",
             "generated_at", "created_at", "posted_at", "evidence_id", "item_id", "cluster_id", "schema_version"}


@dataclass
class RedactReport:
    documents_changed: int = 0
    anchors_cleared: int = 0
    strings_changed: int = 0
    quotes_removed: int = 0
    packs_saved: list[str] = field(default_factory=list)


def redact_tree(value: Any, report: RedactReport) -> Any:
    """Every human-text string in a JSON-like tree, redacted; ids, urls, hashes and dates untouched."""
    if isinstance(value, dict):
        return {k: (v if k in SKIP_KEYS else redact_tree(v, report)) for k, v in value.items()}
    if isinstance(value, list):
        return [redact_tree(v, report) for v in value]
    if isinstance(value, str):
        out, changed = redact(value)
        report.strings_changed += changed
        return out
    return value


def _flat(text: str) -> str:
    return re.sub(r"\s+", " ", text).strip()


def anchors_ok(start: str | None, end: str | None, redacted_text: str) -> bool:
    """Anchor phrases hold no personal data: redaction leaves them alone AND they still appear in the post's
    redacted text (spacing ignored - anchors come from the page, the stored text is normalised)."""
    flat = _flat(redacted_text)
    return bool(start) and all(not redact(a)[1] and _flat(a) in flat for a in (start, end) if a)


def refresh_fragment_links(value: Any, report: RedactReport, docs: dict[str, Any]) -> None:
    """Every evidence link is rebuilt from its post's (checked) anchors; links whose post is unknown are
    kept only if redaction leaves their anchor words alone."""
    from urllib.parse import unquote

    from ctxpack.collect.web import text_fragment_url

    if isinstance(value, dict):
        if "text_fragment_url" in value:
            old = value["text_fragment_url"]
            doc = docs.get(value.get("doc_id") or value.get("id", ""))
            if doc is not None:
                new = (text_fragment_url(doc.url, doc.fragment_anchor_start, doc.fragment_anchor_end)
                       if doc.fragment_anchor_start else None)
            elif old and "#:~:text=" in old:
                anchors = [unquote(a) for a in old.split("#:~:text=", 1)[1].split(",")]
                new = None if any(redact(a)[1] for a in anchors) else old
            else:
                new = old
            report.anchors_cleared += bool(old) and not new
            value["text_fragment_url"] = new
        for v in value.values():
            refresh_fragment_links(v, report, docs)
    elif isinstance(value, list):
        for v in value:
            refresh_fragment_links(v, report, docs)


def drop_broken_quotes(pack: dict, report: RedactReport) -> None:
    """Quotes must stay exact substrings of their evidence; any that do not are removed."""
    ev = {e["id"]: e["text"] for e in pack.get("evidence", [])}

    def walk(value: Any) -> None:
        if isinstance(value, dict):
            if isinstance(value.get("quotes"), list):
                kept = [q for q in value["quotes"] if q.get("text", "") in ev.get(q.get("evidence_id"), "")]
                report.quotes_removed += len(value["quotes"]) - len(kept)
                value["quotes"] = kept
            for v in value.values():
                walk(v)
        elif isinstance(value, list):
            for v in value:
                walk(v)

    walk(pack)


def redact_run(run_id: str) -> RedactReport:
    from ctxpack.schemas.document import Document
    from ctxpack.schemas.pack import ContextPack

    report = RedactReport()
    run = db.get_run(run_id)
    if run is None:
        raise KeyError(f"run {run_id} not found")

    changed_docs = []
    for d in db.get_documents(run_id):
        text, t1 = redact(d.text)
        text_en, t2 = redact(d.text_en) if d.text_en else (None, False)
        extraction = redact_tree(d.extraction, report) if d.extraction else d.extraction
        anchors_pii = bool(d.fragment_anchor_start) and not anchors_ok(d.fragment_anchor_start,
                                                                      d.fragment_anchor_end, text)
        if t1 or t2 or anchors_pii or extraction != d.extraction:
            data = Document.model_validate(d.model_dump()).model_dump()
            data.update(text=text, text_en=text_en, extraction=extraction, redacted=d.redacted or t1)
            if anchors_pii:  # anchors come from the original text and must hold no PII: drop the link instead
                data.update(fragment_anchor_start=None, fragment_anchor_end=None)
                report.anchors_cleared += 1
            changed_docs.append(Document(**data))
    report.documents_changed = len(changed_docs)
    if changed_docs:
        db.save_documents(changed_docs)

    by_doc = {d.id: d for d in db.get_documents(run_id)}  # redacted, anchors checked
    ev_doc = {e["id"]: e["doc_id"] for part in (run.draft or {}, (run.draft or {}).get("verified", {}))
              for e in part.get("evidence", []) if e.get("doc_id")}
    docs = {**by_doc, **{ev: by_doc[d] for ev, d in ev_doc.items() if d in by_doc}}  # by doc id and by EV id

    if run.draft:
        draft = redact_tree(run.draft, report)
        refresh_fragment_links(draft, report, docs)
        for part in [draft.get("verified", {})]:
            if part.get("evidence"):
                drop_broken_quotes({"evidence": part["evidence"], "sections": part.get("sections")}, report)
        db.update_run(run_id, draft=draft)

    for row in db.list_packs_for_run(run_id):
        pack = redact_tree(row.pack, report)
        refresh_fragment_links(pack, report, docs)
        drop_broken_quotes(pack, report)
        db.save_pack(ContextPack.model_validate(pack), run_id=run_id, featured=row.featured)
        report.packs_saved.append(row.id)
    return report
