"""Public-site protection (B10).

Step 2.1: the spend limits - the per-run budget error and the daily cap
across all runs (spend table). The run key and the queue arrive with the
API steps.
"""

from __future__ import annotations

from ctxpack.config import get_settings


class BudgetExceeded(RuntimeError):
    """A spend limit was reached. The orchestrator turns this into a partial pack."""


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
