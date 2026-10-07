"""Public-site protection (B10).

Spend limits (the per-run budget error and the daily cap across all runs),
the run key (constant-time compare, never logged or echoed) and the queue
limit. Reading packs never needs the key; starting runs always does.
"""

from __future__ import annotations

import secrets

import logging

from ctxpack.config import get_settings, load_yaml

log = logging.getLogger(__name__)


class BudgetExceeded(RuntimeError):
    """A spend limit was reached. The orchestrator turns this into a partial pack."""


class StopRequested(Exception):
    """The Stop button was pressed; package what exists."""


class DailyCapReached(BudgetExceeded):
    """DAILY_SPEND_CAP_USD reached for today (all runs, Apify + Anthropic)."""


def daily_cap_usd() -> float:
    return get_settings().daily_spend_cap_usd


def daily_spend_left() -> float:
    from ctxpack import db

    return max(0.0, daily_cap_usd() - db.spend_today())


def check_daily_cap() -> None:
    """Raise DailyCapReached if today's spend has reached the cap. Called before every paid call."""
    if daily_spend_left() <= 0:
        raise DailyCapReached(f"daily spend cap of ${daily_cap_usd():.2f} reached - try again tomorrow")


class GuardError(Exception):
    """A request refused by a guard. `status` is the HTTP status; the message is safe to show."""

    def __init__(self, status: int, message: str):
        super().__init__(message)
        self.status = status
        self.message = message


GUEST_KEY_MIN_CHARS = 16  # a shorter guest key is ignored: too easy to guess


def _matches(given: str, expected) -> bool:
    value = expected.get_secret_value().strip() if expected is not None else ""
    return bool(value) and secrets.compare_digest(given.encode(), value.encode())


def check_run_key(given: str | None) -> None:
    """The run key must match RUN_KEY, or GUEST_RUN_KEY while that is set (constant-time).

    GUEST_RUN_KEY is temporary access for a tester: deleting it in Render revokes it without touching
    RUN_KEY. If RUN_KEY is not set, nobody can start runs (a guest key alone opens nothing).
    """
    settings = get_settings()
    if not settings.is_set("RUN_KEY"):
        if settings.offline:  # keyless local demo: recorded data and the fake model, nothing is paid
            return
        raise GuardError(503, "starting runs is switched off on this server")
    key = (given or "").strip()
    if key and _matches(key, settings.run_key):
        return
    guest = settings.guest_run_key
    if key and guest is not None and len(guest.get_secret_value().strip()) >= GUEST_KEY_MIN_CHARS \
            and _matches(key, guest):
        log.info("run started with the guest key")
        return
    raise GuardError(401, "a valid run key is needed to start runs (header X-API-Key)")


def check_can_queue() -> None:
    """Daily cap and queue size, checked before any paid call for a new run."""
    from ctxpack import db
    from ctxpack.schemas.enums import RunStatus

    if daily_spend_left() <= 0:
        raise GuardError(429, f"today's spend cap of ${daily_cap_usd():.2f} is reached - featured packs still "
                              "work; new runs can start again tomorrow")
    if len(db.runs_with_status(RunStatus.queued)) >= load_yaml("modes")["queue_max"]:
        raise GuardError(429, "queue full - try again in a few minutes")
