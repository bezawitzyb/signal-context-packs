"""The cleaning chain (Step 1.5). No network, no money: LLM_FAKE answers relevance."""

import asyncio
import json
from datetime import date, datetime, timezone

import pytest

from ctxpack.collect.cleaning import (
    Deduper, Draft, clean, hash_author, in_window, make_draft, parse_date, percentile_of,
    redact, spam_reason,
)
from ctxpack.collect.relevance import BriefContext
from ctxpack.config import get_settings
from ctxpack.schemas.enums import DatePrecision as P
from ctxpack.schemas.enums import Platform

NOW = datetime(2026, 10, 4, 12, 0, tzinfo=timezone.utc)
SALT = "test-salt-not-a-secret"


@pytest.fixture
def llm_fake(monkeypatch):
    monkeypatch.setenv("LLM_FAKE", "true")
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


def draft(text, author="someone", platform=Platform.reddit, date_raw="2026-09-30", **kw):
    return make_draft(platform=platform, source_unit="reddit:r/test", url="https://example.com/post",
                      text=text, author=author, date_raw=date_raw, fetched_at=NOW, salt=SALT, **kw)


# --- privacy -----------------------------------------------------------------

@pytest.mark.parametrize("text, expected", [
    ("mail me at jan.devries@gmail.com please", "mail me at [email] please"),
    ("bel +31 6 1234 5678 voor info", "bel [phone] voor info"),
    ("bel me op 06-12345678", "bel me op [phone]"),
    ("ruf an: +49 151 23456789", "ruf an: [phone]"),
    ("Festnetz 030 1234567 ab 9 Uhr", "Festnetz [phone] ab 9 Uhr"),
    ("handy 0151/23456789", "handy [phone]"),
    ("+31 (0)20 123 4567 is ons nummer", "[phone] is ons nummer"),
    ("@jansen_99 zei het al", "[user] zei het al"),
    ("as u/MealPrepKing said", "as [user] said"),
    ("see reddit.com/user/foo_bar for more", "see [user] for more"),
    ("follow https://www.instagram.com/foo.bar/ now", "follow [user] now"),
    ("her tiktok.com/@abc.def is great", "her [user] is great"),
    ("youtube.com/@SomeChannel has recipes", "[user] has recipes"),
])
def test_planted_pii_is_redacted(text, expected):
    out, changed = redact(text)
    assert out == expected and changed


@pytest.mark.parametrize("text", [
    "posted on 04.07.2026 at 9", "costs €12,99 or 1.5 kg", "back in 2026", "#mealprep is life",
    "see instagram.com/p/ABC123 for the recipe", "call me at 5", "order 3 for 20 euro",
])
def test_ordinary_text_is_not_redacted(text):
    assert redact(text) == (text, False)


def test_author_is_hashed_and_never_kept():
    d = draft("I prep every Sunday for the whole week", author="JanJansen1987")
    assert len(d.author_hash) == 64
    assert d.author_hash == hash_author("reddit", "@JanJansen1987", SALT)  # same person, same hash
    assert d.author_hash != hash_author("tiktok", "JanJansen1987", SALT)   # platform in the hash
    assert "JanJansen1987".casefold() not in json.dumps(d.to_cache()).casefold()


def test_no_salt_no_hash():
    with pytest.raises(RuntimeError):
        hash_author("reddit", "someone", "")


def test_tiktok_url_loses_the_handle():
    d = draft("great video about lunch boxes", platform=Platform.tiktok)
    d2 = make_draft(platform=Platform.tiktok, source_unit="tiktok:#x", url="https://www.tiktok.com/@jan.j/video/123",
                    text="x y z w", author="jan.j", date_raw=None, fetched_at=NOW, salt=SALT)
    assert d2.url == "https://www.tiktok.com/@/video/123" and "jan.j" not in d2.url
    assert d.url


def test_normalise_and_cache_round_trip():
    d = draft("  Meal&nbsp;prep​  is   great\r\n\r\n\r\nreally  ")
    assert d.text == "Meal prep is great\n\nreally"
    assert Draft.from_cache(json.loads(json.dumps(d.to_cache()))) == d


# --- dates -------------------------------------------------------------------

DATE_TABLE = [
    # English
    ("2026-07-04T14:29:08.000Z", date(2026, 7, 4), P.day),
    ("2026-07-04 14:53:52", date(2026, 7, 4), P.day),
    ("Jul 4, 2026", date(2026, 7, 4), P.day),
    ("4 July 2026", date(2026, 7, 4), P.day),
    ("3 weeks ago", date(2026, 9, 13), P.day),
    ("1 day ago", date(2026, 10, 3), P.day),
    ("an hour ago", date(2026, 10, 4), P.day),
    ("Streamed 2 days ago", date(2026, 10, 2), P.day),
    ("yesterday", date(2026, 10, 3), P.day),
    ("5d", date(2026, 9, 29), P.day),
    ("2 months ago", date(2026, 8, 4), P.month),
    ("a year ago", date(2025, 10, 4), P.year),
    ("March 2025", date(2025, 3, 1), P.month),
    (1751587200, date(2025, 7, 4), P.day),
    ("1751587200000", date(2025, 7, 4), P.day),
    # Dutch
    ("3 jaar geleden", date(2023, 10, 4), P.year),
    ("2 weken geleden", date(2026, 9, 20), P.day),
    ("1 dag geleden", date(2026, 10, 3), P.day),
    ("5 uur geleden", date(2026, 10, 4), P.day),
    ("een maand geleden", date(2026, 9, 4), P.month),
    ("gisteren", date(2026, 10, 3), P.day),
    ("eergisteren", date(2026, 10, 2), P.day),
    ("vandaag", date(2026, 10, 4), P.day),
    ("4 juli 2026", date(2026, 7, 4), P.day),
    ("04-07-2026", date(2026, 7, 4), P.day),
    ("maart 2025", date(2025, 3, 1), P.month),
    # German
    ("vor 2 Monaten", date(2026, 8, 4), P.month),
    ("vor 3 Wochen", date(2026, 9, 13), P.day),
    ("vor einem Tag", date(2026, 10, 3), P.day),
    ("vor 5 Stunden", date(2026, 10, 4), P.day),
    ("vor einem Jahr", date(2025, 10, 4), P.year),
    ("gestern", date(2026, 10, 3), P.day),
    ("vorgestern", date(2026, 10, 2), P.day),
    ("heute", date(2026, 10, 4), P.day),
    ("04.07.2026", date(2026, 7, 4), P.day),
    ("4. Juli 2026", date(2026, 7, 4), P.day),
    ("März 2025", date(2025, 3, 1), P.month),
    # Unknown
    ("", None, P.unknown),
    (None, None, P.unknown),
    ("sometime", None, P.unknown),
    ("31.02.2026", None, P.unknown),
]


@pytest.mark.parametrize("raw, expected, precision", DATE_TABLE)
def test_date_table(raw, expected, precision):
    assert parse_date(raw, NOW) == (expected, precision)


def test_window():
    assert in_window(date(2026, 4, 7), P.day, NOW, 180)         # cutoff day itself stays
    assert not in_window(date(2026, 4, 6), P.day, NOW, 180)
    assert in_window(date(2026, 4, 1), P.month, NOW, 180)       # April overlaps the window
    assert not in_window(date(2025, 1, 1), P.year, NOW, 180)
    assert in_window(None, P.unknown, NOW, 180)                 # undated: kept, flagged


# --- de-duplication ----------------------------------------------------------

LONG = ("I started meal prepping on Sundays because weekday dinners kept turning into "
        "takeaway and my budget could not handle it any more so now I cook rice and chicken")


def test_exact_and_near_duplicates_are_dropped():
    dd = Deduper()
    assert dd.check("a", LONG, 5) == (True, None)
    assert dd.check("b", "  " + LONG.upper() + " ", 1) == (False, None)              # exact (case/space)
    assert dd.check("c", LONG.replace("chicken", "tofu"), 1) == (False, None)        # near-duplicate
    assert dd.check("d", "Totally different post about lunch boxes for kids at school", 1) == (True, None)


def test_higher_engagement_copy_wins():
    dd = Deduper([("stored", LONG, 2.0)])
    assert dd.check("new", LONG + " too", 50.0) == (True, "stored")
    assert dd.check("again", LONG, 10.0) == (False, None)


# --- spam and short form -------------------------------------------------------

def test_two_word_slang_is_kept_as_short_form():
    d = draft("girl dinner fr")
    assert d.short_form and spam_reason(d, set()) is None
    assert draft("😂😂😂").short_form and spam_reason(draft("😂😂😂"), set()) is None
    assert not draft("this is so good").short_form


@pytest.mark.parametrize("text, reason", [
    ("https://bit.ly/abc", "link_only"),
    ("great recipe " + " ".join(f"#tag{i}" for i in range(9)), "hashtag_flood"),
    ("😂" * 20 + " this is so good", "emoji_flood"),
    ("Love this one! Use code SAVE20 for 20% off", "promo"),
    ("Nieuwe recepten staan online, link in bio voor meer", "promo"),
    ("Mit dem Rabattcode SPAREN bekommst du zehn Prozent", "promo"),
])
def test_spam(text, reason):
    assert spam_reason(draft(text), set()) == reason


def test_repeat_author_spam():
    seen: set = set()
    assert spam_reason(draft("Check my store for great deals 1 https://a.b/1", author="shop"), seen) is None
    assert spam_reason(draft("Check my store for great deals 2 https://a.b/2", author="shop"), seen) == "repeat_author"
    assert spam_reason(draft("Check my store for great deals 3", author="other"), seen) is None


def test_percentile():
    assert percentile_of(None, [1, 2]) is None
    assert percentile_of(10, [1, 5, 10, 20]) == 62.5


# --- the whole chain ---------------------------------------------------------

def test_clean_chain(llm_fake):
    brief = BriefContext(topic="meal prep", market="NL", languages=["nl", "en"],
                         research_questions={"RQ1": "Why do people meal prep?"})
    drafts = [
        draft("I meal prep on Sunday to save money, mail me jan@x.nl", author="JanJansen1987",
              engagement={"upVotes": 40}),
        draft("I meal prep on Sunday to save money, mail me jan@x.nl", author="Copycat",
              engagement={"upVotes": 1}),                                           # duplicate
        draft("girl dinner fr", author="a2", engagement={"upVotes": 3}),            # short form
        draft("Unrelated post about football results this weekend", author="a3"),   # not relevant
        draft("Love this! Use code SAVE20 for 20% off meal prep boxes", author="a4"),  # spam
        draft("meal prep in 2019 was different", author="a5", date_raw="2019-05-01"),  # out of window
        draft("meal prep without a date still counts here", author="a6", date_raw=None),  # undated
    ]
    result = asyncio.run(clean(drafts, run_id="RUN-1", window_days=180, brief=brief, deduper=Deduper()))
    s = result.stats
    assert (s["collected"], s["duplicate"], s["spam"], s["out_of_window"]) == (7, 1, 1, 1)
    assert s["kept"] == 4 and s["short_form"] == 1 and s["undated"] == 1 and s["redacted"] >= 2
    by_text = {d.text: d for d in result.documents}
    first = by_text["I meal prep on Sunday to save money, mail me [email]"]
    assert first.is_relevant and first.research_question_ids == ["RQ1"] and first.redacted
    assert first.engagement_percentile is not None
    assert first.relevance_reason == "on_topic" and first.is_promotional is False
    assert first.market_match is None                  # fake worker: "cannot tell"
    assert by_text["girl dinner fr"].short_form
    assert not by_text["Unrelated post about football results this weekend"].is_relevant
    assert by_text["meal prep without a date still counts here"].date_precision == P.unknown
    dumped = json.dumps([d.model_dump(mode="json") for d in result.documents]).casefold()
    for name in ("janjansen1987", "copycat", "jan@x.nl"):
        assert name not in dumped
    assert result.usd == 0.0


@pytest.mark.parametrize("text, expected", [
    ("Zitat geschrieben von smaragd  Danke dir", "Zitat geschrieben von [user]  Danke dir"),
    ("Zitat von Heizer77: das stimmt", "Zitat von [user]: das stimmt"),
    ("Citaat van Marieke: klopt", "Citaat van [user]: klopt"),
    ("Marieke schreef op 12 mei 2025: ik ook", "[user] schreef op 12 mei 2025: ik ook"),
    ("Heizer77 schrieb: genau", "[user] schrieb: genau"),
    ("Quote from bob_k: agreed", "Quote from [user]: agreed"),
    ("jane wrote: yes", "[user] wrote: yes"),
    ("Originally posted by Sam1 nope", "Originally posted by [user] nope"),
])
def test_forum_quote_headers_are_redacted(text, expected):
    assert redact(text) == (expected, True)


def test_known_page_names_are_redacted():
    out, changed = redact("Ik ben het eens met Marieke en marieke93 hier", ["Marieke", "marieke93", "x"])
    assert out == "Ik ben het eens met [user] en [user] hier" and changed


@pytest.mark.parametrize("text", ["Hij zei dat het lekker was", "she said it was fine", "Zitat ist gut"])
def test_quote_header_rule_leaves_normal_text(text):
    assert redact(text) == (text, False)


# --- first names written inside a post (Step 3.7 privacy fix) ---------------------------

import pytest as _pytest  # noqa: E402

from ctxpack.collect.cleaning import redact as _redact  # noqa: E402


@_pytest.mark.parametrize("text,expected", [
    ("Mijn man Hans en ik verdienen niet zo veel", "Mijn man [name] en ik verdienen niet zo veel"),
    ("m'n vriendin Ans vindt het vies", "m'n vriendin [name] vindt het vies"),
    ("Bedankt Oscar,\n\nVeel snacks.\n\nHartelijke groet,\nLaura", "Bedankt [name],\n\nVeel snacks.\n\nHartelijke groet,\n[name]"),
    ("My husband Tom loves chips", "My husband [name] loves chips"),
    ("Thanks Sarah!", "Thanks [name]!"),
    ("Meine Frau Petra isst gern Chips.\nViele Grüße\nKlaus", "Meine Frau [name] isst gern Chips.\nViele Grüße\n[name]"),
    ("Liefs, Ans", "Liefs, [name]"),
    ("Gr Bea en Hans en de kids", "Gr Bea en Hans en de kids"),                  # no cue: left alone ...
    ("Gr [user] en Hans en de kids", "Gr [user] en [name] en de kids"),          # ... but joined to a redacted name
])
def test_first_names_in_the_post_are_redacted(text, expected):
    assert _redact(text)[0] == expected


@_pytest.mark.parametrize("text", [
    "Hoi allemaal, ik eet graag Lays", "Hi All, Croky is better", "Groetjes van mij", "mijn man vindt het lekker",
    "Thanks for the tip, Albert Heijn has it", "Lidl en AH naast elkaar", "Beste chips ooit: Croky",
])
def test_ordinary_text_is_left_alone(text):
    assert _redact(text) == (text, False)


# --- escaped emoji and forum image markup (Day 5 data fix) --------------------------------

from ctxpack.collect.cleaning import normalise_text as _normalise  # noqa: E402


@_pytest.mark.parametrize("raw,expected", [
    (r"\ud83d\udc40 A few simple swaps", "👀 A few simple swaps"),
    (r"love it \ud83c\udf6b\ud83c\udf7f", "love it 🍫🍿"),
    ("De chips ![:9~](http://i.fok.nl/s/kwijl.gif) lekker", "De chips :9~ lekker"),
    ("![](https://example.com/a.png) foto", "foto"),
    (r"caf\u00e9", "café"),
    (r"half \ud83d emoji", "half emoji"),
    (r"a path C:\users stays", r"a path C:\users stays"),
    ("normal [link](https://x.nl) stays", "normal [link](https://x.nl) stays"),   # only images are unwrapped
])
def test_escaped_emoji_and_image_markup_become_what_the_reader_saw(raw, expected):
    assert _normalise(raw) == expected
