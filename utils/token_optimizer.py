"""Small helpers that turn raw signal dicts into compact prompt text.

The whole point of this module is to keep Claude input tokens low.
Nothing here calls the LLM.
"""

from __future__ import annotations


def truncate_text(text: str, max_chars: int = 120) -> str:
    """Clean truncation with ellipsis."""
    if text is None:
        return ""
    text = text.strip().replace("\n", " ")
    if len(text) <= max_chars:
        return text
    return text[: max_chars - 1].rstrip() + "…"


def format_top_items(items: list, max_items: int = 3) -> str:
    """Format a list of dicts as numbered one-liners.

    Each item may provide keys like title/text/score/engagement/views.
    Unknown shapes are rendered via str().
    """
    if not items:
        return "none"

    lines = []
    for i, item in enumerate(items[:max_items], start=1):
        if isinstance(item, dict):
            label = item.get("title") or item.get("text") or ""
            label = truncate_text(label, 120)
            metric_bits = []
            for key in ("score", "engagement", "views", "likes"):
                if key in item:
                    metric_bits.append(f"{key}:{item[key]}")
            suffix = f" ({', '.join(metric_bits)})" if metric_bits else ""
            lines.append(f"{i}. \"{label}\"{suffix}")
        else:
            lines.append(f"{i}. {truncate_text(str(item), 120)}")
    return "\n".join(lines)


def format_news(items: list, max_items: int = 3) -> str:
    """Render the recent_news list as up to 3 dense one-liners.

    Each item is expected to have {title, publisher, age_hours}.
    """
    if not items:
        return "none"
    lines = []
    for i, it in enumerate(items[:max_items], start=1):
        title = truncate_text(it.get("title", ""), 120)
        publisher = it.get("publisher") or "unknown"
        age = it.get("age_hours")
        age_str = f"{age}h ago" if isinstance(age, (int, float)) else "age n/a"
        lines.append(f"{i}. \"{title}\" — {publisher}, {age_str}")
    return "\n".join(lines)


def estimate_tokens(text: str) -> int:
    """Rough char/4 heuristic — good enough for local logging."""
    if not text:
        return 0
    return max(1, len(text) // 4)


def _fmt_price(x: float) -> str:
    return f"{x:,.2f}"


def _fmt_pct(val: float | None, decimals: int = 1) -> str:
    """Format a fraction (0.82) as a percentage string ('+82.0%'), or 'n/a'."""
    if val is None:
        return "n/a"
    return f"{val * 100:+.{decimals}f}%"


def _fmt_ratio(val: float | None) -> str:
    """Format a ratio to 2 dp, or 'n/a'."""
    if val is None:
        return "n/a"
    return f"{val:.2f}"


def _fmt_int(val: int | None, suffix: str = "") -> str:
    if val is None:
        return "n/a"
    return f"{val}{suffix}"


def _format_long_horizon(lh: dict) -> str:
    """Render the long_horizon dict as a compact prompt block.

    Returns an empty string when lh is empty so callers can concatenate
    unconditionally.  Each line is kept short to minimise token cost.
    """
    if not lh:
        return ""

    ext_200d   = lh.get("price_extension_200d")
    sustained  = lh.get("sustained_days_60")
    ret_6m     = lh.get("return_6m")
    accel      = lh.get("acceleration_ratio")
    vol_dist   = lh.get("volume_dist_ratio")
    dd_peak    = lh.get("drawdown_from_peak_2y")
    days_peak  = lh.get("days_since_peak_2y")

    # Sustained extension label
    if sustained is not None:
        sustained_str = f"{sustained}/60d"
        if sustained >= 30:
            sustained_str += " ⚑ extended"
    else:
        sustained_str = "n/a"

    # Volume distribution label
    if vol_dist is not None:
        vd_label = " (distribution ⚠)" if vol_dist > 1.0 else " (buying pressure)"
        vol_dist_str = f"{vol_dist:.2f}{vd_label}"
    else:
        vol_dist_str = "n/a"

    # Acceleration label
    if accel is not None:
        accel_label = " (parabolic ⚑)" if accel > 0.5 else ""
        accel_str = f"{accel:.2f}{accel_label}"
    else:
        accel_str = "n/a"

    return (
        f"Long-horizon context (v2, observe only — not a classification gate):\n"
        f"- Ext vs 200d MA: {_fmt_pct(ext_200d)} (sustained: {sustained_str})\n"
        f"- 6m return: {_fmt_pct(ret_6m)} | Acceleration (30d/6m): {accel_str}\n"
        f"- Vol distribution (down÷up, last 20d): {vol_dist_str}\n"
        f"- 2y peak drawdown: {_fmt_pct(dd_peak)} "
        f"({_fmt_int(days_peak, 'd since peak')})\n\n"
    )


def compress_signals(ticker: str, name: str, signals: dict) -> str:
    """Build the compact user-prompt body from analyzer outputs.

    `signals` is the merged dict produced by main.py — it must contain
    `market`, `volume`, `velocity`, and optionally `rsi` and `sentiment`.

    Social signals are shown as `social_heat_z: +3.2` when a z-score is
    available, or `n/a` when no collectors are wired yet.
    """
    m = signals["market"]
    v = signals["volume"]
    p = signals["velocity"]
    r = signals.get("rsi") or {}
    s = signals.get("sentiment")

    # Social heat: z-score preferred over raw score
    if s is None:
        social_line        = "social_heat_z: n/a"
        stocktwits_summary = "n/a"
        youtube_summary    = "n/a"
        twitter_summary    = "n/a"
    else:
        heat_z = s.get("social_heat_zscore")
        if heat_z is not None:
            social_line = f"social_heat_z: {heat_z:+.1f}"
        else:
            raw = s.get("social_heat")
            social_line = f"social_heat: {raw}/100" if raw is not None else "social_heat_z: n/a"

        breakdown = s.get("source_breakdown") or {}
        stocktwits_summary = breakdown.get("stocktwits", "n/a")
        youtube_summary    = breakdown.get("youtube",    "n/a")
        twitter_summary    = breakdown.get("twitter",    "n/a")

    rsi_value = r.get("rsi")
    rsi_class = r.get("classification", "n/a")
    rsi_str = (
        f"RSI-14: {rsi_value} ({rsi_class})"
        if rsi_value is not None
        else f"RSI-14: n/a ({rsi_class})"
    )

    news_str = format_news(m.get("recent_news") or [])

    macro_flag = " ⚠ macro_extreme" if p.get("macro_extreme") else ""

    # Volume-artifact containment (analyzers/volume_quality.py): when the
    # artifact flag fires, the volume multiple is removed from the classifier
    # payload entirely (raw value survives only in the badge and the artifact
    # log) and the loud investigation flag is rendered for the human reader.
    artifact = bool(v.get("artifact")) or v.get("data_quality") == "suspicious_volume"
    dq_flag = ""
    if artifact:
        raw_ratio = v.get("raw_ratio", v.get("ratio"))
        dq_flag = (
            f"⚠ DATA QUALITY FLAG: This ticker's volume multiple ({raw_ratio}x) exceeds normal"
            f" range and may be a data artifact. Weight volume evidence accordingly.\n"
            f"⚠ VOLUME DATA UNRELIABLE — metrics excluded from analysis. yfinance "
            f"front-month contract-roll artifact suspected. NEEDS INVESTIGATION/FIX. "
            f"See backtests/VOLUME_FIX*.md and logs/volume_artifacts.log\n\n"
        )

    volume_line = (
        "- Volume: n/a (suspected data artifact — excluded from analysis)"
        if artifact
        else f"- Volume: {v['classification']} ({v['ratio']}x 30d avg)"
    )

    # Long-horizon context (strategy v2, observation mode).
    # These signals are for context only — do not use them as classification
    # gates. The primary Divergence Rules (Volume × Social Heat × Price
    # Velocity) remain the sole classification triggers.
    lh = m.get("long_horizon") or {}
    long_horizon_block = _format_long_horizon(lh)

    return (
        f"{dq_flag}"
        f"Asset: {ticker} ({name})\n\n"
        f"Market signals:\n"
        f"{volume_line}\n"
        f"- Price velocity: {p['classification']} "
        f"(z_30d: {p['z_score_30d']}, z_200d: {p['z_score_200d']}, "
        f"direction: {p['direction']}, macro_extreme: {p.get('macro_extreme', False)})"
        f"{macro_flag}\n"
        f"- {rsi_str}\n"
        f"- Current price: ${_fmt_price(m['current_price'])} "
        f"({m['daily_return_pct']:+.2f}% today)\n\n"
        f"Recent news (last 3):\n{news_str}\n\n"
        f"Social signals ({social_line}):\n"
        f"- StockTwits: {stocktwits_summary}\n"
        f"- YouTube: {youtube_summary}\n"
        f"- Twitter: {twitter_summary}\n\n"
        f"{long_horizon_block}"
        f"Analyze and respond in JSON."
    )
