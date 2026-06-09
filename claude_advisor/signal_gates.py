"""Code-enforced classification gates for strategy v2.

The Claude/Haiku classifier returns a list of signal dicts
(``ticker``/``classification``/``recommendation``/``reasoning``/``confidence``).
The system prompt *asks* the model to apply the v2 short-gating rules, but a
prompt is advisory — the V1 retrospective (backtests/V1_RETROSPECTIVE_20260605.md)
showed the model issued high-confidence bubble shorts straight into institutional
accumulation regardless of the prompt guidance.

This module enforces those rules in code, after classification, so they cannot
be ignored.  It only ever *tightens* SHORT signals — long signals
(``irrational_panic`` → ``contrarian_buy``) are never touched, per the
retrospective finding that the long side went 2/2.

Rules (applied in order, to every ``bubble_forming`` / ``reduce_exposure``
SHORT candidate):

1. AI-hardware-in-bull reclassification (Part 4):
   semis sector AND Buffett > 200% AND z200 elevated (≥ +2) AND vol_dist ≤ 1.0
   → ``institutional_rebalancing`` / ``wait``.
2. Volume-distribution gate (Part 2, PRIMARY):
   requires vol_dist > 1.0 (down-day volume exceeds up-day volume = real
   distribution).  Otherwise the move is accumulation, not euphoria →
   ``institutional_rebalancing`` / ``wait``.
3. Sustained-extension gate (Part 4, secondary):
   requires price_extension_200d > 0.60 (single name) / 0.40 (index)
   AND sustained_days_60 >= 30.  Otherwise → ``institutional_rebalancing`` / ``wait``.
4. Macro fear cap (Part 3):
   any signal still classified ``bubble_forming`` when Fear & Greed < 35 has
   its confidence capped at 5 — below the actionable short threshold of 6, so
   it survives as an observation but cannot open a position.

Each gated signal gets a ``v2_gate`` annotation describing what fired, for the
report/email and for auditability.

Pure functions only — no I/O, no network.  Safe to unit-test directly.
"""

from __future__ import annotations

import logging

from tracker.sectors import get_sector

logger = logging.getLogger(__name__)

# ── thresholds ──────────────────────────────────────────────────────────────
SHORT_CLASSIFICATION = "bubble_forming"
SHORT_RECOMMENDATION = "reduce_exposure"
WAIT_CLASSIFICATION  = "institutional_rebalancing"
WAIT_RECOMMENDATION  = "wait"

SHORT_VOL_DIST_MIN    = 1.0    # down÷up volume must exceed this for a real short
SHORT_EXT_MIN_SINGLE  = 0.60   # price_extension_200d for a single name
SHORT_EXT_MIN_INDEX   = 0.40   # price_extension_200d for a broad index/ETF
SHORT_SUSTAINED_MIN   = 30     # sustained_days_60 floor

MACRO_FEAR_CAP_THRESHOLD = 35  # Fear & Greed strictly below this caps bubble conf
MACRO_BUBBLE_CONF_CAP    = 5   # capped confidence (below MIN_SHORT_CONFIDENCE)

# Actionable-confidence floors (single source of truth — the prompt and the
# recommendation parser both reference these). A short below 6 or a long below
# 7 is an observation, not a trade. MACRO_BUBBLE_CONF_CAP sits deliberately
# below MIN_SHORT_CONFIDENCE so a fear-capped bubble short can never open.
MIN_SHORT_CONFIDENCE = 6
MIN_LONG_CONFIDENCE  = 7

AI_HW_SECTOR            = "semis"
AI_HW_BUFFETT_THRESHOLD = 200.0  # Buffett Indicator % above which AI-hw rule arms
AI_HW_Z200_THRESHOLD    = 2.0    # |z200| above which the move is "elevated"

INDEX_SECTOR = "etfs_broad"


# ── macro normalisation ─────────────────────────────────────────────────────

def _fear_greed_score(macro: dict | None) -> int | None:
    """Pull the Fear & Greed score out of a macro dict.

    Accepts either the raw collector dict ({"score": 26, ...}) or a plain int.
    """
    if not macro:
        return None
    fg = macro.get("fear_greed", macro.get("fg"))
    if isinstance(fg, dict):
        fg = fg.get("score")
    if isinstance(fg, (int, float)):
        return int(fg)
    return None


def _buffett_pct(macro: dict | None) -> float | None:
    """Pull the Buffett Indicator percentage out of a macro dict."""
    if not macro:
        return None
    b = macro.get("buffett", macro.get("buffett_indicator"))
    if isinstance(b, dict):
        b = b.get("ratio_pct")
    if isinstance(b, (int, float)):
        return float(b)
    return None


# ── single-signal gate ──────────────────────────────────────────────────────

def _is_short(signal: dict) -> bool:
    return (
        signal.get("classification") == SHORT_CLASSIFICATION
        or signal.get("recommendation") == SHORT_RECOMMENDATION
    )


def _reclassify(signal: dict, rule: str, detail: str) -> None:
    """Turn a bubble_forming short into institutional_rebalancing → wait."""
    signal["v2_gate"] = {
        "action": "reclassified",
        "rule": rule,
        "detail": detail,
        "original_classification": signal.get("classification"),
        "original_recommendation": signal.get("recommendation"),
        "original_confidence": signal.get("confidence"),
    }
    signal["classification"] = WAIT_CLASSIFICATION
    signal["recommendation"] = WAIT_RECOMMENDATION


def gate_signal(
    signal: dict,
    long_horizon: dict | None,
    velocity: dict | None,
    macro: dict | None,
    sector: str | None = None,
) -> dict:
    """Apply the v2 short gates to a single classified signal in place.

    ``long_horizon`` / ``velocity`` are the per-ticker sub-dicts from the
    market pipeline; either may be empty/None.  Returns the same dict (mutated)
    for convenient chaining.
    """
    if not _is_short(signal):
        return signal  # never touch longs / waits / no_action

    lh        = long_horizon or {}
    vel       = velocity or {}
    ticker    = (signal.get("ticker") or "").upper()
    sector    = sector if sector is not None else get_sector(ticker)
    vol_dist  = lh.get("volume_dist_ratio")
    ext_200d  = lh.get("price_extension_200d")
    sustained = lh.get("sustained_days_60")
    z200      = vel.get("z_score_200d")

    fg        = _fear_greed_score(macro)
    buffett   = _buffett_pct(macro)

    # ── Rule 1: AI-hardware-in-bull reclassification ─────────────────────────
    # z200 must be elevated to the UPSIDE: a deeply negative z200 is a crash,
    # not institutional AI-capex demand, and must not arm this rule.
    if (
        sector == AI_HW_SECTOR
        and buffett is not None and buffett > AI_HW_BUFFETT_THRESHOLD
        and z200 is not None and z200 >= AI_HW_Z200_THRESHOLD
        and vol_dist is not None and vol_dist <= SHORT_VOL_DIST_MIN
    ):
        _reclassify(
            signal, "ai_hardware_bull",
            f"semis + Buffett {buffett:.0f}% + z200=+{z200:.1f} + "
            f"vol_dist={vol_dist:.2f}≤1.0 → institutional demand, not euphoria",
        )
        return signal

    # ── Rule 2: volume-distribution gate (PRIMARY) ───────────────────────────
    # A bubble-short needs distribution (down-volume > up-volume). vol_dist
    # missing is treated as "not confirmed" — we do not short on unconfirmed
    # distribution.
    if vol_dist is None or vol_dist <= SHORT_VOL_DIST_MIN:
        shown = f"{vol_dist:.2f}" if vol_dist is not None else "n/a"
        _reclassify(
            signal, "vol_dist",
            f"vol_dist={shown} ≤ 1.0 → accumulation/buying pressure, not distribution",
        )
        return signal

    # ── Rule 3: sustained-extension gate (secondary) ─────────────────────────
    ext_min = SHORT_EXT_MIN_INDEX if sector == INDEX_SECTOR else SHORT_EXT_MIN_SINGLE
    ext_ok       = ext_200d is not None and ext_200d > ext_min
    sustained_ok = sustained is not None and sustained >= SHORT_SUSTAINED_MIN
    if not (ext_ok and sustained_ok):
        ext_shown = f"{ext_200d:+.0%}" if ext_200d is not None else "n/a"
        sus_shown = f"{sustained}" if sustained is not None else "n/a"
        _reclassify(
            signal, "sustained_extension",
            f"ext={ext_shown} (need >{ext_min:.0%}) / sustained={sus_shown}/60 "
            f"(need ≥{SHORT_SUSTAINED_MIN}) → not a sustained bubble",
        )
        return signal

    # ── Rule 4: macro fear cap ───────────────────────────────────────────────
    # Survived all reclassification gates — still a bubble_forming short.
    # In a fear regime, cap confidence so it cannot open a position.
    if fg is not None and fg < MACRO_FEAR_CAP_THRESHOLD:
        original = signal.get("confidence", 0)
        if original > MACRO_BUBBLE_CONF_CAP:
            signal["v2_gate"] = {
                "action": "confidence_capped",
                "rule": "macro_fear_cap",
                "detail": f"F&G={fg} < {MACRO_FEAR_CAP_THRESHOLD} → "
                          f"bubble confidence capped {original}→{MACRO_BUBBLE_CONF_CAP}",
                "original_confidence": original,
            }
            signal["confidence"] = MACRO_BUBBLE_CONF_CAP

    return signal


# ── batch application over the daily pipeline ────────────────────────────────

def _gate_inputs_from_results(results: list[dict]) -> dict[str, dict]:
    """Build {ticker: {"long_horizon":..., "velocity":...}} from pipeline results."""
    out: dict[str, dict] = {}
    for r in results or []:
        ticker = (r.get("ticker") or "").upper()
        signals = r.get("signals") or {}
        market  = signals.get("market") or {}
        out[ticker] = {
            "long_horizon": market.get("long_horizon") or {},
            "velocity":     signals.get("velocity") or {},
        }
    return out


def apply_short_gates(
    signals: list[dict],
    results: list[dict],
    macro_context: dict | None,
) -> list[dict]:
    """Apply the v2 short gates to every classified signal.

    ``signals``  — parsed classifier output (mutated in place and returned).
    ``results``  — the daily pipeline results (carry market.long_horizon + velocity).
    ``macro_context`` — {"fear_greed": <collector dict or int>,
                         "buffett": <collector dict or pct>}.
    """
    inputs = _gate_inputs_from_results(results)
    reclassified = 0
    capped = 0
    for signal in signals or []:
        ticker = (signal.get("ticker") or "").upper()
        per    = inputs.get(ticker, {})
        before_cls = signal.get("classification")
        before_conf = signal.get("confidence")
        gate_signal(
            signal,
            long_horizon=per.get("long_horizon"),
            velocity=per.get("velocity"),
            macro=macro_context,
        )
        gate = signal.get("v2_gate")
        if gate and gate.get("action") == "reclassified":
            reclassified += 1
            logger.info(
                "[V2 GATE] %s %s→%s (%s)",
                ticker, before_cls, signal.get("classification"), gate.get("rule"),
            )
        elif gate and gate.get("action") == "confidence_capped":
            capped += 1
            logger.info(
                "[V2 GATE] %s confidence %s→%s (%s)",
                ticker, before_conf, signal.get("confidence"), gate.get("rule"),
            )
    if reclassified or capped:
        logger.info(
            "[V2 GATE] summary: %d reclassified to wait, %d confidence-capped",
            reclassified, capped,
        )
    return signals
