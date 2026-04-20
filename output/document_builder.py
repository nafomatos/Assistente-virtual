"""Build a single .txt report you can paste into Claude.ai.

The file has three parts:
  1. Header with today's date, shared macro context (Fear & Greed, VIX Structure,
     Buffett Indicator), and the cached system prompt.
  2. One section per asset that passes the alert tier filter — Red alerts first,
     then Amber — each labelled [RED] or [AMBER].
  3. A closing instruction asking Claude to return JSON recommendations.
"""

from __future__ import annotations

import datetime as dt
import logging
import os

from claude_advisor.prompts import SYSTEM_PROMPT
from collectors.fear_greed import format_summary as format_fear_greed
from config import TICKER_NAMES
from utils.token_optimizer import compress_signals

logger = logging.getLogger(__name__)

OUTPUT_DIR = "output"

# Amber thresholds — below Red but above normal noise
AMBER_ZSCORE_THRESHOLD = 1.5
AMBER_VOL_THRESHOLD = 1.5
AMBER_SOCIAL_ZSCORE_THRESHOLD = 2.0


def get_alert_tier(signals: dict) -> str | None:
    """Return 'red', 'amber', or None.

    Red  — extreme volume (>5x) OR macro_extreme (both |z_30d|>2 AND |z_200d|>2).
    Amber — |z_30d|>1.5 AND vol>1.5x; OR vol>2.5x alone; OR RSI>75/RSI<25;
             OR social_heat_zscore>2.0 with any volume >1.0x.
    Red takes priority; an asset cannot be both.
    """
    vol_class = signals["volume"]["classification"]
    vol_ratio = signals["volume"]["ratio"]
    macro_extreme = signals["velocity"].get("macro_extreme", False)
    z30 = abs(signals["velocity"]["z_score_30d"])
    rsi_val = (signals.get("rsi") or {}).get("rsi")
    heat_z = (signals.get("sentiment") or {}).get("social_heat_zscore")

    # Red: extreme volume or both z-scores exceed 2
    if vol_class == "extreme" or macro_extreme:
        return "red"

    # Amber conditions (any one is sufficient)
    if z30 > AMBER_ZSCORE_THRESHOLD and vol_ratio > AMBER_VOL_THRESHOLD:
        return "amber"
    if vol_class in ("anomalous", "extreme"):
        return "amber"
    if rsi_val is not None and (rsi_val > 75 or rsi_val < 25):
        return "amber"
    if heat_z is not None and heat_z > AMBER_SOCIAL_ZSCORE_THRESHOLD and vol_ratio > 1.0:
        return "amber"

    return None


def passes_prefilter(signals: dict) -> bool:
    """Backward-compatible wrapper — True if the asset has any alert tier."""
    return get_alert_tier(signals) is not None


def get_tier_reason(signals: dict) -> str:
    """Explain which signals triggered the tier, or why the ticker was skipped."""
    vol_class = signals["volume"]["classification"]
    vol_ratio = signals["volume"]["ratio"]
    z30 = signals["velocity"]["z_score_30d"]
    z200 = signals["velocity"]["z_score_200d"]
    macro_extreme = signals["velocity"].get("macro_extreme", False)
    rsi_val = (signals.get("rsi") or {}).get("rsi")
    heat_z = (signals.get("sentiment") or {}).get("social_heat_zscore")

    tier = get_alert_tier(signals)

    if tier == "red":
        reasons = []
        if vol_class == "extreme":
            reasons.append(f"vol={vol_ratio:.1f}x (extreme >5x)")
        if macro_extreme:
            reasons.append(f"macro_extreme(z30={z30:+.1f},z200={z200:+.1f})")
        return "RED: " + "; ".join(reasons)

    if tier == "amber":
        reasons = []
        if abs(z30) > AMBER_ZSCORE_THRESHOLD and vol_ratio > AMBER_VOL_THRESHOLD:
            reasons.append(f"|z30|={abs(z30):.1f}>{AMBER_ZSCORE_THRESHOLD} + vol={vol_ratio:.1f}x")
        if vol_class in ("anomalous", "extreme"):
            reasons.append(f"vol={vol_ratio:.1f}x ({vol_class})")
        if rsi_val is not None and (rsi_val > 75 or rsi_val < 25):
            reasons.append(f"RSI={rsi_val:.0f}")
        if heat_z is not None and heat_z > AMBER_SOCIAL_ZSCORE_THRESHOLD and vol_ratio > 1.0:
            reasons.append(f"social_z={heat_z:+.1f}")
        return "AMBER: " + "; ".join(reasons)

    # Skipped — explain what fell short
    parts = [f"vol={vol_ratio:.1f}x ({vol_class})", f"z30={z30:+.1f},z200={z200:+.1f}"]
    if rsi_val is not None:
        parts.append(f"RSI={rsi_val:.0f}")
    if heat_z is not None:
        parts.append(f"social_z={heat_z:+.1f}")
    return "SKIP: " + "; ".join(parts)


# Keep old name so any external callers don't break
_get_filter_reason = get_tier_reason


def _coverage_line(red: list[str], amber: list[str], skipped: list[str]) -> str:
    total = len(red) + len(amber) + len(skipped)
    return (
        f"Coverage — {total} tickers processed · {len(red)} red · "
        f"{len(amber)} amber · {len(skipped)} filtered\n"
        f"  [RED]:   {', '.join(red) or 'none'}\n"
        f"  [AMBER]: {', '.join(amber) or 'none'}\n"
        f"  skipped: {', '.join(skipped) or 'none'}"
    )


def _debug_summary(results: list[dict]) -> str:
    """Show tier and trigger reason for every ticker."""
    rows = []
    for r in results:
        ticker = r["ticker"]
        signals = r["signals"]
        vol_ratio = signals["volume"]["ratio"]
        z30 = signals["velocity"]["z_score_30d"]
        z200 = signals["velocity"]["z_score_200d"]
        rsi_val = signals["rsi"].get("rsi")
        reason = get_tier_reason(signals)
        rsi_str = f"{rsi_val:.0f}" if rsi_val is not None else "N/A"
        rows.append(
            f"  {ticker} | {vol_ratio:.1f}x | {z30:+.1f} | {z200:+.1f} | {rsi_str} | {reason}"
        )

    if not rows:
        return ""

    header = "[TICKER ALERT TIERS]\n  TICKER | VOL | Z_30D | Z_200D | RSI | TIER/REASON\n"
    return header + "\n".join(rows) + "\n"


def _macro_context_lines(
    fear_greed: dict | None,
    vix_structure: dict | None = None,
    buffett: dict | None = None,
) -> str:
    from collectors.vix_structure import format_summary as fmt_vix
    from collectors.buffett_indicator import format_summary as fmt_buffett
    return (
        f"Macro context — {format_fear_greed(fear_greed)}\n"
        f"               {fmt_vix(vix_structure)}\n"
        f"               {fmt_buffett(buffett)}"
    )


def _header(
    today: dt.date,
    fear_greed: dict | None,
    red: list[str],
    amber: list[str],
    skipped: list[str],
    debug_summary: str = "",
    vix_structure: dict | None = None,
    buffett: dict | None = None,
) -> str:
    macro = _macro_context_lines(fear_greed, vix_structure, buffett)
    coverage = _coverage_line(red, amber, skipped)
    return (
        f"ARTIFICIAL PRICE RADAR — Daily Report {today.isoformat()}\n"
        f"{'=' * 72}\n"
        f"{macro}\n"
        f"{coverage}\n"
        f"{'=' * 72}\n\n"
        f"{debug_summary}"
        f"[SYSTEM PROMPT — paste everything below together into Claude.ai]\n\n"
        f"{SYSTEM_PROMPT.strip()}\n"
    )


def _asset_section(ticker: str, signals: dict, tier: str) -> str:
    name = TICKER_NAMES.get(ticker, ticker)
    label = f"[{tier.upper()}]"
    body = compress_signals(ticker, name, signals)
    body = body.replace("\n\nAnalyze and respond in JSON.", "").rstrip()
    # Inject tier label into the first "Asset:" line
    body = body.replace(f"Asset: {ticker} ({name})", f"Asset: {label} {ticker} ({name})", 1)
    return f"{'-' * 72}\n{body}\n"


def _closing_instruction(n_assets: int) -> str:
    return (
        f"\n{'=' * 72}\n"
        f"[INSTRUCTION]\n\n"
        f"Analyze each of the {n_assets} asset(s) above and respond with a single "
        f"JSON array. Each element must follow this exact schema:\n\n"
        f"{{\n"
        f'  "ticker": "...",\n'
        f'  "classification": "bubble_forming|irrational_panic|silent_accumulation|ambiguous|no_signal",\n'
        f'  "recommendation": "contrarian_buy|reduce_exposure|wait|no_action",\n'
        f'  "reasoning": "2-3 short sentences, under 400 characters total",\n'
        f'  "confidence": <integer 1-10>\n'
        f"}}\n\n"
        f"Return ONLY the JSON array, no prose, no markdown fences.\n"
    )


def build_document(
    results: list[dict],
    today: dt.date | None = None,
    fear_greed: dict | None = None,
    vix_structure: dict | None = None,
    buffett: dict | None = None,
) -> tuple[str, list[str], list[str], list[str]]:
    """Construct the report text.

    Returns (document_text, red_tickers, amber_tickers, skipped_tickers).
    Red alerts are written first, then Amber. Both are labelled in the report.
    """
    today = today or dt.date.today()

    red_items:   list[tuple[str, dict]] = []
    amber_items: list[tuple[str, dict]] = []
    skipped:     list[str] = []

    for r in results:
        tier = get_alert_tier(r["signals"])
        if tier == "red":
            red_items.append((r["ticker"], r["signals"]))
        elif tier == "amber":
            amber_items.append((r["ticker"], r["signals"]))
        else:
            skipped.append(r["ticker"])

    red_tickers   = [t for t, _ in red_items]
    amber_tickers = [t for t, _ in amber_items]

    debug_summary = _debug_summary(results)
    parts = [_header(today, fear_greed, red_tickers, amber_tickers, skipped,
                     debug_summary, vix_structure, buffett)]

    if red_items or amber_items:
        parts.append("\n[ASSETS WITH NON-TRIVIAL SIGNALS]\n\n")
        for ticker, signals in red_items:
            parts.append(_asset_section(ticker, signals, "red"))
        for ticker, signals in amber_items:
            parts.append(_asset_section(ticker, signals, "amber"))
    else:
        parts.append(
            "\n[ASSETS WITH NON-TRIVIAL SIGNALS]\n\n"
            "(none — all tickers evaluated today fell within normal ranges)\n"
        )

    parts.append(_closing_instruction(len(red_items) + len(amber_items)))
    return "".join(parts), red_tickers, amber_tickers, skipped


def write_document(
    results: list[dict],
    today: dt.date | None = None,
    fear_greed: dict | None = None,
    vix_structure: dict | None = None,
    buffett: dict | None = None,
    output_dir: str = OUTPUT_DIR,
) -> tuple[str, list[str], list[str]]:
    """Build and persist the report. Returns (path, included, skipped).

    `included` combines red + amber tickers (Red first).
    """
    today = today or dt.date.today()
    text, red, amber, skipped = build_document(results, today, fear_greed, vix_structure, buffett)
    included = red + amber

    os.makedirs(output_dir, exist_ok=True)
    path = os.path.join(output_dir, f"daily_report_{today.isoformat()}.txt")
    with open(path, "w", encoding="utf-8") as f:
        f.write(text)

    logger.info(
        f"wrote {path} ({len(text)} chars, {len(red)} red, {len(amber)} amber, "
        f"{len(skipped)} skipped)"
    )
    return path, included, skipped
