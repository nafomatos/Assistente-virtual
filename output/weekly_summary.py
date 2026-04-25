"""Parse the week's archived log files and build a structured weekly summary.

Reads logs/YYYY-MM-DD.txt for each trading day (Mon-Fri) of the given week,
extracts RED/AMBER alert data, volume spikes, and macro evolution, and returns
a structured dict consumed by the email builder and narrative generator.
"""

from __future__ import annotations

import datetime as dt
import logging
import os
import re

logger = logging.getLogger(__name__)

# ── Log-parsing patterns ───────────────────────────────────────────────────

_RE_FG = re.compile(r"Fear & Greed: (\d+)/100")
_RE_BUFFETT = re.compile(r"Buffett Indicator: ([\d.]+)%\s*[—\-]+\s*([\w ]+?)\s*\(")
_RE_RED = re.compile(r"\[RED\]:\s*(.*)")
_RE_AMBER = re.compile(r"\[AMBER\]:\s*(.*)")

# Matches rows in the [TICKER ALERT TIERS] section, e.g.:
#   GC=F | 28.1x | +0.3 | +0.1 | 47 | RED: vol=28.1x (extreme >5x)
_RE_TIER_ROW = re.compile(
    r"^\s{1,6}(\S+)\s*\|\s*([\d.]+)x\s*\|\s*([+-]?[\d.]+)\s*\|\s*"
    r"([+-]?[\d.]+)\s*\|\s*([\d.]+|N/A)\s*\|\s*(RED|AMBER|SKIP):",
    re.MULTILINE,
)


# ── Helpers ────────────────────────────────────────────────────────────────

def _monday_of_week(date: dt.date) -> dt.date:
    return date - dt.timedelta(days=date.weekday())


def _parse_tickers(raw: str) -> list[str]:
    if not raw or not raw.strip():
        return []
    return [t.strip() for t in raw.split(",") if t.strip() and t.strip().lower() != "none"]


def _parse_log_file(path: str) -> dict | None:
    """Parse a single daily log file.

    Returns a dict with keys:
        fear_greed_score, buffett_pct, buffett_class,
        red_tickers, amber_tickers,
        ticker_signals: {ticker: {vol_ratio, z30, z200, rsi, tier}}
    Returns None if the file cannot be read or parsed at all.
    """
    try:
        with open(path, "r", encoding="utf-8") as fh:
            text = fh.read()
    except OSError:
        logger.warning(f"Cannot read log file: {path}")
        return None

    result: dict = {
        "fear_greed_score": None,
        "buffett_pct": None,
        "buffett_class": None,
        "red_tickers": [],
        "amber_tickers": [],
        "ticker_signals": {},
    }

    m = _RE_FG.search(text)
    if m:
        result["fear_greed_score"] = int(m.group(1))

    m = _RE_BUFFETT.search(text)
    if m:
        result["buffett_pct"] = float(m.group(1))
        result["buffett_class"] = m.group(2).strip()

    m = _RE_RED.search(text)
    if m:
        result["red_tickers"] = _parse_tickers(m.group(1))

    m = _RE_AMBER.search(text)
    if m:
        result["amber_tickers"] = _parse_tickers(m.group(1))

    for row in _RE_TIER_ROW.finditer(text):
        ticker, vol, z30, z200, rsi_raw, tier = row.groups()
        rsi = None if rsi_raw.upper() == "N/A" else float(rsi_raw)
        result["ticker_signals"][ticker] = {
            "vol_ratio": float(vol),
            "z30": float(z30),
            "z200": float(z200),
            "rsi": rsi,
            "tier": tier.lower(),
        }

    return result


# ── Public entry point ─────────────────────────────────────────────────────

def generate_weekly_summary(logs_dir: str, week_end_date: dt.date) -> dict:
    """Read Mon–Fri log files and return a structured weekly summary.

    Returns an empty dict if no log files are found for the week (the caller
    should log a warning and skip the weekly send in that case).

    Returned keys
    -------------
    days_analyzed   : int — how many trading days had data
    total_signals   : int — total RED+AMBER alerts across the week
    asset_frequency : dict[str, int] — ticker → days it flagged (desc order)
    highest_volume  : list[dict] — top 3: {ticker, date, ratio}
    macro_evolution : dict — fg/buffett for first and last day
    dynamic_changes : dict — {promoted: [], demoted: []} (not in log files)
    red_alerts      : list[dict] — {ticker, date} for every RED alert
    amber_alerts    : list[dict] — {ticker, date} for every AMBER alert
    week_start      : str — ISO date of Monday
    week_end        : str — ISO date of week_end_date
    """
    monday = _monday_of_week(week_end_date)
    trading_days = [
        monday + dt.timedelta(days=i)
        for i in range(5)
        if monday + dt.timedelta(days=i) <= week_end_date
    ]

    parsed: list[tuple[dt.date, dict]] = []
    for day in trading_days:
        log_path = os.path.join(logs_dir, f"{day.isoformat()}.txt")
        if not os.path.isfile(log_path):
            logger.info(f"weekly_summary: no log for {day.isoformat()} — skipping")
            continue
        data = _parse_log_file(log_path)
        if data is not None:
            parsed.append((day, data))

    if not parsed:
        logger.warning(f"weekly_summary: no log files found for week of {monday.isoformat()}")
        return {}

    # ── Asset frequency & alert lists ────────────────────────────────────
    asset_days: dict[str, int] = {}
    red_alerts: list[dict] = []
    amber_alerts: list[dict] = []

    for day, data in parsed:
        seen_today: set[str] = set()
        for ticker in data["red_tickers"]:
            red_alerts.append({"ticker": ticker, "date": day.isoformat()})
            if ticker not in seen_today:
                asset_days[ticker] = asset_days.get(ticker, 0) + 1
                seen_today.add(ticker)
        for ticker in data["amber_tickers"]:
            amber_alerts.append({"ticker": ticker, "date": day.isoformat()})
            if ticker not in seen_today:
                asset_days[ticker] = asset_days.get(ticker, 0) + 1
                seen_today.add(ticker)

    # ── Top volume spikes across all RED/AMBER tickers ────────────────────
    volume_events: list[dict] = []
    for day, data in parsed:
        alert_tickers = set(data["red_tickers"] + data["amber_tickers"])
        for ticker, sig in data["ticker_signals"].items():
            if ticker in alert_tickers:
                volume_events.append(
                    {"ticker": ticker, "date": day.isoformat(), "ratio": sig["vol_ratio"]}
                )
    volume_events.sort(key=lambda x: x["ratio"], reverse=True)
    highest_volume = volume_events[:3]

    # ── Macro evolution ───────────────────────────────────────────────────
    first_day, first_data = parsed[0]
    last_day, last_data = parsed[-1]
    macro_evolution = {
        "fear_greed_start": {
            "date": first_day.isoformat(),
            "score": first_data["fear_greed_score"],
        },
        "fear_greed_end": {
            "date": last_day.isoformat(),
            "score": last_data["fear_greed_score"],
        },
        "buffett_start": {
            "date": first_day.isoformat(),
            "pct": first_data["buffett_pct"],
            "class": first_data["buffett_class"],
        },
        "buffett_end": {
            "date": last_day.isoformat(),
            "pct": last_data["buffett_pct"],
            "class": last_data["buffett_class"],
        },
    }

    return {
        "days_analyzed": len(parsed),
        "total_signals": len(red_alerts) + len(amber_alerts),
        "asset_frequency": dict(
            sorted(asset_days.items(), key=lambda x: x[1], reverse=True)
        ),
        "highest_volume": highest_volume,
        "macro_evolution": macro_evolution,
        "dynamic_changes": {"promoted": [], "demoted": []},
        "red_alerts": red_alerts,
        "amber_alerts": amber_alerts,
        "week_start": monday.isoformat(),
        "week_end": week_end_date.isoformat(),
    }
