"""Build a single .txt report you can paste into Claude.ai.

The file has three parts:
  1. Header with today's date, shared macro context (Fear & Greed), and the
     cached system prompt from claude_advisor/prompts.py.
  2. One section per asset that passes the local pre-filter, in the
     compressed signal format produced by utils/token_optimizer.py.
  3. A closing instruction asking Claude to return JSON recommendations.
"""

from __future__ import annotations

import datetime as dt
import logging
import os

from claude_advisor.prompts import SYSTEM_PROMPT
from collectors.fear_greed import format_summary as format_fear_greed
from config import SOCIAL_HEAT_THRESHOLD, TICKER_NAMES
from utils.token_optimizer import compress_signals

logger = logging.getLogger(__name__)

OUTPUT_DIR = "output"


def passes_prefilter(signals: dict) -> bool:
    """Cheap local filter: only include assets with a non-trivial signal.

    macro_extreme=True is a guaranteed pass — that's a both-timeframe
    z>2 move, rare enough to warrant Claude's attention on its own.
    """
    vol_class = signals["volume"]["classification"]
    vel_class = signals["velocity"]["classification"]
    macro_extreme = signals["velocity"].get("macro_extreme", False)
    heat = (signals.get("sentiment") or {}).get("social_heat", 0)
    return (
        macro_extreme
        or vol_class in ("anomalous", "extreme")
        or vel_class in ("extreme", "blowout")
        or heat > SOCIAL_HEAT_THRESHOLD
    )


def _coverage_line(included: list[str], skipped: list[str]) -> str:
    total = len(included) + len(skipped)
    passed_str = ", ".join(included) if included else "none"
    skipped_str = ", ".join(skipped) if skipped else "none"
    return (
        f"Coverage — {total} tickers processed · {len(included)} passed · "
        f"{len(skipped)} filtered\n"
        f"  passed:  {passed_str}\n"
        f"  skipped: {skipped_str}"
    )


def _header(
    today: dt.date,
    fear_greed: dict | None,
    included: list[str],
    skipped: list[str],
) -> str:
    fg_line = format_fear_greed(fear_greed)
    coverage = _coverage_line(included, skipped)
    return (
        f"ARTIFICIAL PRICE RADAR — Daily Report {today.isoformat()}\n"
        f"{'=' * 72}\n"
        f"Macro context — {fg_line}\n"
        f"{coverage}\n"
        f"{'=' * 72}\n\n"
        f"[SYSTEM PROMPT — paste everything below together into Claude.ai]\n\n"
        f"{SYSTEM_PROMPT.strip()}\n"
    )


def _asset_section(ticker: str, signals: dict) -> str:
    name = TICKER_NAMES.get(ticker, ticker)
    body = compress_signals(ticker, name, signals)
    # strip the trailing "Analyze and respond in JSON." that compress_signals
    # appends; we replace it with a single global instruction at the end.
    body = body.replace("\n\nAnalyze and respond in JSON.", "").rstrip()
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
) -> tuple[str, list[str], list[str]]:
    """Construct the report text.

    `results` is a list of dicts with at least `ticker` and `signals`.
    `fear_greed` is the shared macro snapshot from collectors.fear_greed.
    Returns (document_text, included_tickers, skipped_tickers).
    """
    today = today or dt.date.today()

    included: list[str] = []
    skipped:  list[str] = []
    sections: list[str] = []

    for r in results:
        if passes_prefilter(r["signals"]):
            sections.append(_asset_section(r["ticker"], r["signals"]))
            included.append(r["ticker"])
        else:
            skipped.append(r["ticker"])

    parts = [_header(today, fear_greed, included, skipped)]
    if sections:
        parts.append("\n[ASSETS WITH NON-TRIVIAL SIGNALS]\n\n")
        parts.extend(sections)
    else:
        parts.append(
            "\n[ASSETS WITH NON-TRIVIAL SIGNALS]\n\n"
            "(none — all tickers evaluated today fell within normal ranges)\n"
        )
    parts.append(_closing_instruction(len(included)))

    return "".join(parts), included, skipped


def write_document(
    results: list[dict],
    today: dt.date | None = None,
    fear_greed: dict | None = None,
    output_dir: str = OUTPUT_DIR,
) -> tuple[str, list[str], list[str]]:
    """Build and persist the report. Returns (path, included, skipped)."""
    today = today or dt.date.today()
    text, included, skipped = build_document(results, today, fear_greed)

    os.makedirs(output_dir, exist_ok=True)
    path = os.path.join(output_dir, f"daily_report_{today.isoformat()}.txt")
    with open(path, "w", encoding="utf-8") as f:
        f.write(text)

    logger.info(
        f"wrote {path} ({len(text)} chars, {len(included)} included, "
        f"{len(skipped)} skipped)"
    )
    return path, included, skipped
