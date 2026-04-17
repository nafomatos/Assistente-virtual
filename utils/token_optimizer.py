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
    `market`, `volume`, `velocity`, and optionally `sentiment`.
    """
    m = signals["market"]
    v = signals["volume"]
    p = signals["velocity"]
    s = signals.get("sentiment")

    if s is None:
        heat = 0
        reddit_summary = "n/a"
        twitter_summary = "n/a"
        youtube_summary = "n/a"
    else:
        heat = s.get("social_heat", 0)
        breakdown = s.get("source_breakdown", {})
        reddit_summary  = breakdown.get("reddit",  "n/a")
        twitter_summary = breakdown.get("twitter", "n/a")
        youtube_summary = breakdown.get("youtube", "n/a")

    return (
        f"Asset: {ticker} ({name})\n\n"
        f"Market signals:\n"
        f"- Volume: {v['classification']} ({v['ratio']}x 30d avg)\n"
        f"- Price velocity: {p['classification']} "
        f"(z-score: {p['z_score']}, direction: {p['direction']})\n"
        f"- Current price: ${_fmt_price(m['current_price'])} "
        f"({m['daily_return_pct']:+.2f}% today)\n\n"
        f"Social signals (social_heat: {heat}/100):\n"
        f"- Reddit: {reddit_summary}\n"
        f"- Twitter: {twitter_summary}\n"
        f"- YouTube: {youtube_summary}\n\n"
        f"Analyze and respond in JSON."
    )
