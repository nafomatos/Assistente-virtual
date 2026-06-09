"""Cluster signal booster — detects when 3+ tickers from the same sector
receive same-direction classifications within a rolling business-day window.

Signal logs are read from logs/signals_YYYY-MM-DD.json files, which are
saved by the pipeline when CLUSTER_BOOST_ENABLED=true.

Each signal file has the shape:
  {
    "date": "YYYY-MM-DD",
    "signals": [
      {
        "ticker": "NVDA",
        "classification": "bubble_forming",
        "recommendation": "reduce_exposure",
        "confidence": 8,
        "reasoning": "..."
      },
      ...
    ]
  }
"""

from __future__ import annotations

import datetime as dt
import json
import logging
import os

from tracker.sectors import get_direction_group, get_sector

logger = logging.getLogger(__name__)

_CLUSTER_THRESHOLD_SMALL = 3
_CLUSTER_THRESHOLD_LARGE = 5


def _last_business_days(reference_date: dt.date, n: int) -> list[dt.date]:
    """Return the last *n* Mon-Fri dates ending at reference_date (inclusive)."""
    days: list[dt.date] = []
    current = reference_date
    while len(days) < n:
        if current.weekday() < 5:  # Mon=0 … Fri=4
            days.append(current)
        current -= dt.timedelta(days=1)
    return days


def detect_clusters(
    days_window: int = 5,
    logs_dir: str = "logs",
    reference_date: dt.date | None = None,
) -> list[dict]:
    """Scan the last *days_window* business days and return active clusters.

    reference_date defaults to today; tests can inject a fixed date.
    days_window counts BUSINESS DAYS, not calendar days.
    Reads files matching pattern: {logs_dir}/signals_YYYYMMDD.json
    Missing log files for a given date are silently skipped (not an error).

    Returns list of dicts:
      {
        "sector": str,
        "direction_group": str,
        "tickers": list[str],       # sorted, unique
        "count": int,
        "boost": int,               # +1 for 3-4 tickers, +2 for 5+
        "first_seen": str,          # YYYY-MM-DD
        "last_seen": str,           # YYYY-MM-DD
      }
    """
    if reference_date is None:
        reference_date = dt.date.today()

    window_dates = _last_business_days(reference_date, days_window)

    # cluster_data[sector][direction_group][ticker] = [date_str, ...]
    cluster_data: dict[str, dict[str, dict[str, list[str]]]] = {}
    unmapped_tickers: set[str] = set()

    for day in window_dates:
        log_path = os.path.join(logs_dir, f"signals_{day.isoformat()}.json")
        if not os.path.exists(log_path):
            continue
        try:
            with open(log_path, "r", encoding="utf-8") as fh:
                data = json.load(fh)
        except (json.JSONDecodeError, OSError) as exc:
            logger.warning("cluster_detector: skipping %s (%s)", log_path, exc)
            continue

        for signal in data.get("signals", []):
            ticker = signal.get("ticker", "")
            classification = signal.get("classification", "")
            recommendation = signal.get("recommendation", "")

            sector = get_sector(ticker)
            direction = get_direction_group(classification, recommendation)
            if sector is None or direction is None:
                # A directional signal on a ticker with no sector mapping can
                # never join a cluster — surface it so the map gets extended.
                if ticker and sector is None and direction is not None:
                    unmapped_tickers.add(ticker)
                continue

            cluster_data.setdefault(sector, {}).setdefault(direction, {}).setdefault(
                ticker, []
            )
            date_str = day.isoformat()
            if date_str not in cluster_data[sector][direction][ticker]:
                cluster_data[sector][direction][ticker].append(date_str)

    if unmapped_tickers:
        logger.warning(
            "cluster_detector: no sector mapping for signalling ticker(s): %s "
            "— add them to tracker/sectors.SECTOR_MAP to include in clustering",
            ", ".join(sorted(unmapped_tickers)),
        )

    results: list[dict] = []
    for sector, directions in cluster_data.items():
        for direction, ticker_dates in directions.items():
            count = len(ticker_dates)
            if count < _CLUSTER_THRESHOLD_SMALL:
                continue

            all_dates: list[str] = sorted(
                {d for dates in ticker_dates.values() for d in dates}
            )
            boost = 1 if count < _CLUSTER_THRESHOLD_LARGE else 2

            results.append(
                {
                    "sector": sector,
                    "direction_group": direction,
                    "tickers": sorted(ticker_dates.keys()),
                    "count": count,
                    "boost": boost,
                    "first_seen": all_dates[0],
                    "last_seen": all_dates[-1],
                }
            )

    return results


def apply_cluster_boosts(signals: list[dict], clusters: list[dict]) -> list[dict]:
    """Boost the confidence of classified signals that belong to an active cluster.

    Mutates ``signals`` in place and returns the list. Each boosted signal gets
    a ``cluster_boost`` annotation (sector, direction_group, count,
    original_confidence, boost_amount) for the email/report and sizing.

    Signals whose confidence was capped by the macro fear gate
    (``v2_gate.action == "confidence_capped"``) are never boosted — boosting a
    capped bubble short back above MIN_SHORT_CONFIDENCE would silently defeat
    the cap.

    Freshness guard: a signal is only boosted by a cluster it is itself a
    member of. Today's signals are persisted before detect_clusters() runs, so
    a signal that genuinely belongs to the pattern always appears in the
    cluster's ticker list; a sector/direction match without membership means
    the cluster was built entirely from other days' signals and today's signal
    was never verified against it.
    """
    for signal in signals or []:
        ticker = signal.get("ticker", "")
        gate = signal.get("v2_gate") or {}
        if gate.get("action") == "confidence_capped":
            logger.info(
                "[CLUSTER BOOST] %s skipped — confidence capped by v2 gate (%s)",
                ticker, gate.get("rule"),
            )
            continue

        sector = get_sector(ticker)
        direction = get_direction_group(
            signal.get("classification", ""),
            signal.get("recommendation", ""),
        )
        if sector is None or direction is None:
            continue

        for cluster in clusters:
            if cluster["sector"] == sector and cluster["direction_group"] == direction:
                if ticker not in cluster.get("tickers", []):
                    logger.info(
                        "[CLUSTER BOOST] %s skipped — matches %s/%s but is not a "
                        "cluster member (stale or unverified cluster)",
                        ticker, sector, direction,
                    )
                    continue
                original = signal.get("confidence", 0)
                boosted = min(original + cluster["boost"], 10)
                signal["cluster_boost"] = {
                    "sector": sector,
                    "direction_group": direction,
                    "count": cluster["count"],
                    "original_confidence": original,
                    "boost_amount": cluster["boost"],
                }
                signal["confidence"] = boosted
                logger.info(
                    "[CLUSTER BOOST] %s %s %s: %d -> %d (+%d, %d tickers)",
                    ticker, sector, direction,
                    original, boosted, cluster["boost"], cluster["count"],
                )
                break
    return signals


if __name__ == "__main__":
    import sys

    logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
    clusters = detect_clusters()
    if not clusters:
        print("No active clusters detected.")
        sys.exit(0)
    for c in clusters:
        days_span = (
            dt.date.fromisoformat(c["last_seen"]) - dt.date.fromisoformat(c["first_seen"])
        ).days + 1
        print(
            f"\n[CLUSTER] {c['sector']} · {c['direction_group']} · "
            f"{c['count']} tickers in {days_span} days (boost +{c['boost']})"
        )
        print(f"  tickers   : {', '.join(c['tickers'])}")
        print(f"  first_seen: {c['first_seen']}")
        print(f"  last_seen : {c['last_seen']}")
