"""Normalised Document (guide B4, PRD FR-C1): one cleaned post, comment or page segment.

A Document is created only AFTER the cleaning chain has hashed the author
and redacted PII. It never holds a raw author name: author_hash must be a
sha256 hex digest.
"""

from datetime import date, datetime

import re

from pydantic import field_validator
from sqlalchemy import DateTime
from sqlmodel import JSON, Field, SQLModel

from ctxpack.schemas.enums import DatePrecision, Platform, RelevanceReason

SHA256_HEX = re.compile(r"^[0-9a-f]{64}$")


class Document(SQLModel):
    """Shared fields; db.DocumentRow adds the table on top of this."""

    id: str = Field(primary_key=True, description="Document id, unique across runs.")
    run_id: str = Field(index=True, description="Run that collected this document.")
    platform: Platform = Field(description="Source family.")
    source_unit: str = Field(
        description='Source unit, e.g. "reddit:r/mealprep" or "web:forum.example.nl".'
    )
    found_by: str | None = Field(default=None, description="The search words that found it (a web page's query, "
                                 "an Apify search target); tells prompted from unprompted brand mentions (V12).")
    url: str = Field(description="Page or post URL.")
    permalink: str | None = Field(default=None, description="Comment permalink when available.")
    community: str | None = Field(default=None, description="Subreddit, hashtag, channel or domain.")
    text: str = Field(description="Cleaned, PII-redacted text (untrusted user content).")
    text_en: str | None = Field(default=None, description="English translation when not English.")
    language: str | None = Field(default=None, description="ISO 639-1 language code.")
    posted_at: date | None = Field(default=None, description="Normalised posting date.")
    date_precision: DatePrecision = Field(default=DatePrecision.unknown)
    engagement_raw: dict = Field(default_factory=dict, sa_type=JSON, description="Platform metrics as collected.")
    engagement_percentile: float | None = Field(
        default=None, ge=0, le=100, description="Engagement percentile within its platform."
    )
    author_hash: str | None = Field(
        default=None, description="sha256(salt + platform + handle); never a name."
    )
    thread_id: str | None = Field(default=None, description="Thread or video the post belongs to.")
    relevance: float | None = Field(default=None, ge=0, le=1)
    is_relevant: bool | None = Field(default=None)
    relevance_reason: RelevanceReason | None = Field(
        default=None, description="Relevance worker's reason code (F4-5)."
    )
    market_match: bool | None = Field(
        default=None, description="From or about the brief's market; null = cannot tell."
    )
    is_promotional: bool | None = Field(
        default=None, description="Brand, sponsored or affiliate content: never counted as audience voice."
    )
    research_question_ids: list[str] = Field(
        default_factory=list, sa_type=JSON, description="Research questions this document helps answer."
    )
    extraction: dict | None = Field(default=None, sa_type=JSON, description="Extractor output (FR-C3).")
    redacted: bool = Field(default=False, description="True if redaction changed the text.")
    short_form: bool = Field(default=False, description="Under 4 words: lexicon only, never counted.")
    fragment_anchor_start: str | None = Field(
        default=None, description="Text-fragment start words from the ORIGINAL text, no PII."
    )
    fragment_anchor_end: str | None = Field(default=None, description="Text-fragment end words, no PII.")
    expires_at: datetime | None = Field(default=None, index=True, sa_type=DateTime(timezone=True),
                                        description="Deleted after this time.")

    @field_validator("author_hash")
    @classmethod
    def _hashed_only(cls, value: str | None) -> str | None:
        """Privacy guard: a raw author name can never be stored."""
        if value is not None and not SHA256_HEX.match(value):
            raise ValueError("author_hash must be a sha256 hex digest, never a name")
        return value
