"""Persistent position tracker for directional recommendations.

Manages open/closed positions in tracker/positions.json.
Positions are only added when recommendation is contrarian_buy or reduce_exposure.
P&L is always expressed from the recommendation's perspective:
  - long (contrarian_buy):   pnl = (current - entry) / entry * 100
  - short (reduce_exposure): pnl = (entry - current) / entry * 100
Outcome at d+30:
  correct   = pnl >= +2%
  incorrect = pnl <= -2%
  neutral   = |pnl| < 2%
"""

from __future__ import annotations

import datetime as dt
import json
import logging
import uuid
from pathlib import Path

import yfinance as yf

logger = logging.getLogger(__name__)

TRACKER_DIR = Path(__file__).parent
POSITIONS_FILE = TRACKER_DIR / "positions.json"
NEUTRAL_THRESHOLD = 2.0  # % — within this band = neutral outcome


# ── persistence ────────────────────────────────────────────────────────────

def _load() -> dict:
    if POSITIONS_FILE.exists():
        with open(POSITIONS_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    return {"open": [], "closed": []}


def _save(state: dict) -> None:
    POSITIONS_FILE.parent.mkdir(parents=True, exist_ok=True)
    with open(POSITIONS_FILE, "w", encoding="utf-8") as f:
        json.dump(state, f, indent=2, default=str)


# ── price fetching ─────────────────────────────────────────────────────────

def fetch_price(ticker: str, date: dt.date | None = None) -> float | None:
    """Return closing price for ticker.

    If date is None, returns the most recent close.
    If date is given, returns the last close on or before that date
    (handles weekends / holidays by looking back up to 5 calendar days).
    """
    try:
        t = yf.Ticker(ticker)
        if date is None:
            hist = t.history(period="5d")
        else:
            start = (date - dt.timedelta(days=5)).isoformat()
            end   = (date + dt.timedelta(days=1)).isoformat()
            hist  = t.history(start=start, end=end)
            if not hist.empty:
                # Use .date to avoid tz-aware vs tz-naive comparison errors.
                hist = hist[hist.index.date <= date]
        if hist.empty:
            logger.warning("%s: no price data for %s", ticker, date)
            return None
        return float(hist["Close"].iloc[-1])
    except Exception as exc:
        logger.error("%s: price fetch failed: %s", ticker, exc)
        return None


# ── P&L helpers ────────────────────────────────────────────────────────────

def _pnl(direction: str, entry: float, current: float) -> float:
    if direction == "long":
        return (current - entry) / entry * 100
    return (entry - current) / entry * 100  # short: profit when price falls


def _outcome(pnl_pct: float) -> str:
    if pnl_pct >= NEUTRAL_THRESHOLD:
        return "correct"
    if pnl_pct <= -NEUTRAL_THRESHOLD:
        return "incorrect"
    return "neutral"


def _status(pnl_pct: float) -> str:
    if pnl_pct > NEUTRAL_THRESHOLD:
        return "ON TRACK"
    if pnl_pct < -NEUTRAL_THRESHOLD:
        return "UNDERWATER"
    return "NEUTRAL"


# ── public API ─────────────────────────────────────────────────────────────

def add_position(
    ticker: str,
    direction: str,
    recommendation: str,
    confidence: int,
    reasoning: str,
    entry_price: float,
    entry_date: str,
    macro_context: dict | None = None,
) -> dict:
    """Add a new open position; skips silently if the same ticker + date already exists."""
    state = _load()

    for pos in state["open"]:
        if pos["ticker"] == ticker and pos["entry_date"] == entry_date:
            logger.info("%s already tracked for %s — skipping", ticker, entry_date)
            return pos

    ed = dt.date.fromisoformat(entry_date)
    pos: dict = {
        "id": str(uuid.uuid4()),
        "ticker": ticker,
        "direction": direction,
        "recommendation": recommendation,
        "confidence": confidence,
        "reasoning": reasoning,
        "entry_date": entry_date,
        "entry_price": round(entry_price, 4),
        "macro_context": macro_context or {},
        "d5_target":  (ed + dt.timedelta(days=5)).isoformat(),
        "d10_target": (ed + dt.timedelta(days=10)).isoformat(),
        "d30_target": (ed + dt.timedelta(days=30)).isoformat(),
    }
    state["open"].append(pos)
    _save(state)
    logger.info("added position: %s %s @ %.2f on %s", ticker, direction, entry_price, entry_date)
    return pos


def update_open_positions(date: dt.date) -> list[dict]:
    """Return all open positions enriched with live price metrics.

    Does NOT modify positions.json — call close_expired_positions() for that.
    """
    state = _load()
    enriched = []
    for pos in state["open"]:
        current_price = fetch_price(pos["ticker"])
        if current_price is None:
            current_price = pos["entry_price"]

        entry_date = dt.date.fromisoformat(pos["entry_date"])
        days_held  = (date - entry_date).days
        pnl_pct    = _pnl(pos["direction"], pos["entry_price"], current_price)

        enriched.append({
            **pos,
            "current_price": round(current_price, 2),
            "pnl_pct": round(pnl_pct, 2),
            "days_held": days_held,
            "status": _status(pnl_pct),
        })
    return enriched


def close_expired_positions(date: dt.date) -> list[dict]:
    """Move positions whose d30_target <= date from open to closed.

    Fetches prices at d+5, d+10, and d+30 checkpoints.
    Returns list of newly closed position dicts.
    """
    state      = _load()
    still_open = []
    newly_closed: list[dict] = []

    for pos in state["open"]:
        d30 = dt.date.fromisoformat(pos["d30_target"])
        if date < d30:
            still_open.append(pos)
            continue

        d5  = dt.date.fromisoformat(pos["d5_target"])
        d10 = dt.date.fromisoformat(pos["d10_target"])

        p5  = fetch_price(pos["ticker"], d5)
        p10 = fetch_price(pos["ticker"], d10)
        p30 = fetch_price(pos["ticker"], d30)

        entry = pos["entry_price"]
        pnl_d5  = round(_pnl(pos["direction"], entry, p5),  2) if p5  else None
        pnl_d10 = round(_pnl(pos["direction"], entry, p10), 2) if p10 else None
        pnl_d30 = round(_pnl(pos["direction"], entry, p30), 2) if p30 else None

        closed: dict = {
            "id":           pos["id"],
            "ticker":       pos["ticker"],
            "direction":    pos["direction"],
            "recommendation": pos["recommendation"],
            "confidence":   pos["confidence"],
            "reasoning":    pos["reasoning"],
            "entry_date":   pos["entry_date"],
            "entry_price":  entry,
            "exit_date":    d30.isoformat(),
            "exit_price":   round(p30, 2) if p30 else None,
            "pnl_pct":      pnl_d30,
            "pnl_d5":       pnl_d5,
            "pnl_d10":      pnl_d10,
            "pnl_d30":      pnl_d30,
            "outcome":      _outcome(pnl_d30) if pnl_d30 is not None else "unknown",
            "macro_context": pos.get("macro_context", {}),
        }
        state["closed"].append(closed)
        newly_closed.append(closed)
        logger.info(
            "closed position: %s outcome=%s pnl=%.1f%%",
            pos["ticker"], closed["outcome"], pnl_d30 or 0,
        )

    state["open"] = still_open
    if newly_closed:
        _save(state)
    return newly_closed


def get_open_positions() -> list[dict]:
    """Return raw open positions (no live price enrichment)."""
    return _load()["open"]


def get_recent_closed(n: int = 10) -> list[dict]:
    """Return last n closed positions (oldest-first ordering)."""
    return _load()["closed"][-n:]


def get_aggregate_stats() -> dict:
    """Win rate and avg P&L broken down by recommendation type and confidence band."""
    closed = _load()["closed"]
    if not closed:
        return {
            "total": 0, "correct": 0, "incorrect": 0, "neutral": 0,
            "win_rate": 0.0, "avg_pnl": 0.0,
            "by_recommendation": {}, "by_confidence": {},
        }

    total     = len(closed)
    correct   = sum(1 for p in closed if p.get("outcome") == "correct")
    incorrect = sum(1 for p in closed if p.get("outcome") == "incorrect")
    neutral   = sum(1 for p in closed if p.get("outcome") == "neutral")
    pnls      = [p["pnl_pct"] for p in closed if p.get("pnl_pct") is not None]
    avg_pnl   = sum(pnls) / len(pnls) if pnls else 0.0
    win_rate  = correct / total * 100 if total else 0.0

    # By recommendation type
    by_rec: dict[str, dict] = {}
    for pos in closed:
        rec = pos.get("recommendation", "unknown")
        bucket = by_rec.setdefault(rec, {"total": 0, "correct": 0, "pnls": []})
        bucket["total"] += 1
        if pos.get("outcome") == "correct":
            bucket["correct"] += 1
        if pos.get("pnl_pct") is not None:
            bucket["pnls"].append(pos["pnl_pct"])

    by_rec_out = {
        rec: {
            "total":    d["total"],
            "correct":  d["correct"],
            "win_rate": d["correct"] / d["total"] * 100 if d["total"] else 0.0,
            "avg_pnl":  sum(d["pnls"]) / len(d["pnls"]) if d["pnls"] else 0.0,
        }
        for rec, d in by_rec.items()
    }

    # By confidence band (1–4 = low, 5–7 = mid, 8–10 = high)
    bands: dict[str, list[dict]] = {"1-4": [], "5-7": [], "8-10": []}
    for pos in closed:
        conf = pos.get("confidence", 0)
        if conf <= 4:
            bands["1-4"].append(pos)
        elif conf <= 7:
            bands["5-7"].append(pos)
        else:
            bands["8-10"].append(pos)

    by_conf_out = {}
    for band, positions in bands.items():
        if not positions:
            continue
        b_correct = sum(1 for p in positions if p.get("outcome") == "correct")
        b_pnls    = [p["pnl_pct"] for p in positions if p.get("pnl_pct") is not None]
        by_conf_out[band] = {
            "total":    len(positions),
            "correct":  b_correct,
            "win_rate": b_correct / len(positions) * 100,
            "avg_pnl":  sum(b_pnls) / len(b_pnls) if b_pnls else 0.0,
        }

    return {
        "total":     total,
        "correct":   correct,
        "incorrect": incorrect,
        "neutral":   neutral,
        "win_rate":  round(win_rate, 1),
        "avg_pnl":   round(avg_pnl, 2),
        "by_recommendation": by_rec_out,
        "by_confidence":     by_conf_out,
    }
