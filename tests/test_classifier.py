"""Tests for Issue 4: claude_advisor/classifier.py JSON parsing.

Verifies that _parse_json_section() correctly extracts the JSON array from
the Claude two-section response format regardless of whether the model
wraps the array in markdown fences or not.
"""

from __future__ import annotations

import json
import pytest

from claude_advisor.classifier import _parse_json_section


# ── helpers ──────────────────────────────────────────────────────────────────

_SAMPLE_SIGNALS = [
    {
        "ticker": "GC=F",
        "classification": "institutional_rebalancing",
        "recommendation": "wait",
        "reasoning": "Volume 161x with suspicious data quality flag; z30=+0.27 is noise. No social heat. Institutional rebalancing.",
        "confidence": 5,
    },
    {
        "ticker": "NVDA",
        "classification": "bubble_forming",
        "recommendation": "reduce_exposure",
        "reasoning": "Volume 3.2x, z30=+2.8, z200=+2.1, macro_extreme. Heat explosive, bullish tone.",
        "confidence": 8,
    },
]

_SAMPLE_JSON = json.dumps(_SAMPLE_signals := _SAMPLE_SIGNALS, indent=2)


# ── bare array (ideal case) ───────────────────────────────────────────────────

def test_bare_array_no_fences():
    """Model returns bare JSON array after JSON_OUTPUT: label."""
    text = f"HUMAN_SUMMARY:\nAlgum texto.\n\nJSON_OUTPUT:\n{_SAMPLE_JSON}"
    result = _parse_json_section(text)
    assert len(result) == 2
    assert result[0]["ticker"] == "GC=F"
    assert result[1]["ticker"] == "NVDA"


# ── markdown fences (the bug that was causing the empty-body failure) ─────────

def test_fenced_json_array():
    """Model wraps JSON in ```json ... ``` fences → must be stripped correctly."""
    text = f"HUMAN_SUMMARY:\nAlgum texto.\n\nJSON_OUTPUT:\n```json\n{_SAMPLE_JSON}\n```"
    result = _parse_json_section(text)
    assert len(result) == 2
    assert result[0]["ticker"] == "GC=F"


def test_fenced_without_language_tag():
    """Fences without language specifier (``` alone) must also be stripped."""
    text = f"HUMAN_SUMMARY:\nAlgum texto.\n\nJSON_OUTPUT:\n```\n{_SAMPLE_JSON}\n```"
    result = _parse_json_section(text)
    assert len(result) == 2


def test_case_insensitive_section_label():
    """JSON_OUTPUT: label matching is case-insensitive."""
    text = f"HUMAN_SUMMARY:\nAlgum texto.\n\njson_output:\n{_SAMPLE_JSON}"
    result = _parse_json_section(text)
    assert len(result) == 2


# ── error cases ───────────────────────────────────────────────────────────────

def test_missing_json_output_section_raises():
    """Missing JSON_OUTPUT: label must raise ValueError."""
    with pytest.raises(ValueError, match="JSON_OUTPUT section not found"):
        _parse_json_section("HUMAN_SUMMARY:\nSome text.\n\nNo JSON section here.")


def test_empty_array_is_valid():
    """An empty JSON array is valid (no actionable signals today)."""
    text = "HUMAN_SUMMARY:\nNenhum alerta.\n\nJSON_OUTPUT:\n[]"
    result = _parse_json_section(text)
    assert result == []


def test_single_signal():
    """Single-element array parses correctly."""
    single = json.dumps([_SAMPLE_SIGNALS[0]])
    text = f"HUMAN_SUMMARY:\nTexto.\n\nJSON_OUTPUT:\n{single}"
    result = _parse_json_section(text)
    assert len(result) == 1
    assert result[0]["recommendation"] == "wait"


def test_extra_whitespace_around_label():
    """Whitespace around the JSON_OUTPUT: label must not break parsing."""
    text = f"HUMAN_SUMMARY:\nTexto.\n\n  JSON_OUTPUT:   \n{_SAMPLE_JSON}"
    result = _parse_json_section(text)
    assert len(result) == 2
