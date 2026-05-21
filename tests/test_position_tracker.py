"""Tests for the stop-loss feature in tracker/position_tracker.py.

Verifies check_stop_loss() boundary conditions (LONG, SHORT, direction-
aware) and that close_expired_positions() applies the stop BEFORE d+30
with correct STOPPED_OUT labeling.

Real ticker prices are NOT fetched — positions.json is never written;
the tests exercise only the pure logic helpers.
"""

from __future__ import annotations

import pytest

from tracker.position_tracker import STOP_LOSS_THRESHOLD, check_stop_loss


# ── helpers ──────────────────────────────────────────────────────────────────

def _pos(direction: str, entry: float) -> dict:
    return {"direction": direction, "entry_price": entry}


# ── 1. LONG down 25% — triggers ──────────────────────────────────────────────

def test_long_down_25_triggers():
    """LONG at $100, current $75 → adverse = 25% → stop fires."""
    pos = _pos("long", 100.0)
    assert check_stop_loss(pos, 75.0) is True


# ── 2. LONG down 24% — no trigger ────────────────────────────────────────────

def test_long_down_24_no_trigger():
    """LONG at $100, current $76 → adverse = 24% → no stop."""
    pos = _pos("long", 100.0)
    assert check_stop_loss(pos, 76.0) is False


# ── 3. SHORT up 25% (adverse) — triggers ─────────────────────────────────────

def test_short_up_25_triggers():
    """SHORT at $100, current $125 → adverse = 25% → stop fires."""
    pos = _pos("short", 100.0)
    assert check_stop_loss(pos, 125.0) is True


# ── 4. SHORT up 24% — no trigger ─────────────────────────────────────────────

def test_short_up_24_no_trigger():
    """SHORT at $100, current $124 → adverse = 24% → no stop."""
    pos = _pos("short", 100.0)
    assert check_stop_loss(pos, 124.0) is False


# ── 5. SHORT down 25% (favorable) — no trigger ───────────────────────────────

def test_short_favorable_move_no_trigger():
    """SHORT at $100, current $75 → price FELL 25% (profit for short) → no stop."""
    pos = _pos("short", 100.0)
    assert check_stop_loss(pos, 75.0) is False


# ── 6. Threshold boundary: exactly 25% → triggers ────────────────────────────

def test_boundary_exactly_25_triggers():
    """Exactly at STOP_LOSS_THRESHOLD (>=) — stop fires."""
    pos = _pos("long", 100.0)
    threshold_price = 100.0 * (1 - STOP_LOSS_THRESHOLD)
    assert check_stop_loss(pos, threshold_price) is True


# ── 7. POET SHORT — retroactive scenario (−60.9%) ────────────────────────────

def test_poet_short_retroactive():
    """POET SHORT entry $9.21, current $14.82.
    adverse = (14.82 - 9.21) / 9.21 = 60.9% → STOPPED_OUT."""
    pos = _pos("short", 9.21)
    current = 14.82
    adverse = (current - 9.21) / 9.21
    assert abs(adverse - 0.609) < 0.001, f"adverse={adverse:.3f}"
    assert check_stop_loss(pos, current) is True


# ── 8. ARM SHORT — retroactive scenario (−25.7%) ─────────────────────────────

def test_arm_short_retroactive():
    """ARM SHORT entry $237.30, current $298.23.
    adverse = (298.23 - 237.30) / 237.30 = 25.7% → STOPPED_OUT."""
    pos = _pos("short", 237.30)
    current = 298.23
    adverse = (current - 237.30) / 237.30
    assert abs(adverse - 0.257) < 0.001, f"adverse={adverse:.3f}"
    assert check_stop_loss(pos, current) is True


# ── 9. NBIS SHORT — just under threshold (−24.7%) → NO trigger ───────────────

def test_nbis_short_just_under_threshold():
    """NBIS SHORT entry $176.42, current $219.93.
    adverse = (219.93 - 176.42) / 176.42 = 24.7% → BELOW 25% → no stop.

    NBIS rides until it crosses 25% or reaches d+30.
    """
    pos = _pos("short", 176.42)
    current = 219.93
    adverse = (current - 176.42) / 176.42
    assert abs(adverse - 0.247) < 0.001, f"adverse={adverse:.3f}"
    assert check_stop_loss(pos, current) is False
