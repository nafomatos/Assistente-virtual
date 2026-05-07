# Validation Diagnostic — Empty Metrics (2026-05-07 run)

_Read-only code inspection. No files were modified. Branch: `diagnostic/validation-empty-metrics`._

---

## 1. Bug 1 Root Cause — Cluster Detector Never Fires in Backtest Mode

### Finding: sector map coverage gap makes clusters structurally impossible for some periods

The cluster detector (`tracker/cluster_detector.py`) requires **≥ 3 unique tickers from the same sector** within a 5-day business-day window. Cross-referencing `SECTOR_MAP` in `tracker/sectors.py` against the ticker lists in `backtesting/historical/main.py`:

| Period | Sector | Mapped tickers (in SECTOR_MAP) | Unmapped tickers |
|--------|--------|-------------------------------|------------------|
| COVID 2020 | `mega_tech` | AAPL, AMZN, GOOGL → **3** ✓ | TSLA (unmapped) |
| COVID 2020 | `commodities_metals` | GC=F, SI=F, HG=F → **3** ✓ | — |
| COVID 2020 | `semis` | NVDA → **1** | TSLA (unmapped) |
| COVID 2020 | `energy` | CL=F → **1** | — |
| **GameStop 2021** | `meme_retail` | GME, PLTR → **2** ✗ | AMC, BB, TSLA (all unmapped) |
| **GameStop 2021** | `commodities_metals` | GC=F, SI=F → **2** ✗ | — |
| **GameStop 2021** | `semis` | NVDA → **1** | — |
| 2022 Bear | `mega_tech` | AAPL, AMZN, GOOGL → **3** ✓ | TSLA (unmapped) |
| 2022 Bear | `fintech` | MSTR → **1** | — |
| 2022 Bear | `meme_retail` | PLTR → **1** | TSLA (unmapped) |
| 2008 Crisis | `mega_tech` | AAPL, AMZN, GOOGL → **3** ✓ | — |
| 2008 Crisis | `commodities_metals` | GC=F, SI=F, HG=F → **3** ✓ | — |
| 2008 Crisis | `energy` | CL=F → **1** | — |

**Definitive finding: GameStop 2021 cannot ever produce a cluster.** No sector in its 8-ticker universe reaches the threshold of 3. `meme_retail` has only GME + PLTR (AMC and BB are absent from `SECTOR_MAP`); `commodities_metals` has only GC=F + SI=F (HG=F is absent from the GameStop ticker list). One of the 4 periods is structurally incapable of validating cluster boost.

**Secondary finding: TSLA is absent from `SECTOR_MAP` entirely.** TSLA appears in 3 of 4 backtest universes (COVID, GameStop, 2022 Bear) but `get_sector("TSLA")` returns `None`. TSLA signals are silently skipped by `detect_clusters()` at this code path:

```python
# tracker/cluster_detector.py  line 97-99
sector = get_sector(ticker)
direction = get_direction_group(classification, recommendation)
if sector is None or direction is None:
    continue
```

**Why the other 3 periods also showed 0 boosts:**

For COVID, 2022 Bear, and 2008 — sectors with 3 mapped tickers DO exist (`mega_tech`, `commodities_metals`). However, two additional factors prevent clusters from forming in practice:

1. **Low signal density.** Each period averaged 1.4–1.7 Claude calls per trading day across all tickers. For `mega_tech` to cluster, AAPL, AMZN, and GOOGL must ALL receive signals in the SAME direction within a 5-day window. With each firing roughly once per 3 days, three specific tickers co-firing in the same direction within 5 days is statistically infrequent.

2. **Direction-group compatibility required.** Even when 3 mega_tech tickers do generate signals within 5 days, they must map to the same `direction_group`. The system prompt classifies large-caps toward `institutional_rebalancing` ("institutional" group) by default. Commodities also default toward `institutional_rebalancing`. Unless the Divergence Rules produce `irrational_panic` or `bubble_forming` for all 3 co-firing tickers simultaneously, no cluster forms.

Both factors together explain why historically plausible cluster sectors never reached the threshold — **but this cannot be verified without examining the actual signal logs**. What IS verified by code inspection: GameStop 2021 is structurally impossible.

---

## 2. Bug 2 Root Cause — Hit Rates All "—"

### Finding: confidence penalty is applied twice, suppressing all directional recommendations

This is a definitive code-level bug. The confidence penalty is applied **twice** to every historical signal:

**Application 1 — inside Claude's reasoning** (via `HISTORICAL_MODE_ADDENDUM` in `claude_advisor/prompts.py` + the `macro_section` string built in `runner.py`):

```python
# backtesting/historical/runner.py  lines 581-587
macro_section = (
    f"\n\nMacro context (historical proxy):\n"
    ...
    f"- Confidence penalty: {synth['confidence_penalty']} "
    f"(reduce your output confidence by this amount)\n"       # ← tells Claude to apply penalty
    ...
)
```

```python
# backtesting/historical/runner.py  lines 51-63  (HISTORICAL_MODE_ADDENDUM)
"""
Apply the confidence_penalty indicated — reduce your raw confidence by that amount before outputting.
"""
```

Claude reads these instructions and reduces its confidence score BEFORE writing the JSON output. If Claude's internal assessment is 8, it outputs `"confidence": 6`.

**Application 2 — Python post-processing** in `runner.py`:

```python
# backtesting/historical/runner.py  lines 601-603
raw_confidence = parsed.get("confidence", 0) if parsed else 0   # ← reads ALREADY-PENALIZED value
penalty        = synth["confidence_penalty"]
stored_confidence = max(1, raw_confidence - penalty) if raw_confidence > 0 else 0  # ← deducts again
```

`raw_confidence` is Claude's **output** (already penalized). Python then subtracts `penalty` a second time.

**Net effect on recommendations:**

The system prompt constraint (line 105 of `claude_advisor/prompts.py`) states:
> `contrarian_buy only when confidence ≥ 7.`

This applies to Claude's OUTPUT confidence. After Application 1, Claude's output confidence = `raw_internal − 2`. For `contrarian_buy` to appear, the output must be ≥ 7:
```
raw_internal − 2 ≥ 7  →  raw_internal ≥ 9
```

Confidence 9–10 is described in the system prompt as reserved for "rare, high-conviction moments" where "all three signal families align, macro context reinforces the call." In backtest mode with synthetic VIX proxy instead of real social sentiment, Claude rarely assesses raw_internal ≥ 9. The result: `contrarian_buy` is systematically replaced by `wait`.

**Why `reduce_exposure` also disappears:**

`reduce_exposure` (from `bubble_forming`) has no confidence threshold in the prompt — but `bubble_forming` requires:
> `Price above 200d average AND Social Heat "explosive" AND tone "bullish"`

In backtest mode, `heat` is derived from VIX via `get_synthetic_sentiment()`:

```python
# backtesting/historical/sentiment_proxy.py  lines 37-44
if vix_value >= 50:
    heat = "explosive"
elif vix_value >= 35:
    heat = "elevated"
elif vix_value >= 25:
    heat = "stable"
else:
    heat = "low"
```

During crash/bear periods (which comprise most of the 4 backtest periods), VIX is elevated → heat is "explosive"/"elevated" but **tone is "bearish"** (prices crashing). The Divergence Rules for `bubble_forming` require "explosive" heat AND "bullish" tone simultaneously. In a crash, both rarely coexist.

In pre-crash phases (early COVID, early 2022 Bear), prices are near all-time highs but VIX is low (15–20) → heat is "low". Without "explosive" heat, the Divergence Rules default to "ambiguous" → `wait/no_action`.

The net result across 487 total signals: essentially **zero signals produce `contrarian_buy` or `reduce_exposure`** recommendations. `_calculate_hit_rates()` skips direction-neutral signals:

```python
# backtesting/historical/runner.py  lines 320-323
hit = outcome.get("hit")
if hit is None:
    continue  # direction-neutral
```

`by_recom` accumulates no entries for `contrarian_buy` or `reduce_exposure`. `_combined_hit_rate()` reads these empty entries as total = 0 → returns `(None, 0)` → displayed as "—".

**This also explains the "identical verdict text" observation.** If no directional signals appear in any run (on or off), `period_pass[period]` = False for all periods. The verdict is "FAIL ✗ — 0/4 periods improved by ≥3pp at d+30" with the "DO NOT FLIP" recommended action block — which would look structurally similar across runs because it's template text with no real numbers to differentiate it.

---

## 3. Proposed Fixes

### Fix for Bug 2 (high priority — blocks all real validation)

**Remove the penalty instruction from the prompt side.** The Python code in `runner.py` already applies the penalty correctly. The prompt instruction is redundant and causes double-counting.

**File:** `backtesting/historical/runner.py`  
**Lines to change:** `macro_section` string (~line 581)

```python
# BEFORE (double-penalizes):
macro_section = (
    f"\n\nMacro context (historical proxy):\n"
    f"- Fear & Greed proxy (VIX-derived): {fg_proxy}/100\n"
    f"- Synthetic Sentiment (VIX-proxy): heat={synth['heat']}, tone={synth['tone']}\n"
    f"- VIX on this date: {vix_value:.1f}\n"
    f"- Confidence penalty: {synth['confidence_penalty']} "
    f"(reduce your output confidence by this amount)\n"         # ← REMOVE THIS LINE
    f"- Note: sentiment derived from VIX proxy, not real social data. "
    f"Confidence should reflect this uncertainty."
)

# AFTER (single-penalizes, Python side only):
macro_section = (
    f"\n\nMacro context (historical proxy):\n"
    f"- Fear & Greed proxy (VIX-derived): {fg_proxy}/100\n"
    f"- Synthetic Sentiment (VIX-proxy): heat={synth['heat']}, tone={synth['tone']}\n"
    f"- VIX on this date: {vix_value:.1f}\n"
    f"- Note: sentiment derived from VIX proxy, not real social data. "
    f"Confidence should reflect this uncertainty."
)
```

**File:** `backtesting/historical/runner.py`  
**Lines to change:** `HISTORICAL_MODE_ADDENDUM` constant (~line 51)

```python
# BEFORE:
HISTORICAL_MODE_ADDENDUM = """
## Historical Backtest Mode
...
Apply the confidence_penalty indicated — reduce your raw confidence by that amount before outputting.
Your classification and recommendation logic is unchanged."""

# AFTER:
HISTORICAL_MODE_ADDENDUM = """
## Historical Backtest Mode
...
Your classification and recommendation logic is unchanged.
Note: a post-processing confidence adjustment will be applied to reflect VIX-proxy uncertainty."""
```

The Python penalty application in lines 601–603 stays unchanged:
```python
raw_confidence    = parsed.get("confidence", 0) if parsed else 0
penalty           = synth["confidence_penalty"]
stored_confidence = max(1, raw_confidence - penalty) if raw_confidence > 0 else 0
```

This means:
- Claude outputs raw confidence (e.g., 8 for a strong irrational_panic signal)
- The `contrarian_buy ≥ 7` constraint fires correctly on raw confidence (8 ≥ 7 ✓)
- Python then stores max(1, 8−2) = 6 as the penalized stored confidence

### Fix for Bug 1 (required for GameStop period; improves all periods)

**Option A (minimal) — Add missing tickers to SECTOR_MAP:**

```python
# tracker/sectors.py
SECTOR_MAP = {
    "semis":              [...],
    "fintech":            [...],
    "mega_tech":          ["AAPL", "MSFT", "GOOGL", "META", "AMZN", "TSLA"],  # add TSLA
    "commodities_metals": ["GC=F", "SI=F", "HG=F"],
    "energy":             ["CL=F", "NG=F"],
    "agri":               ["ZS=F"],
    "meme_retail":        ["GME", "AMC", "BB", "RDDT", "PLTR", "RKLB", "ASTS"],  # add AMC, BB
    "etfs_broad":         ["SPY", "QQQ"],
}
```

This enables cluster detection for TSLA (now `mega_tech`) and AMC/BB (now `meme_retail`). GameStop 2021 then has 3 `meme_retail` tickers (GME, AMC, BB → all high-beta meme stocks) and becomes structurally capable of forming clusters.

**Caveat on TSLA classification:** Some operators may prefer `high_beta_consumer` or its own group. The choice of `mega_tech` is defensible (TSLA is an S&P 500 mega-cap) but debatable.

**Option B (alternative) — Replace GameStop period tickers:**

Replace the GameStop 2021 ticker list to include tickers that ARE in `SECTOR_MAP`:
```python
"gamestop_2021": {
    "tickers": ["GME", "PLTR", "GC=F", "SI=F", "HG=F", "TSLA", "NVDA", "AAPL"],
    ...
}
```

This gives `meme_retail` = GME + PLTR, `commodities_metals` = GC=F + SI=F + HG=F (3 ✓), `semis` = NVDA, `mega_tech` = AAPL + TSLA (if TSLA added). Less historically authentic but immediately makes the period clusterizable.

**Recommendation: Option A.** It fixes the sector map correctly rather than working around it by changing the historical universe.

---

## 4. Risk Assessment

### Fix 2 (remove prompt-side penalty) — Risk: LOW

- **Production daily pipeline:** `HISTORICAL_MODE_ADDENDUM` and the `macro_section` penalty string are used ONLY in `backtesting/historical/runner.py`. The production `main.py` pipeline calls `claude_advisor/prompts.py` directly (the `SYSTEM_PROMPT`) but does NOT import `HISTORICAL_MODE_ADDENDUM` or the `macro_section` logic. No production code path is affected.
- **Backtest result comparability:** Any previously computed backtest results (JSON files in `backtesting/historical/results/`) were produced with the double penalty. Those results must be deleted and re-run after the fix; they are not comparable to post-fix results. This is the correct behavior — cached results from the broken state should be discarded.
- **Claude behavior change:** Removing the prompt-side penalty means Claude's output confidence will be higher for the same signals. This is intentional: the penalty should be applied once (Python-side), not twice. Some signals that previously got `wait` will now correctly get `contrarian_buy` or `reduce_exposure`.

### Fix 1 (SECTOR_MAP additions) — Risk: LOW

- **Production daily pipeline:** `tracker/sectors.py` is imported by `tracker/cluster_detector.py`, which is gated behind `CLUSTER_BOOST_ENABLED=false` in production. The flag is not flipped; production pipeline behavior is unchanged.
- **Existing cluster detection behavior:** Adding TSLA, AMC, BB to the map can only INCREASE cluster detection (more tickers eligible), never decrease it. The boost logic is additive.
- **Backtest result comparability:** Same as Fix 2 — any cached results must be re-run.

---

## 5. Re-Validation Plan

1. **Merge fix PRs** (one for Bug 2 in `runner.py`, one for Bug 1 in `sectors.py`).
2. **Delete cached results** — remove any `.json` files under `backtesting/historical/results/` that were produced by the broken run, so the harness doesn't load stale data.
3. **Trigger the workflow** from Actions tab → Cluster Boost Validation → Run workflow:
   - "Smoke test": UNCHECKED
   - "Single period": leave blank (run all 4)
   - "Force re-run": CHECK (ensures no stale cache is reused)
4. **Expected results after fixes:**
   - `total_signals_generated` still in same range (119/58/200/110 — signal generation is unaffected)
   - `d+10` and `d+30` hit rates are **non-null** (values other than "—") for all periods and both boost states
   - `boosted_count` > 0 for at least COVID, 2022 Bear, and 2008 periods (GameStop: depends on whether AMC/BB are mapped; sectors with 3 tickers now exist)
   - Verdict (PASS/FAIL) is based on actual data, not template defaults

5. **If boosted_count is still 0 after fixes:** The cluster simply didn't form in these historical periods given signal density. That is a valid finding (cluster boost has no effect in low-signal environments). Add diagnostic logging to `runner.py` to emit the per-day cluster detection result for verification:
   ```python
   if cluster_boost and day_signals:
       _write_day_signal_log(tmp_signals_dir, day, day_signals)
       active_clusters = detect_clusters(...)
       logger.info(
           "[CLUSTER] %s: wrote %d signals → %d active clusters",
           day, len(day_signals), len(active_clusters)
       )
   ```

---

_Read-only inspection. No code was modified. Generated 2026-05-07._
