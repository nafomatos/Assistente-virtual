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
import math
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


def is_null_data(signals: dict) -> bool:
    """True for pure null-data tickers (e.g. pre-IPO SPCX): NaN/None volume
    ratio AND z30 == 0 AND z200 == 0 AND no 200d history. Such a ticker has
    no real signal — NaN volume must not be allowed to read as "extreme" and
    solo-trigger RED."""
    ratio = signals["volume"].get("ratio")
    ratio_null = ratio is None or (isinstance(ratio, float) and math.isnan(ratio))
    if not ratio_null:
        return False
    vel = signals["velocity"]
    if vel.get("z_score_30d") != 0 or vel.get("z_score_200d") != 0:
        return False
    lh = (signals.get("market") or {}).get("long_horizon") or {}
    return lh.get("price_extension_200d") is None


def get_alert_tier(signals: dict) -> str | None:
    """Return 'red', 'amber', or None.

    Null-data tickers (NaN volume + zero z-scores + no 200d history) are
    always SKIP — see is_null_data().
    Red  — extreme volume (>5x) OR macro_extreme (both |z_30d|>2 AND |z_200d|>2).
    Amber — |z_30d|>1.5 AND vol>1.5x; OR vol>2.5x alone; OR RSI>75/RSI<25;
             OR social_heat_zscore>2.0 with vol>1.0x;
             OR StockTwits heat "elevated"/"explosive" with vol>1.0x.
    Red takes priority; an asset cannot be both.
    """
    if is_null_data(signals):
        return None
    vol_class  = signals["volume"]["classification"]
    vol_ratio  = signals["volume"]["ratio"]
    macro_extreme = signals["velocity"].get("macro_extreme", False)
    z30        = abs(signals["velocity"]["z_score_30d"])
    rsi_val    = (signals.get("rsi") or {}).get("rsi")
    sentiment  = signals.get("sentiment") or {}
    heat_z     = sentiment.get("social_heat_zscore")
    st_heat    = sentiment.get("stocktwits_heat")

    # Red: extreme volume (unless data quality is suspicious) or both z-scores exceed 2.
    # When data_quality == "suspicious_volume" the 10x+ reading is almost certainly a
    # data artifact (contract roll, bad tick); volume alone must not solo-trigger RED.
    # macro_extreme (|z30|>2 AND |z200|>2) is independent of volume and still fires.
    data_quality = signals["volume"].get("data_quality", "ok")
    vol_suspicious = data_quality == "suspicious_volume"
    if (vol_class == "extreme" and not vol_suspicious) or macro_extreme:
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
    if st_heat in ("elevated", "explosive") and vol_ratio > 1.0:
        return "amber"

    return None


def passes_prefilter(signals: dict) -> bool:
    """Backward-compatible wrapper — True if the asset has any alert tier."""
    return get_alert_tier(signals) is not None


def get_tier_reason(signals: dict) -> str:
    """Explain which signals triggered the tier, or why the ticker was skipped."""
    if is_null_data(signals):
        return (
            "SKIP: null data — NaN volume, zero z-scores, no 200d history "
            "(pre-IPO / dead ticker, no real signal)"
        )
    vol_class = signals["volume"]["classification"]
    vol_ratio = signals["volume"]["ratio"]
    z30 = signals["velocity"]["z_score_30d"]
    z200 = signals["velocity"]["z_score_200d"]
    macro_extreme = signals["velocity"].get("macro_extreme", False)
    rsi_val  = (signals.get("rsi") or {}).get("rsi")
    sentiment = signals.get("sentiment") or {}
    heat_z   = sentiment.get("social_heat_zscore")
    st_heat  = sentiment.get("stocktwits_heat")

    tier = get_alert_tier(signals)

    if tier == "red":
        reasons = []
        data_quality = signals["volume"].get("data_quality", "ok")
        if vol_class == "extreme" and data_quality != "suspicious_volume":
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
        if st_heat in ("elevated", "explosive") and vol_ratio > 1.0:
            reasons.append(f"st_heat={st_heat}")
        return "AMBER: " + "; ".join(reasons)

    # Skipped — explain what fell short
    parts = [f"vol={vol_ratio:.1f}x ({vol_class})", f"z30={z30:+.1f},z200={z200:+.1f}"]
    if rsi_val is not None:
        parts.append(f"RSI={rsi_val:.0f}")
    if heat_z is not None:
        parts.append(f"social_z={heat_z:+.1f}")
    if st_heat:
        parts.append(f"st_heat={st_heat}")
    return "SKIP: " + "; ".join(parts)


# Keep old name so any external callers don't break
_get_filter_reason = get_tier_reason


def _active_positions_section(
    open_positions: list[dict],
    closed_stats: dict | None,
) -> str:
    """Plain-text ACTIVE POSITIONS block for the .txt report."""
    if not open_positions and not closed_stats:
        return ""

    lines = [
        "=" * 72,
        "ACTIVE POSITIONS",
        "=" * 72,
    ]

    if open_positions:
        for pos in open_positions:
            ticker      = pos["ticker"]
            direction   = pos.get("direction", "long").upper()
            conf        = pos.get("confidence", "?")
            entry_price = pos.get("entry_price", 0)
            entry_date  = pos.get("entry_date", "")
            current     = pos.get("current_price", entry_price)
            pnl_pct     = pos.get("pnl_pct", 0.0)
            days_held   = pos.get("days_held", 0)
            status      = pos.get("status", "NEUTRAL")
            pnl_sign    = "+" if pnl_pct >= 0 else ""

            lines.append(
                f"  {ticker:<6} | {direction:<5} | conf {conf}"
            )
            lines.append(
                f"  Entry: ${entry_price:.2f} on {entry_date}"
            )
            lines.append(
                f"  Current: ${current:.2f} ({pnl_sign}{pnl_pct:.1f}%)"
            )
            lines.append(
                f"  Days held: {days_held} / 30  |  Status: {status}"
            )
            lines.append("")
    else:
        lines.append("  No open positions.")
        lines.append("")

    if closed_stats and closed_stats.get("total", 0) > 0:
        total    = closed_stats["total"]
        correct  = closed_stats["correct"]
        win_rate = closed_stats["win_rate"]
        avg_pnl  = closed_stats["avg_pnl"]
        pnl_sign = "+" if avg_pnl >= 0 else ""
        lines.append(
            f"  Closed positions (last 30 days): {total} total "
            f"| {correct} correct ({win_rate:.1f}%) "
            f"| Avg P&L: {pnl_sign}{avg_pnl:.1f}%"
        )
        lines.append("")

    return "\n".join(lines) + "\n"


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
    # Must match the Output Contract in claude_advisor/prompts.py — the
    # classifier's parser expects the HUMAN_SUMMARY / JSON_OUTPUT labels.
    return (
        f"\n{'=' * 72}\n"
        f"[INSTRUCTION]\n\n"
        f"Analyze each of the {n_assets} asset(s) above and respond using the "
        f"exact two-section format from the system prompt: a HUMAN_SUMMARY: "
        f"section followed by a JSON_OUTPUT: section containing a single JSON "
        f"array. Each element of the array must follow this exact schema:\n\n"
        f"{{\n"
        f'  "ticker": "...",\n'
        f'  "classification": "bubble_forming|irrational_panic|institutional_rebalancing|silent_accumulation|ambiguous|no_signal",\n'
        f'  "recommendation": "contrarian_buy|reduce_exposure|wait|no_action",\n'
        f'  "reasoning": "2-3 short sentences, under 400 characters total",\n'
        f'  "confidence": <integer 1-10>\n'
        f"}}\n\n"
        f"No markdown fences, no prose outside the two labelled sections.\n"
    )


def build_document(
    results: list[dict],
    today: dt.date | None = None,
    fear_greed: dict | None = None,
    vix_structure: dict | None = None,
    buffett: dict | None = None,
    open_positions: list[dict] | None = None,
    closed_stats: dict | None = None,
) -> tuple[str, list[str], list[str], list[str]]:
    """Construct the report text.

    Returns (document_text, red_tickers, amber_tickers, skipped_tickers).
    Red alerts are written first, then Amber. Both are labelled in the report.
    The ACTIVE POSITIONS section is prepended above the macro context when
    open_positions is provided.
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
    positions_section = _active_positions_section(open_positions or [], closed_stats)
    header = _header(today, fear_greed, red_tickers, amber_tickers, skipped,
                     debug_summary, vix_structure, buffett)

    parts = [positions_section, header] if positions_section else [header]

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
    open_positions: list[dict] | None = None,
    closed_stats: dict | None = None,
) -> tuple[str, list[str], list[str]]:
    """Build and persist the report. Returns (path, included, skipped).

    `included` combines red + amber tickers (Red first).
    Pass `open_positions` and `closed_stats` to include the ACTIVE POSITIONS section.
    """
    today = today or dt.date.today()
    text, red, amber, skipped = build_document(
        results, today, fear_greed, vix_structure, buffett,
        open_positions=open_positions, closed_stats=closed_stats,
    )
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
