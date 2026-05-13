"""Tests for Issue 1: suspicious_volume tier suppression in get_alert_tier().

Verifies that a volume multiple > 10x (data_quality="suspicious_volume")
cannot solo-trigger RED, while macro_extreme still can, and that a
non-suspicious extreme volume still produces RED as before.
"""

from __future__ import annotations

import pytest

from output.document_builder import get_alert_tier, get_tier_reason


# ── helpers ──────────────────────────────────────────────────────────────────

def _signals(
    vol_ratio: float = 1.0,
    vol_class: str = "normal",
    data_quality: str = "ok",
    z30: float = 0.0,
    z200: float = 0.0,
    macro_extreme: bool = False,
    rsi: float | None = None,
) -> dict:
    return {
        "volume": {
            "ratio": vol_ratio,
            "classification": vol_class,
            "data_quality": data_quality,
        },
        "velocity": {
            "z_score_30d": z30,
            "z_score_200d": z200,
            "macro_extreme": macro_extreme,
            "classification": "normal",
            "direction": "flat",
        },
        "rsi": {"rsi": rsi, "classification": "normal"} if rsi is not None else {"rsi": None, "classification": "normal"},
        "sentiment": None,
    }


# ── Issue 1: suspicious volume must not solo-trigger RED ─────────────────────

def test_suspicious_extreme_volume_not_red():
    """GC=F scenario: 161x volume, suspicious_volume, z30=+0.27 → must NOT be RED."""
    s = _signals(vol_ratio=161.2, vol_class="extreme", data_quality="suspicious_volume",
                 z30=0.27, z200=0.12)
    assert get_alert_tier(s) != "red"


def test_suspicious_extreme_volume_falls_to_amber():
    """After RED suppression, extreme vol_class still triggers AMBER via amber check."""
    s = _signals(vol_ratio=161.2, vol_class="extreme", data_quality="suspicious_volume",
                 z30=0.27, z200=0.12)
    assert get_alert_tier(s) == "amber"


def test_non_suspicious_extreme_volume_still_red():
    """5.1x volume with ok data quality must still produce RED."""
    s = _signals(vol_ratio=5.1, vol_class="extreme", data_quality="ok",
                 z30=0.3, z200=0.1)
    assert get_alert_tier(s) == "red"


def test_macro_extreme_overrides_suspicious_volume():
    """macro_extreme=True fires RED even when data_quality=suspicious_volume."""
    s = _signals(vol_ratio=161.2, vol_class="extreme", data_quality="suspicious_volume",
                 z30=2.5, z200=2.3, macro_extreme=True)
    assert get_alert_tier(s) == "red"


def test_tier_reason_suppressed_does_not_mention_vol():
    """When volume is suppressed, tier reason should NOT list vol as a RED trigger.
    macro_extreme reason should still appear when it fires."""
    s_suppressed = _signals(vol_ratio=161.2, vol_class="extreme",
                            data_quality="suspicious_volume", z30=0.27, z200=0.12)
    reason = get_tier_reason(s_suppressed)
    # Should be AMBER (not RED), and vol= should describe AMBER trigger, not RED
    assert reason.startswith("AMBER"), f"Expected AMBER, got: {reason}"

    s_macro = _signals(vol_ratio=161.2, vol_class="extreme",
                       data_quality="suspicious_volume", z30=2.5, z200=2.3, macro_extreme=True)
    reason_macro = get_tier_reason(s_macro)
    assert reason_macro.startswith("RED"), f"Expected RED via macro_extreme, got: {reason_macro}"
    assert "macro_extreme" in reason_macro


def test_boundary_exactly_10x_ok_is_extreme_red():
    """ratio=10.0 is data_quality='ok' (threshold is strictly > 10) → RED."""
    s = _signals(vol_ratio=10.0, vol_class="extreme", data_quality="ok",
                 z30=0.1, z200=0.1)
    assert get_alert_tier(s) == "red"


def test_just_above_10x_suspicious_not_red():
    """ratio=10.01 is suspicious_volume → no RED from volume alone."""
    s = _signals(vol_ratio=10.01, vol_class="extreme", data_quality="suspicious_volume",
                 z30=0.1, z200=0.1)
    assert get_alert_tier(s) != "red"
    assert get_alert_tier(s) == "amber"
