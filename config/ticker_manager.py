"""Manages the three-tier dynamic ticker list.

Tiers:
  permanent — original 18 tickers + promoted dynamic tickers
  dynamic   — discovered via trending sources; promoted to permanent after
              DYNAMIC_PROMOTION_THRESHOLD RED/AMBER triggers within 30 days
  inactive  — non-original-18 permanent tickers that have been flat for
              FLAT_DEMOTION_THRESHOLD consecutive days; paused, not deleted

State persists in config/active_tickers.json.
Falls back to ALL_TICKERS if that file is missing or corrupted.

JSON schema:
{
  "permanent": ["NVDA", "TSLA", ...],
  "dynamic": {
    "GME": {"added": "2026-04-21", "triggers": 1, "last_trigger": "2026-04-21"}
  },
  "inactive": {
    "RDDT": {"reason": "30d_flat", "since": "2026-05-01"}
  },
  "flat_streak": {
    "RDDT": 28
  }
}
"""

from __future__ import annotations

import datetime as dt
import json
import logging
import os

logger = logging.getLogger(__name__)

_STATE_FILE = os.path.join(os.path.dirname(__file__), "active_tickers.json")

# The original 18 tickers are permanently protected — auto-demotion never applies.
ORIGINAL_18: frozenset[str] = frozenset([
    "NVDA", "TSLA", "AAPL", "AMZN", "GOOGL", "PLTR", "RKLB", "ASTS",
    "MU", "SOFI", "MSTR", "RDDT",
    "GC=F", "SI=F", "CL=F", "HG=F", "ZS=F", "NG=F",
])


# ── state I/O ──────────────────────────────────────────────────────────────

def _load() -> dict:
    try:
        with open(_STATE_FILE, "r", encoding="utf-8") as f:
            state = json.load(f)
        assert isinstance(state.get("permanent"), list)
        assert isinstance(state.get("dynamic"), dict)
        assert isinstance(state.get("inactive"), dict)
        assert isinstance(state.get("flat_streak"), dict)
        return state
    except (FileNotFoundError, json.JSONDecodeError, AssertionError, OSError) as e:
        logger.warning(
            f"ticker_manager: could not load {_STATE_FILE} ({e}) "
            f"— falling back to ALL_TICKERS"
        )
        from config import ALL_TICKERS
        return {
            "permanent":   list(ALL_TICKERS),
            "dynamic":     {},
            "inactive":    {},
            "flat_streak": {},
        }


def _save(state: dict) -> None:
    try:
        os.makedirs(os.path.dirname(_STATE_FILE), exist_ok=True)
        with open(_STATE_FILE, "w", encoding="utf-8") as f:
            json.dump(state, f, indent=2)
    except OSError as e:
        logger.error(f"ticker_manager: could not save state: {e}")


# ── public API ─────────────────────────────────────────────────────────────

def get_active_tickers() -> list[str]:
    """Return all tickers to process: permanent (minus inactive) + dynamic."""
    state = _load()
    inactive = set(state.get("inactive", {}).keys())
    active = [t for t in state["permanent"] if t not in inactive]
    active += list(state["dynamic"].keys())
    return active


def record_trigger(ticker: str, date: str) -> bool:
    """Increment RED/AMBER trigger count for a dynamic ticker.

    Promotes the ticker to permanent if it reaches DYNAMIC_PROMOTION_THRESHOLD
    triggers within 30 days of first being added.

    Has no effect if the ticker is not in the dynamic list.
    Returns True if the ticker was promoted.
    """
    from config import DYNAMIC_PROMOTION_THRESHOLD
    state = _load()
    dyn = state["dynamic"]
    if ticker not in dyn:
        return False

    entry = dyn[ticker]
    entry["triggers"] += 1
    entry["last_trigger"] = date

    added = dt.date.fromisoformat(entry["added"])
    today = dt.date.fromisoformat(date)
    days_since_added = (today - added).days

    if entry["triggers"] >= DYNAMIC_PROMOTION_THRESHOLD and days_since_added <= 30:
        state["permanent"].append(ticker)
        del state["dynamic"][ticker]
        state["flat_streak"].pop(ticker, None)
        _save(state)
        logger.info(
            f"ticker_manager: {ticker} promoted to permanent "
            f"({entry['triggers']} triggers in {days_since_added}d)"
        )
        return True

    _save(state)
    return False


def record_flat(ticker: str, date: str) -> bool:
    """Increment the consecutive flat-day counter for a permanent ticker.

    Demotes non-ORIGINAL_18 permanent tickers to inactive after
    FLAT_DEMOTION_THRESHOLD flat days. The original 18 are never auto-demoted.
    Has no effect on dynamic tickers (handled by remove_stale_dynamic).
    Returns True if the ticker was demoted.
    """
    from config import FLAT_DEMOTION_THRESHOLD
    state = _load()

    if ticker not in state["permanent"]:
        return False
    if ticker in ORIGINAL_18:
        return False

    streak = state["flat_streak"].get(ticker, 0) + 1
    state["flat_streak"][ticker] = streak

    if streak >= FLAT_DEMOTION_THRESHOLD:
        state["inactive"][ticker] = {"reason": "30d_flat", "since": date}
        state["flat_streak"].pop(ticker, None)
        _save(state)
        logger.info(f"ticker_manager: {ticker} demoted to inactive (flat for {streak}d)")
        return True

    _save(state)
    return False


def record_signal(ticker: str, date: str) -> None:  # noqa: ARG001
    """Reset the flat-day counter for any ticker that triggered an alert."""
    state = _load()
    if ticker in state.get("flat_streak", {}):
        del state["flat_streak"][ticker]
        _save(state)


def add_dynamic_ticker(ticker: str, date: str) -> bool:
    """Add a ticker to the dynamic list if not already tracked.

    Respects the MAX_DYNAMIC_TICKERS cap.
    Returns True if actually added.
    """
    from config import MAX_DYNAMIC_TICKERS
    state = _load()

    all_tracked = (
        set(state["permanent"])
        | set(state["dynamic"].keys())
        | set(state["inactive"].keys())
    )
    if ticker in all_tracked:
        return False

    if len(state["dynamic"]) >= MAX_DYNAMIC_TICKERS:
        logger.debug(
            f"ticker_manager: dynamic cap ({MAX_DYNAMIC_TICKERS}) reached, skipping {ticker}"
        )
        return False

    state["dynamic"][ticker] = {
        "added":        date,
        "triggers":     0,
        "last_trigger": None,
    }
    _save(state)
    logger.info(f"ticker_manager: added {ticker} to dynamic list")
    return True


def remove_stale_dynamic(days: int = 7) -> list[str]:
    """Remove dynamic tickers with 0 triggers that are older than `days` days.

    Returns the list of removed tickers.
    """
    state = _load()
    today = dt.date.today()
    to_remove = [
        ticker for ticker, entry in state["dynamic"].items()
        if entry["triggers"] == 0
        and (today - dt.date.fromisoformat(entry["added"])).days >= days
    ]
    for ticker in to_remove:
        del state["dynamic"][ticker]
        logger.info(f"ticker_manager: removed stale dynamic ticker {ticker} (0 triggers in {days}d)")

    if to_remove:
        _save(state)
    return to_remove


def get_state_summary() -> dict:
    """Return a summary dict for logging and debug output."""
    state = _load()
    return {
        "n_permanent": len(state["permanent"]),
        "n_dynamic":   len(state["dynamic"]),
        "n_inactive":  len(state["inactive"]),
        "dynamic":     dict(state["dynamic"]),
        "inactive":    dict(state["inactive"]),
    }
