"""Containment for suspected volume artifacts (yfinance contract rolls).

yfinance front-month futures symbols silently stitch different contracts'
histories at roll, injecting fake volume (diagnosed May 2026: GC=F hit 310x
on May-18; see backtests/VOLUME_FIX*.md). The DATA QUALITY badge and the
RED-tier suppression contain the display/tier path, but the artifact also
poisons the v2 ``volume_dist_ratio`` — the PRIMARY bubble-short gate — and
the classifier's reasoning (2026-06-09: SI=F "Volume 43.2x ... but
directional", vol_dist 58.84).

This module nulls every volume-derived metric in the DECISION payload when
the artifact flag fires, so poisoned values cannot reach any gate or any
classifier reasoning, and writes a running record to
``logs/volume_artifacts.log`` so the root cause can be investigated and
fixed (e.g. a continuous-contract data source).

Policy: do NOT try to correct the number — no data is better than poisoned
data. Mark it unusable, exclude it, and flag it loudly.
"""

from __future__ import annotations

import datetime as dt
import logging
import os

logger = logging.getLogger(__name__)

ARTIFACT_LOG_FILENAME = "volume_artifacts.log"


def is_volume_artifact(volume: dict | None) -> bool:
    """True when the volume analyzer flagged this ticker's volume as a
    suspected data artifact (data_quality == "suspicious_volume")."""
    return (volume or {}).get("data_quality") == "suspicious_volume"


def sanitize_volume_artifacts(
    ticker: str,
    signals: dict,
    date: dt.date,
    logs_dir: str = "logs",
    write_log: bool = True,
) -> bool:
    """Null all volume-derived decision metrics for an artifact-flagged ticker.

    Mutates ``signals`` in place:
      - ``volume["artifact"] = True`` and the raw multiple is preserved under
        ``volume["raw_ratio"]`` (display/badge/logging only).
      - ``market.long_horizon.volume_dist_ratio`` → None (raw value preserved
        under ``raw_volume_dist_ratio``). A null vol_dist FAILS the v2
        ``> 1.0`` short gate, so the ticker is not eligible for a
        bubble_forming short.

    The renderer (utils/token_optimizer.compress_signals) keys off
    ``volume["artifact"]`` to null the volume line in the classifier payload
    and to print the VOLUME DATA UNRELIABLE investigation flag.

    Returns True when the ticker was flagged (and logged), False otherwise.
    """
    volume = signals.get("volume") or {}
    if not is_volume_artifact(volume):
        return False

    raw_ratio = volume.get("ratio")
    volume["artifact"] = True
    volume["raw_ratio"] = raw_ratio

    lh = (signals.get("market") or {}).get("long_horizon")
    raw_vol_dist = None
    if lh is not None:
        raw_vol_dist = lh.get("volume_dist_ratio")
        lh["raw_volume_dist_ratio"] = raw_vol_dist
        lh["volume_dist_ratio"] = None

    logger.warning(
        "[VOLUME ARTIFACT] %s: vol_multiple=%s and vol_dist=%s nulled — "
        "excluded from gates and classification (suspected contract-roll artifact)",
        ticker, raw_ratio, raw_vol_dist,
    )
    if write_log:
        _append_artifact_log(date, ticker, raw_ratio, raw_vol_dist, logs_dir)
    return True


def _append_artifact_log(
    date: dt.date,
    ticker: str,
    raw_ratio: float | None,
    raw_vol_dist: float | None,
    logs_dir: str,
) -> None:
    """Append one line per flagged ticker to logs/volume_artifacts.log."""
    path = os.path.join(logs_dir, ARTIFACT_LOG_FILENAME)
    ratio_s    = f"{raw_ratio:.2f}" if isinstance(raw_ratio, (int, float)) else "n/a"
    vol_dist_s = f"{raw_vol_dist:.2f}" if isinstance(raw_vol_dist, (int, float)) else "n/a"
    line = (
        f"{date.isoformat()} | {ticker} | raw_vol_multiple={ratio_s}x | "
        f"raw_vol_dist={vol_dist_s} | metrics nulled (suspected contract-roll artifact)\n"
    )
    try:
        os.makedirs(logs_dir, exist_ok=True)
        with open(path, "a", encoding="utf-8") as fh:
            fh.write(line)
    except OSError as exc:
        logger.warning("volume artifact log: could not write %s (%s)", path, exc)


def log_artifact_summary(
    date: dt.date, tickers: list[str], logs_dir: str = "logs"
) -> None:
    """Append a per-run summary line so artifact frequency is visible over time."""
    if not tickers:
        return
    path = os.path.join(logs_dir, ARTIFACT_LOG_FILENAME)
    line = (
        f"{date.isoformat()} | SUMMARY | count={len(tickers)} | "
        f"tickers={','.join(tickers)}\n"
    )
    try:
        os.makedirs(logs_dir, exist_ok=True)
        with open(path, "a", encoding="utf-8") as fh:
            fh.write(line)
    except OSError as exc:
        logger.warning("volume artifact log: could not write %s (%s)", path, exc)
