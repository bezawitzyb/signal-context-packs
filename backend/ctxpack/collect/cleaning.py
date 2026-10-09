"""The cleaning chain used by every collection tool (guide Step 1.5, B8c, PRD FR-C2).

Order: normalise -> privacy (hash author, redact) -> [24 h cache stores
these Drafts] -> dates + window -> de-duplication -> spam -> relevance ->
engagement percentile -> Documents.

Privacy rule: the raw author name enters make_draft() and never leaves it;
only author_hash does. Nothing here logs or returns scraped text except
the cleaned, redacted Drafts and Documents themselves.
"""

from __future__ import annotations

import calendar
import hashlib
import html
import re
import unicodedata
from dataclasses import asdict, dataclass, field
from datetime import date, datetime, timedelta, timezone
from typing import Any, Iterable

from datasketch import MinHash, MinHashLSH

from ctxpack.collect.relevance import BriefContext, classify
from ctxpack.config import get_settings, load_yaml
from ctxpack.schemas.document import Document
from ctxpack.schemas.enums import DatePrecision, Platform


def _cfg() -> dict[str, Any]:
    return load_yaml("modes")["cleaning"]


# --------------------------------------------------------------------------
# 1. Normalise
# --------------------------------------------------------------------------

_ZERO_WIDTH = re.compile("[​‌‍⁠﻿]")
_SPACES = re.compile(r"[ \t  -   　]+")


# Some scrapers return emoji as escaped text ("\\ud83d\\udc40") and forums write smileys as image markup
# ("![:9~](http://i.fok.nl/s/kwijl.gif)"). Both become what the reader saw: the emoji, or the smiley's text.
_UNICODE_ESCAPE = re.compile(r"\\u([dD][89abAB][0-9a-fA-F]{2})\\u([dD][c-fC-F][0-9a-fA-F]{2})|\\u([0-9a-fA-F]{4})")
_MD_IMAGE = re.compile(r"!\[([^\]\n]{0,40})\]\(https?://[^)\s]+\)")


def _decode_escape(m: re.Match) -> str:
    if m.group(1):
        hi, lo = int(m.group(1), 16), int(m.group(2), 16)
        return chr(0x10000 + ((hi - 0xD800) << 10) + (lo - 0xDC00))
    code = int(m.group(3), 16)
    return "" if 0xD800 <= code <= 0xDFFF else chr(code)  # a lone half of an emoji is dropped


def tidy_markup(text: str) -> str:
    """Escaped emoji -> the emoji; forum image markup -> its alt text (the smiley as written)."""
    return _MD_IMAGE.sub(lambda m: m.group(1), _UNICODE_ESCAPE.sub(_decode_escape, text))


def normalise_text(text: str) -> str:
    """Escaped emoji and image markup, HTML entities, Unicode NFC, invisible characters and whitespace runs."""
    text = unicodedata.normalize("NFC", tidy_markup(html.unescape(text or "")))
    text = _ZERO_WIDTH.sub("", text).replace("\r\n", "\n").replace("\r", "\n")
    lines = [_SPACES.sub(" ", line).strip() for line in text.split("\n")]
    return re.sub(r"\n{3,}", "\n\n", "\n".join(lines)).strip()


_URL = re.compile(r"https?://\S+|www\.\S+", re.I)
_WORD = re.compile(r"[^\W_]+(?:['’-][^\W_]+)*")


def words(text: str) -> list[str]:
    """Words, ignoring URLs. Hashtags count as words (their text part)."""
    return _WORD.findall(_URL.sub(" ", text))


def is_short_form(text: str) -> bool:
    """Under 4 words: kept for the lexicon, never counted (PRD D25)."""
    return len(words(text)) <= _cfg()["short_form_max_words"]


# --------------------------------------------------------------------------
# 2. Privacy: author hash + redaction
# --------------------------------------------------------------------------

def hash_author(platform: str, handle: str | None, salt: str) -> str | None:
    """sha256(salt + platform + handle). The same person on one platform -> one hash."""
    if not handle or not handle.strip().lstrip("@").strip():
        return None
    if not salt:
        raise RuntimeError("AUTHOR_HASH_SALT is not set - refusing to hash authors without a salt")
    clean = handle.strip().lstrip("@").casefold()
    return hashlib.sha256(f"{salt}{platform}{clean}".encode()).hexdigest()


_EMAIL = re.compile(r"[\w.+-]+@[\w-]+(?:\.[\w-]+)+")
_PROFILE_URL = re.compile(
    r"(?:https?://)?(?:www\.|m\.|old\.|new\.)?(?:"
    r"reddit\.com/(?:u|user)/[\w-]+"
    r"|instagram\.com/(?!p/|reels?/|explore/|stories/|tv/)[\w.]+"
    r"|tiktok\.com/@[\w.]+"
    r"|youtube\.com/(?:@[\w.-]+|channel/[\w-]+|c/[\w-]+|user/[\w-]+)"
    r"|(?:twitter|x)\.com/(?!i/|search|hashtag/|home\b)\w+"
    r"|facebook\.com/(?!groups/|events/|watch/)[\w.]+"
    r"|linkedin\.com/(?:in|posts)/[\w%-]+"
    r")\S*",
    re.I,
)
_HANDLE = re.compile(r"(?<![\w.@/])@[A-Za-z0-9_][A-Za-z0-9_.]{1,29}(?<!\.)")
_REDDIT_USER = re.compile(r"(?<![\w/])/?u/[A-Za-z0-9_-]{3,20}\b")
_PHONE_INTL = re.compile(r"(?<![\w+])(?:\+|00)\d{1,3}[\s.-]?(?:\(0\)[\s.-]?)?\d(?:[\s.-]?\d){6,12}(?![\w])")
# National numbers start with 0 and use spaces, dashes or a slash - never dots,
# so dates like 04.07.2026 are not mistaken for phones.
_PHONE_NATIONAL = re.compile(r"(?<![\w+.,/])\(?0\d{1,4}\)?[\s/-]?\d(?:[\s-]?\d){5,9}(?![\w.,])")


# Forum quote headers name a person: "Zitat von X", "X schreef:", "Quote from X", "X wrote:".
_NAME = r"[^\s:,]{2,40}"
_QUOTE_HEADER = re.compile(
    rf"\b(?P<pre>(?:zitat|citaat|quote|quoting)\s+(?:geschrieben\s+)?(?:von|van|from|by|of)\s+){_NAME}"
    rf"|\b(?P<pre2>originally\s+posted\s+by\s+|geschrieben\s+von\s+|gepost\s+door\s+){_NAME}"
    rf"|(?<![\w\[])(?P<name>{_NAME})(?P<post>\s+(?:schreef|schrieb|wrote|said|zei|sagte)(?:\s+(?:op|am|on)\s+[^:\n]{{1,40}})?\s*:)",
    re.I,
)


def _quote_header(m: re.Match) -> str:
    if m.group("pre"):
        return m.group("pre") + "[user]"
    if m.group("pre2"):
        return m.group("pre2") + "[user]"
    return "[user]" + m.group("post")


# First names written INSIDE a post, found by the words around them (no name lists, no model):
#   "mijn man Hans", "my wife Anna", "meine Frau Petra"          -> "mijn man [name]"
#   "Bedankt Oscar," / "Hi Tom," at the start of a line            -> "Bedankt [name],"
#   "Hartelijke groet,\nLaura" / "Regards, Tom" at the end of a line -> "Hartelijke groet,\n[name]"
# The cue words match in any case; the name must start with a capital.
_FIRST_NAME = r"(?!(?:Allemaal|Iedereen|Allen|All|Everyone|Everybody|Guys|Folks|Team|Zusammen|Alle|Leute)\b)" \
              r"[A-ZÀ-ÖØ-Þ][a-zß-öø-ÿ]{1,20}(?:[-'][A-Za-zÀ-ÖØ-öø-ÿ]{2,20})?"
_RELATION = (r"(?:man|vrouw|vriend|vriendin|vriendje|vriendinnetje|partner|zoon|dochter|broer|zus|zusje|"
             r"moeder|vader|schoonmoeder|schoonvader|collega|buurman|buurvrouw|"
             r"husband|wife|boyfriend|girlfriend|son|daughter|brother|sister|mum|mom|dad|friend|colleague|"
             r"neighbour|neighbor|mann|frau|freund|freundin|sohn|tochter|bruder|schwester|kollege|kollegin)")
_NAMES_IN_TEXT = [
    re.compile(rf"(?P<cue>(?i:\b(?:mijn|m'n|onze|ons|my|our|mein|meine|meinem|meinen|unser|unsere)\s+"
               rf"{_RELATION}\s+))(?P<name>{_FIRST_NAME})\b"),
    re.compile(rf"(?P<cue>(?im:^[ \t]*(?:bedankt|dank\s*je(?:wel)?|dankjewel|hoi|hallo|hey|hi|beste|lieve|dear|"
               rf"thanks|thank\s+you|hello|liebe|lieber|danke)[ \t,]+))(?P<name>{_FIRST_NAME})(?=[ \t]*[,!.:]|[ \t]*$)",
               re.M),
    re.compile(rf"(?P<cue>(?i:\b(?:(?:met\s+)?(?:vriendelijke|hartelijke)\s+groet(?:en)?|groet(?:en|jes)?|"
               rf"liefs|mvg|kind\s+regards|best\s+regards|regards|cheers|viele\s+gr(?:ü|ue)(?:ß|ss)e|"
               rf"liebe\s+gr(?:ü|ue)(?:ß|ss)e|gr(?:ü|ue)(?:ß|ss)e|gru(?:ß|ss)|lg)[ \t]*[,.!]?[ \t]*\n?[ \t]*))"
               rf"(?P<name>{_FIRST_NAME})(?=[ \t]*$)", re.M),
    # a name joined to one already redacted: "Gr [user] en Hans en de kids" -> "Gr [user] en [name] en de kids"
    re.compile(rf"(?P<cue>\[(?:user|name)\]\s*(?:,\s*)?(?i:en|and|und|&)\s+)(?P<name>{_FIRST_NAME})\b"),
]


def redact_first_names(text: str) -> str:
    """Names written inside the post (relatives, greetings, sign-offs) -> [name]."""
    for pattern in _NAMES_IN_TEXT:
        text = pattern.sub(lambda m: m.group("cue") + "[name]", text)
    return text


def redact_names(text: str, names: list[str]) -> str:
    """Replace the page's known author names (from the segmenter) wherever they appear."""
    for name in sorted({n.strip().lstrip("@") for n in names if n and len(n.strip().lstrip("@")) >= 3},
                       key=len, reverse=True):
        text = re.sub(rf"(?<![\w@]){re.escape(name)}(?!\w)", "[user]", text, flags=re.I)
    return text


_HANDLE_LIKE = re.compile(r"[\d_.]")


def name_like(names: list[str | None]) -> list[str]:
    """Author names safe to redact wherever they appear: a full name (two words or more) or a handle with
    digits, '_' or '.'. A single plain word ("snacks", "Anna") is left out - redacting it would cut ordinary
    words out of quotes (first names written in a post are handled by redact_first_names)."""
    out = []
    for n in names:
        n = (n or "").strip().lstrip("@")
        if len(n) >= 3 and (" " in n or _HANDLE_LIKE.search(n)):
            out.append(n)
    return sorted(set(out))


def redact(text: str, names: list[str] | None = None) -> tuple[str, bool]:
    """Emails, profile URLs, phones, handles, quote headers, known author names and first names written in
    the post -> [email] [user] [phone] [name]."""
    out = redact_names(text, names or [])
    out = redact_first_names(out)
    out = _QUOTE_HEADER.sub(_quote_header, out)
    out = _EMAIL.sub("[email]", out)
    out = _PROFILE_URL.sub("[user]", out)
    out = _PHONE_INTL.sub("[phone]", out)
    out = _PHONE_NATIONAL.sub("[phone]", out)
    out = _HANDLE.sub("[user]", out)
    out = _REDDIT_USER.sub("[user]", out)
    return out, out != text


_TIKTOK_HANDLE_IN_URL = re.compile(r"(tiktok\.com/)@[^/?#]+/", re.I)


def scrub_url(url: str | None) -> str | None:
    """Item URLs must not carry a handle either (TikTok video URLs contain one)."""
    if not url:
        return url
    # tiktok.com/@/video/<id> opens the video (checked 2026-10-09: same page data as the real handle's link;
    # a wrong id gives TikTok's not-found status 10204).
    if (m := _LINKEDIN_POST.search(url)):  # /posts/<first-last>_..-<activity id>-xxxx names the author
        return linkedin_url(m.group(1))
    if (m := _X_STATUS.search(url)):  # x.com/<handle>/status/<id> names the author
        return x_url(m.group(1))
    if (m := _FB_POST.search(url)):    # facebook.com/<name>/posts/... names the author
        return facebook_url(m.group(1))
    return _TIKTOK_HANDLE_IN_URL.sub(r"\1@/", url)


_LINKEDIN_POST = re.compile(r"linkedin\.com/posts/[^?#\s]*?(\d{16,22})")
_X_STATUS = re.compile(r"(?:twitter|x)\.com/(?:[^/?#\s]+|i/web)/status(?:es)?/(\d{5,25})", re.I)


_FB_POST = re.compile(r"facebook\.com/(?:groups/[^/?#\s]+/)?(?:[^/?#\s]+/)?(?:posts|permalink)/(\d{8,25})", re.I)


def facebook_url(post_id: str, comment_id: str | None = None) -> str:
    """A Facebook post (or comment) link without anyone's name in it: facebook.com/<post id> opens the post
    (checked 2026-10-09: it redirects to the post's own page)."""
    return f"https://www.facebook.com/{post_id}" + (f"?comment_id={comment_id}" if comment_id else "")


def x_url(post_id: str) -> str:
    """An X post link without the author's handle in it (X opens /i/status/<id>)."""
    return f"https://x.com/i/status/{post_id}"


def linkedin_url(activity_id: str) -> str:
    """A LinkedIn post link without the author's name in it (V6)."""
    return f"https://www.linkedin.com/feed/update/urn:li:activity:{activity_id}/"


@dataclass
class Draft:
    """A normalised, hashed, redacted item - safe to cache (PRD DH2). No raw names."""

    platform: Platform
    source_unit: str
    url: str
    text: str
    author_hash: str | None
    date_raw: str | None
    fetched_at: datetime
    permalink: str | None = None
    community: str | None = None
    thread_id: str | None = None
    engagement: dict[str, Any] = field(default_factory=dict)
    redacted: bool = False
    short_form: bool = False
    fragment_anchor_start: str | None = None  # from the ORIGINAL text, PII-free (DH12)
    fragment_anchor_end: str | None = None
    found_by: str | None = None  # the search words that found it (set by the tool, never cached across runs)

    def to_cache(self) -> dict[str, Any]:
        data = asdict(self)
        data["platform"] = str(self.platform)
        data["fetched_at"] = self.fetched_at.isoformat()
        data.pop("found_by", None)
        return data

    @classmethod
    def from_cache(cls, data: dict[str, Any]) -> "Draft":
        return cls(**{**data, "platform": Platform(data["platform"]),
                      "fetched_at": datetime.fromisoformat(data["fetched_at"])})


def make_draft(
    *,
    platform: Platform,
    source_unit: str,
    url: str,
    text: str,
    author: str | None,
    date_raw: str | int | float | None,
    fetched_at: datetime,
    salt: str | None = None,
    permalink: str | None = None,
    community: str | None = None,
    thread_id: str | None = None,
    engagement: dict[str, Any] | None = None,
    fragment_anchor_start: str | None = None,
    fragment_anchor_end: str | None = None,
    page_names: list[str] | None = None,
) -> Draft:
    """Normalise + privacy in ONE function: the raw author name dies here (CLAUDE.md)."""
    if salt is None:
        settings = get_settings()
        secret = settings.author_hash_salt
        salt = secret.get_secret_value() if secret else ""
        if not salt and settings.offline:
            from ctxpack.config import OFFLINE_SALT

            salt = OFFLINE_SALT
    author_hash = hash_author(str(platform), author, salt)
    names = name_like([author]) + list(page_names or [])  # people sign their posts with their own name
    del author  # never stored, logged, cached or prompted
    clean, changed = redact(normalise_text(text), names)
    return Draft(
        platform=platform,
        source_unit=source_unit,
        url=scrub_url(url) or "",
        text=clean,
        author_hash=author_hash,
        date_raw=None if date_raw is None else str(date_raw),
        fetched_at=fetched_at,
        permalink=scrub_url(permalink),
        community=community,
        thread_id=thread_id,
        engagement={k: v for k, v in (engagement or {}).items() if isinstance(v, (int, float)) and not isinstance(v, bool)},
        redacted=changed,
        short_form=is_short_form(clean),
        fragment_anchor_start=fragment_anchor_start,
        fragment_anchor_end=fragment_anchor_end,
    )


# --------------------------------------------------------------------------
# 3. Dates (absolute + relative; en nl de, and since V2 fr it es pt pl sv da nb fi) and the time window
# --------------------------------------------------------------------------

_MONTHS = {
    1: ["jan", "january", "januari", "januar", "jän", "jänner", "janvier", "gennaio", "enero", "janeiro", "stycznia",
        "styczeń", "januar", "tammikuuta", "tammikuu"],
    2: ["feb", "february", "februari", "februar", "février", "fevrier", "febbraio", "febrero", "fevereiro", "lutego",
        "luty", "helmikuuta", "helmikuu"],
    3: ["mär", "mar", "march", "maart", "mrt", "märz", "maerz", "mrz", "mars", "marzo", "março", "marca", "marzec", "marts",
        "maaliskuuta", "maaliskuu"],
    4: ["apr", "april", "avril", "aprile", "abril", "kwietnia", "kwiecień", "huhtikuuta", "huhtikuu"],
    5: ["may", "mei", "mai", "maggio", "mayo", "maio", "maja", "maj", "toukokuuta", "toukokuu"],
    6: ["jun", "june", "juni", "juin", "giugno", "junio", "junho", "czerwca", "czerwiec", "kesäkuuta", "kesäkuu"],
    7: ["jul", "july", "juli", "juillet", "luglio", "julio", "julho", "lipca", "lipiec", "heinäkuuta", "heinäkuu"],
    8: ["aug", "august", "augustus", "août", "aout", "agosto", "sierpnia", "sierpień", "augusti", "elokuuta", "elokuu"],
    9: ["sep", "sept", "september", "septembre", "settembre", "septiembre", "setembro", "września", "wrzesień",
        "syyskuuta", "syyskuu"],
    10: ["oct", "october", "okt", "oktober", "octobre", "ottobre", "octubre", "outubro", "października",
         "październik", "lokakuuta", "lokakuu"],
    11: ["nov", "november", "novembre", "noviembre", "novembro", "listopada", "listopad", "marraskuuta", "marraskuu"],
    12: ["dec", "december", "dez", "dezember", "décembre", "decembre", "dicembre", "diciembre", "dezembro", "grudnia",
         "grudzień", "joulukuuta", "joulukuu"],
}
_MONTH = {name: num for num, names in _MONTHS.items() for name in names}
_MONTH_RE = "|".join(sorted(map(re.escape, _MONTH), key=len, reverse=True))

_NUMBER_WORDS = {"a": 1, "an": 1, "one": 1, "een": 1, "één": 1, "ein": 1, "eine": 1,
                 "einem": 1, "einer": 1, "einen": 1}
# unit -> (kind, size). kind: days | months | years
_UNITS = {
    **dict.fromkeys(["s", "sec", "secs", "second", "seconds", "seconde", "seconden", "sekunde", "sekunden"], ("days", 0)),
    **dict.fromkeys(["m", "min", "mins", "minute", "minutes", "minuut", "minuten"], ("days", 0)),
    **dict.fromkeys(["h", "hr", "hrs", "hour", "hours", "uur", "uren", "stunde", "stunden", "heure", "heures", "ora",
                     "ore", "hora", "horas", "godzinę", "godziny", "godzin", "timme", "timmar", "time", "timer",
                     "tunti", "tuntia"], ("hours", 1)),
    **dict.fromkeys(["d", "day", "days", "dag", "dagen", "tag", "tage", "tagen", "jour", "jours", "giorno", "giorni",
                     "día", "días", "dia", "dias", "dzień", "dni", "dagar", "dage", "dager", "päivä", "päivää"],
                    ("days", 1)),
    **dict.fromkeys(["w", "wk", "wks", "week", "weeks", "weken", "woche", "wochen", "semaine", "semaines", "settimana",
                     "settimane", "semana", "semanas", "tydzień", "tygodnie", "tygodni", "vecka", "veckor", "uge",
                     "uger", "uke", "uker", "viikko", "viikkoa"], ("days", 7)),
    **dict.fromkeys(["mo", "mos", "month", "months", "maand", "maanden", "monat", "monate", "monaten", "mois", "mese",
                     "mesi", "mes", "meses", "mês", "miesiąc", "miesiące", "miesięcy", "månad", "månader", "måned",
                     "måneder", "kuukausi", "kuukautta"], ("months", 1)),
    **dict.fromkeys(["y", "yr", "yrs", "year", "years", "jaar", "jaren", "jahr", "jahre", "jahren", "an", "ans",
                     "anno", "anni", "año", "años", "ano", "anos", "rok", "lata", "lat", "år", "vuosi", "vuotta"],
                    ("years", 1)),
}
_UNIT_RE = "|".join(sorted(map(re.escape, _UNITS), key=len, reverse=True))
_QTY = r"(\d+|" + "|".join(map(re.escape, _NUMBER_WORDS)) + r")"
# "3 days ago" (en nl it pl sv da nb fi pt) and "vor 3 Tagen", "il y a 3 jours", "hace 3 días", "há 3 dias"
_REL_AGO = re.compile(rf"(?<!\w){_QTY}\s*({_UNIT_RE})\.?\s+(?:ago|geleden|fa|temu|sedan|siden|sitten|atrás)(?!\w)", re.I)
_REL_VOR = re.compile(rf"(?<!\w)(?:vor|il y a|hace|há)\s+{_QTY}\s+({_UNIT_RE})(?!\w)", re.I)
_REL_SHORT = re.compile(r"^(\d+)\s*(mo|[smhdwy])$", re.I)
_DAY_WORDS = {
    0: ["today", "just now", "vandaag", "zojuist", "net", "heute", "gerade", "gerade eben", "soeben",
        "aujourd'hui", "oggi", "hoy", "hoje", "dzisiaj", "dziś", "idag", "i dag", "tänään"],
    1: ["yesterday", "gisteren", "gestern", "ieri", "ayer", "ontem", "wczoraj", "igår", "i går", "eilen"],
    2: ["eergisteren", "vorgestern", "avant-hier", "anteayer", "anteontem", "przedwczoraj", "i förrgår",
        "i forgårs", "toissapäivänä"],
}


def _shift_months(d: date, months: int) -> date:
    y, m = divmod(d.year * 12 + d.month - 1 - months, 12)
    m += 1
    return date(y, m, min(d.day, calendar.monthrange(y, m)[1]))


def _relative(qty: str, unit: str, now: datetime) -> tuple[date, DatePrecision]:
    n = int(qty) if qty.isdigit() else _NUMBER_WORDS[qty.lower()]
    kind, size = _UNITS[unit.lower()]
    if kind == "hours":
        return (now - timedelta(hours=n)).date(), DatePrecision.day
    if kind == "days":
        return (now - timedelta(days=n * size)).date(), DatePrecision.day
    if kind == "months":
        return _shift_months(now.date(), n), DatePrecision.month
    return _shift_months(now.date(), 12 * n), DatePrecision.year


def _year(text: str) -> int:
    y = int(text)
    return y + 2000 if y < 100 else y


def parse_date(value: str | int | float | None, fetched_at: datetime) -> tuple[date | None, DatePrecision]:
    """Absolute or relative date in en / nl / de -> (date, precision). Unknown -> (None, unknown)."""
    unknown = (None, DatePrecision.unknown)
    if value is None or value == "":
        return unknown
    try:
        if isinstance(value, (int, float)) or re.fullmatch(r"\d{9,13}", str(value).strip()):
            ts = float(value)
            ts = ts / 1000 if ts > 1e11 else ts  # milliseconds
            return datetime.fromtimestamp(ts, tz=timezone.utc).date(), DatePrecision.day
        s = " ".join(str(value).strip().split())
        low = s.casefold()

        try:  # ISO 8601: 2026-07-04, 2026-07-04T14:29:08.000Z, 2026-07-04 14:53:52
            return datetime.fromisoformat(s.replace("Z", "+00:00")).date(), DatePrecision.day
        except ValueError:
            pass

        for days, names in _DAY_WORDS.items():
            if any(re.search(rf"(?<!\w){re.escape(n)}(?!\w)", low) for n in names):
                return (fetched_at - timedelta(days=days)).date(), DatePrecision.day
        if m := (_REL_AGO.search(low) or _REL_VOR.search(low)):
            return _relative(m.group(1), m.group(2), fetched_at)
        if m := _REL_SHORT.match(low):
            return _relative(m.group(1), m.group(2), fetched_at)

        # 04.07.2026, 4-7-2026, 4/7/26 - day first (nl/de); month first only if day > 12
        if m := re.fullmatch(r"(\d{1,2})[./-](\d{1,2})[./-](\d{2,4})\.?", low):
            a, b, y = int(m.group(1)), int(m.group(2)), _year(m.group(3))
            day, month = (b, a) if b > 12 >= a else (a, b)
            return date(y, month, day), DatePrecision.day
        # Jul 4, 2026 / July 4 2026
        if m := re.fullmatch(rf"({_MONTH_RE})\.?\s+(\d{{1,2}})(?:st|nd|rd|th)?,?\s+(\d{{4}})", low):
            return date(int(m.group(3)), _MONTH[m.group(1)], int(m.group(2))), DatePrecision.day
        # 4 July 2026 / 4 juli 2026 / 4. Juli 2026
        if m := re.fullmatch(rf"(\d{{1,2}})\.?\s+({_MONTH_RE})\.?,?\s+(\d{{4}})", low):
            return date(int(m.group(3)), _MONTH[m.group(2)], int(m.group(1))), DatePrecision.day
        # March 2025 / maart 2025 / März 2025
        if m := re.fullmatch(rf"({_MONTH_RE})\.?\s+(\d{{4}})", low):
            return date(int(m.group(2)), _MONTH[m.group(1)], 1), DatePrecision.month
        if m := re.fullmatch(r"(19|20)\d\d", low):
            return date(int(low), 1, 1), DatePrecision.year
    except (ValueError, OverflowError, OSError):
        return unknown
    return _embedded_date(low)


# A full day-month-year date INSIDE a longer string: forums show "zondag 19 juli 2026 om 18:09",
# "Di 12. Mär 2024, 14:03", "Geplaatst op 12 maart 2024", "12.03.2024, 14:03". Seen live: the model returned a
# date for 87 of 88 forum posts and only 2 parsed, so 56% of posts were "undated". Only day-level dates are
# searched this way, and never after "member since" words (a join date is not a post date).
_SINCE = re.compile(r"\b(lid sinds|member since|joined|registriert|mitglied seit|dabei seit|inscrit|iscritto|"
                    r"miembro desde|membro desde|medlem sedan|medlem siden|jäsen)\b", re.I)
_EMBEDDED = [
    ("dmy_num", re.compile(r"(?<![\d.])(\d{1,2})[./-](\d{1,2})[./-](\d{4}|\d{2})(?![\d.]*\d)")),
    ("mdy_name", re.compile(rf"(?<!\w)({_MONTH_RE})\.?\s+(\d{{1,2}})(?:st|nd|rd|th)?,?\s+(\d{{4}})(?!\d)")),
    ("dmy_name", re.compile(rf"(?<!\d)(\d{{1,2}})\.?\s+({_MONTH_RE})\.?,?\s+(\d{{4}})(?!\d)")),
]


def _embedded_date(low: str) -> tuple[date | None, DatePrecision]:
    if _SINCE.search(low):
        return None, DatePrecision.unknown
    for kind, rx in _EMBEDDED:
        for m in rx.finditer(low):
            try:
                if kind == "dmy_num":
                    a, b, y = int(m.group(1)), int(m.group(2)), _year(m.group(3))
                    day, month = (b, a) if b > 12 >= a else (a, b)
                    return date(y, month, day), DatePrecision.day
                if kind == "mdy_name":
                    return date(int(m.group(3)), _MONTH[m.group(1)], int(m.group(2))), DatePrecision.day
                return date(int(m.group(3)), _MONTH[m.group(2)], int(m.group(1))), DatePrecision.day
            except (ValueError, KeyError):
                continue
    return None, DatePrecision.unknown


def in_window(d: date | None, precision: DatePrecision, fetched_at: datetime, window_days: int) -> bool:
    """Undated posts stay (flagged). A month/year date stays if any part of it is in the window."""
    if d is None:
        return True
    latest = d
    if precision == DatePrecision.month:
        latest = d.replace(day=calendar.monthrange(d.year, d.month)[1])
    elif precision == DatePrecision.year:
        latest = date(d.year, 12, 31)
    return latest >= fetched_at.date() - timedelta(days=window_days)


# --------------------------------------------------------------------------
# 4. De-duplication: exact hash, then MinHash LSH on 5-word shingles
# --------------------------------------------------------------------------

_VIEW_KEYS = re.compile(r"view|play", re.I)


def engagement_score(engagement: dict[str, Any]) -> float | None:
    """One number to compare copies and rank posts. None when the actor gave no metrics."""
    nums = {k: float(v) for k, v in engagement.items() if isinstance(v, (int, float)) and not isinstance(v, bool)}
    if not nums:
        return None
    return sum(v / 100 if _VIEW_KEYS.search(k) else v for k, v in nums.items())


def _exact_key(text: str) -> str:
    return hashlib.sha256(" ".join(text.casefold().split()).encode()).hexdigest()


class Deduper:
    """Per-run duplicate index. Seed it with the run's stored docs; keeps the higher-engagement copy."""

    def __init__(self, existing: Iterable[tuple[str, str, float | None]] = ()):
        cfg = _cfg()
        self.num_perm, self.shingle = cfg["minhash_num_perm"], cfg["shingle_words"]
        self.lsh = MinHashLSH(threshold=cfg["minhash_threshold"], num_perm=self.num_perm)
        self.exact: dict[str, str] = {}             # exact hash -> key
        self.entries: dict[str, tuple[str, float]] = {}  # key -> (exact hash, score)
        for key, text, score in existing:
            self.check(key, text, score)

    def _minhash(self, text: str) -> MinHash | None:
        toks = [w.casefold() for w in words(text)]
        if len(toks) < self.shingle:
            return None  # too short for shingles: exact match only
        mh = MinHash(num_perm=self.num_perm)
        for i in range(len(toks) - self.shingle + 1):
            mh.update(" ".join(toks[i:i + self.shingle]).encode())
        return mh

    def _remove(self, key: str) -> None:
        exact, _ = self.entries.pop(key)
        self.exact.pop(exact, None)
        if key in self.lsh.keys:
            self.lsh.remove(key)

    def check(self, key: str, text: str, score: float | None) -> tuple[bool, str | None]:
        """-> (keep?, key of a stored copy this one replaces)."""
        score = score or 0.0
        exact = _exact_key(text)
        mh = self._minhash(text)
        dupe = self.exact.get(exact)
        if dupe is None and mh is not None:
            dupe = next(iter(self.lsh.query(mh)), None)
        replaced = None
        if dupe is not None:
            if score <= self.entries[dupe][1]:
                return False, None
            self._remove(dupe)
            replaced = dupe
        self.exact[exact] = key
        self.entries[key] = (exact, score)
        if mh is not None:
            self.lsh.insert(key, mh)
        return True, replaced


# --------------------------------------------------------------------------
# 5. Spam
# --------------------------------------------------------------------------

_HASHTAG = re.compile(r"(?<!\w)#\w+")
_PROMO = re.compile(
    r"\blink (?:is )?in (?:my |the )?bio\b|\blink in mijn bio\b|\blink (?:ist )?in (?:meiner |der )?bio\b"
    r"|\buse (?:my )?code\b|\b(?:discount|promo|coupon) code\b|\bkortingscode\b|\bgebruik (?:mijn )?code\b"
    r"|\brabattcode\b|\bgutscheincode\b|\bmit (?:dem )?code\b",
    re.I,
)


def _emoji_count(text: str) -> int:
    return sum(1 for ch in text if unicodedata.category(ch) == "So")


def spam_reason(draft: Draft, templates: set[tuple[str, str]]) -> str | None:
    """Why a draft is spam, or None. Posts under 4 words are never spam for length (D25)."""
    text = draft.text
    if not words(text) and _URL.search(text):
        return "link_only"
    if draft.short_form:
        return None
    cfg = _cfg()
    toks = text.split()
    tags = len(_HASHTAG.findall(text))
    if tags > cfg["spam_max_hashtags"] or tags / max(len(toks), 1) > cfg["spam_flood_share"]:
        return "hashtag_flood"
    visible = [ch for ch in text if not ch.isspace()]
    emoji = _emoji_count(text)
    if emoji >= 6 and emoji / max(len(visible), 1) > cfg["spam_flood_share"]:
        return "emoji_flood"
    if _PROMO.search(text):
        return "promo"
    if draft.author_hash:
        # Same author, same text once links, numbers, tags and handles are removed.
        template = " ".join(re.sub(r"https?://\S+|#\w+|\[user\]|\d+", " ", text.casefold()).split())
        if (draft.author_hash, template) in templates:
            return "repeat_author"
        templates.add((draft.author_hash, template))
    return None


# --------------------------------------------------------------------------
# 6. Engagement percentile within platform
# --------------------------------------------------------------------------

def percentile_of(score: float | None, population: list[float]) -> float | None:
    """Share of the platform's scores at or below this one (0-100). None if unknown."""
    if score is None or not population:
        return None
    below = sum(1 for p in population if p < score)
    equal = sum(1 for p in population if p == score)
    return round(100 * (below + 0.5 * equal) / len(population), 1)


# --------------------------------------------------------------------------
# The chain
# --------------------------------------------------------------------------

@dataclass
class CleanResult:
    documents: list[Document]
    stats: dict[str, int]
    replaced_ids: list[str]  # stored documents a better copy replaced: delete them
    usd: float = 0.0


def doc_id(run_id: str, d: Draft) -> str:
    raw = f"{run_id}|{d.platform}|{d.permalink or d.url}|{d.text}"
    return "DOC-" + hashlib.sha256(raw.encode()).hexdigest()[:16]


async def clean(
    drafts: list[Draft],
    *,
    run_id: str,
    window_days: int,
    brief: BriefContext,
    deduper: Deduper,
    templates: set[tuple[str, str]] | None = None,
    platform_scores: dict[str, list[float]] | None = None,
) -> CleanResult:
    """Run dates -> dedupe -> spam -> relevance -> percentile on privacy-safe Drafts.

    deduper / templates / platform_scores hold the run's state across tool
    calls (the caller seeds them from the run's stored documents).
    """
    templates = set() if templates is None else templates
    platform_scores = {} if platform_scores is None else platform_scores
    stats = dict.fromkeys(["collected", "redacted", "short_form", "undated", "out_of_window",
                           "duplicate", "replaced", "spam", "relevant", "kept"], 0)
    stats["collected"] = len(drafts)
    replaced: list[str] = []
    kept: list[tuple[str, Draft, date | None, DatePrecision]] = []
    batch_keys: set[str] = set()  # every key this call put in the deduper

    for d in drafts:
        stats["redacted"] += d.redacted
        posted, precision = parse_date(d.date_raw, d.fetched_at)
        if not in_window(posted, precision, d.fetched_at, window_days):
            stats["out_of_window"] += 1
            continue
        key = doc_id(run_id, d)
        keep, old = deduper.check(key, d.text, engagement_score(d.engagement))
        if not keep:
            stats["duplicate"] += 1
            continue
        batch_keys.add(key)
        if old:
            stats["replaced"] += 1
            if old in batch_keys:  # the copy came in this batch: just drop it
                kept = [k for k in kept if k[0] != old]
            else:  # the copy is already stored: the caller deletes it
                replaced.append(old)
        reason = spam_reason(d, templates)
        if reason:
            stats["spam"] += 1
            stats[f"spam_{reason}"] = stats.get(f"spam_{reason}", 0) + 1
            continue
        kept.append((key, d, posted, precision))

    outcome = await classify({key: d.text for key, d, _, _ in kept}, brief)

    for _, d, _, _ in kept:
        if (score := engagement_score(d.engagement)) is not None:
            platform_scores.setdefault(str(d.platform), []).append(score)

    retention = timedelta(days=get_settings().retention_days)
    documents = []
    for key, d, posted, precision in kept:
        verdict = outcome.verdicts.get(key)
        relevant = bool(verdict and verdict.is_relevant and not verdict.is_promotional)
        stats["relevant"] += relevant
        stats["short_form"] += d.short_form
        stats["undated"] += posted is None
        documents.append(Document(
            id=key, run_id=run_id, platform=d.platform, source_unit=d.source_unit, found_by=d.found_by,
            date_raw=(d.date_raw or "")[:80] or None,
            url=d.url, permalink=d.permalink, community=d.community, thread_id=d.thread_id,
            text=d.text, language=verdict.language if verdict else None,
            posted_at=posted, date_precision=precision,
            engagement_raw=d.engagement,
            engagement_percentile=percentile_of(engagement_score(d.engagement),
                                                platform_scores.get(str(d.platform), [])),
            author_hash=d.author_hash,
            relevance=verdict.relevance if verdict else None,
            is_relevant=relevant,
            relevance_reason=verdict.reason if verdict else None,
            market_match=verdict.market_match if verdict else None,
            is_promotional=verdict.is_promotional if verdict else None,
            research_question_ids=verdict.research_question_ids if verdict else [],
            redacted=d.redacted, short_form=d.short_form,
            fragment_anchor_start=d.fragment_anchor_start, fragment_anchor_end=d.fragment_anchor_end,
            expires_at=d.fetched_at + retention,
        ))
    stats["kept"] = len(documents)
    return CleanResult(documents=documents, stats=stats, replaced_ids=replaced, usd=outcome.usd)
