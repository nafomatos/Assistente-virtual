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
        reddit_summary     = "n/a"
        stocktwits_summary = "n/a"
        twitter_summary    = "n/a"
        youtube_summary    = "n/a"
    else:
        heat_z = s.get("social_heat_zscore")
        if heat_z is not None:
            social_line = f"social_heat_z: {heat_z:+.1f}"
        else:
            # Fall back to raw score if somehow present
            raw = s.get("social_heat")
            social_line = f"social_heat: {raw}/100" if raw is not None else "social_heat_z: n/a"

        breakdown = s.get("source_breakdown") or {}
        reddit_summary      = breakdown.get("reddit",      "n/a")
        stocktwits_summary  = breakdown.get("stocktwits",  "n/a")
        twitter_summary     = breakdown.get("twitter",     "n/a")
        youtube_summary     = breakdown.get("youtube",     "n/a")

    rsi_value = r.get("rsi")
    rsi_class = r.get("classification", "n/a")
    rsi_str = (
        f"RSI-14: {rsi_value} ({rsi_class})"
        if rsi_value is not None
        else f"RSI-14: n/a ({rsi_class})"
    )

    news_str = format_news(m.get("recent_news") or [])

    macro_flag = " ⚠ macro_extreme" if p.get("macro_extreme") else ""

    return (
        f"Asset: {ticker} ({name})\n\n"
        f"Market signals:\n"
        f"- Volume: {v['classification']} ({v['ratio']}x 30d avg)\n"
        f"- Price velocity: {p['classification']} "
        f"(z_30d: {p['z_score_30d']}, z_200d: {p['z_score_200d']}, "
        f"direction: {p['direction']}, macro_extreme: {p.get('macro_extreme', False)})"
        f"{macro_flag}\n"
        f"- {rsi_str}\n"
        f"- Current price: ${_fmt_price(m['current_price'])} "
        f"({m['daily_return_pct']:+.2f}% today)\n\n"
        f"Recent news (last 3):\n{news_str}\n\n"
        f"Social signals ({social_line}):\n"
        f"- Reddit: {reddit_summary}\n"
        f"- StockTwits: {stocktwits_summary}\n"
        f"- Twitter: {twitter_summary}\n"
        f"- YouTube: {youtube_summary}\n\n"
        f"Analyze and respond in JSON."
    )
