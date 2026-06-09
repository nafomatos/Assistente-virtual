"""Automated Claude classification for the daily pipeline.

Calls the primary Claude model with the daily .txt report, parses the
JSON_OUTPUT section, and writes logs/signals_{date}.json so that
_attach_sizing_blocks() can compute position sizes BEFORE the email
is sent.

The pipeline previously had no automated classification step — the
signals file was only created by manual paste (user → Claude.ai →
add_recommendations).  This module closes that gap so sizing blocks
appear in every daily email without human intervention.

Response format expected from the model (see claude_advisor/prompts.py):

    HUMAN_SUMMARY:
    <portuguese text>

    JSON_OUTPUT:
    [{"ticker": ..., "classification": ..., "recommendation": ...,
      "reasoning": ..., "confidence": ...}, ...]
"""

from __future__ import annotations

import datetime
import json
import logging
import os
import re

from config import (
    CLAUDE_MAX_TOKENS_DAILY,
    CLAUDE_TEMPERATURE,
    MODEL_FALLBACK,
    MODEL_PRIMARY,
)

logger = logging.getLogger(__name__)

_LOGS_DIR = "logs"


def _parse_json_section(text: str) -> list[dict]:
    """Extract the JSON array from the JSON_OUTPUT section.

    Handles:
    - Bare array after the JSON_OUTPUT: label
    - Markdown fences around the array
    - Leading/trailing whitespace
    - A response that is just the bare array with no JSON_OUTPUT label
      (the model occasionally follows the report's closing instruction
      instead of the two-section contract)
    """
    # Find JSON_OUTPUT section; fall back to scanning the whole response
    # for a bare array when the label is absent.
    match = re.search(r"JSON_OUTPUT\s*:\s*", text, re.IGNORECASE)
    if match:
        tail = text[match.end():].strip()
    elif "[" in text:
        logger.info("JSON_OUTPUT label missing — falling back to bare-array parse")
        tail = text.strip()
    else:
        raise ValueError("JSON_OUTPUT section not found in response")

    # Strip optional markdown fences
    if tail.startswith("```"):
        tail = re.sub(r"^```(?:json)?\s*\n?", "", tail)
        tail = re.sub(r"\n?```\s*$", "", tail)
        tail = tail.strip()

    # Find the outermost JSON array
    start = tail.find("[")
    if start == -1:
        raise ValueError(f"No JSON array found in JSON_OUTPUT section: {tail[:200]!r}")

    # Walk to the matching close bracket
    depth = 0
    end = start
    for i, ch in enumerate(tail[start:], start=start):
        if ch == "[":
            depth += 1
        elif ch == "]":
            depth -= 1
            if depth == 0:
                end = i
                break
    else:
        raise ValueError("Unterminated JSON array in JSON_OUTPUT section")

    return json.loads(tail[start : end + 1])


def classify_signals(
    report_text: str,
    date: datetime.date | None = None,
    logs_dir: str = _LOGS_DIR,
) -> list[dict]:
    """Call Claude with the daily report and persist classified signals.

    Returns the list of classified signal dicts (may be empty on failure).
    Writes logs/signals_{date}.json only on success.
    Never raises — logs warnings and returns [] on any failure.
    """
    date = date or datetime.date.today()

    api_key = os.environ.get("ANTHROPIC_API_KEY", "").strip()
    if not api_key:
        logger.info("ANTHROPIC_API_KEY not set — skipping automated classification")
        return []

    try:
        import anthropic
    except ImportError:
        logger.warning("anthropic package not installed — skipping automated classification")
        return []

    client = anthropic.Anthropic(api_key=api_key)
    raw = None
    for model in (MODEL_PRIMARY, MODEL_FALLBACK):
        try:
            response = client.messages.create(
                model=model,
                max_tokens=CLAUDE_MAX_TOKENS_DAILY,
                temperature=CLAUDE_TEMPERATURE,
                messages=[{"role": "user", "content": report_text}],
            )
            raw = response.content[0].text
            logger.info(
                "automated classification: model=%s input=%d output=%d tokens",
                model,
                response.usage.input_tokens,
                response.usage.output_tokens,
            )
            break
        except Exception as exc:
            logger.warning(
                "automated classification: API call failed on %s — %s", model, exc
            )
    if raw is None:
        return []

    try:
        signals = _parse_json_section(raw)
    except Exception as exc:
        logger.warning(
            "automated classification: JSON parse failed — %s | raw[:400]=%r",
            exc,
            raw[:400],
        )
        return []

    if not signals:
        logger.info("automated classification: no actionable signals returned")
        return []

    # Persist so _attach_sizing_blocks() can read them in the same pipeline run.
    os.makedirs(logs_dir, exist_ok=True)
    out_path = os.path.join(logs_dir, f"signals_{date.isoformat()}.json")
    try:
        with open(out_path, "w", encoding="utf-8") as fh:
            json.dump({"date": date.isoformat(), "signals": signals}, fh, indent=2)
        logger.info(
            "automated classification: wrote %d signal(s) to %s",
            len(signals),
            out_path,
        )
    except OSError as exc:
        logger.warning("automated classification: could not write %s — %s", out_path, exc)

    return signals
