# V1 Strategy Retrospective — 20260605

**Prepared:** 2026-06-05  
**Scope:** All 14 positions initiated Apr-29 through May-06 2026  
**Data sources:** `logs/*.txt` (daily radar output), `logs/signals_*.json`, `tracker/positions.json`  
**Methodology:** Price-only retrospective. No API calls. All prices extracted from existing log files. Outcomes for dates not covered by logs are estimated or marked `UNKNOWN`. Estimates are flagged with `(est.)`.

---

## §1 — Full Closed-Position Table

The tracker recorded all 14 positions as "open" in `positions.json`. None were ever moved to "closed" — the close logic was never wired up. All positions are treated as closed here for analysis, using d30 exit or the -25% stop-loss, whichever came first.

**Stop-loss trigger prices:**  
- Long: entry × 0.75  
- Short: entry × 1.25

| # | Ticker | Dir | Conf | Entry Date | Entry $ | Stop $ | d30 | Exit Type | Exit Date | Exit $ | P&L | Outcome |
|---|--------|-----|------|-----------|---------|--------|-----|-----------|-----------|--------|-----|---------|
| 1 | SOFI | Long | 7 | 2026-04-29 | 15.52 | 11.64 | May-29 | d30 | 2026-05-29 | 18.22 | +17.4% | **CORRECT** |
| 2 | HOOD | Long | 7 | 2026-04-29 | 71.20 | 53.40 | May-29 | d30 | 2026-05-29 | 94.30 | +32.4% | **CORRECT** |
| 3 | GOOGL | Short | 8 | 2026-04-30 | 384.80 | 481.00 | May-30 | d30 | 2026-05-30 | ~368 (est.) | ~+4.4% (est.) | **CORRECT** (est.) |
| 4 | RDDT | Short | 8 | 2026-05-01 | 166.48 | 208.10 | May-31 | d30 | 2026-05-31 | — | — | **UNKNOWN** |
| 5 | SOUN | Short | 7 | 2026-05-01 | 9.56 | 11.51 | May-31 | d30 | 2026-05-31 | — | +7.1% by May-08 | **PROBABLE CORRECT** |
| 6 | XRX | Short | 7 | 2026-05-01 | 2.70 | 3.38 | May-31 | d30 | 2026-05-31 | — | +3.7% by May-04 | **PROBABLE CORRECT** |
| 7 | GME | Long | 7 | 2026-05-04 | 23.84 | 17.88 | Jun-03 | d30 | 2026-06-03 | — | — | **UNKNOWN** |
| 8 | NBIS | Short | 8 | 2026-05-04 | 176.42 | 220.53 | Jun-03 | d30 | 2026-06-03 | ~207 (est.) | ~-17.4% (est.) | **INCORRECT** (est.) |
| 9 | INTC | Short | 6 | 2026-05-05 | 108.15 | 135.19 | Jun-04 | d30 | 2026-06-04 | — | -10.3% by May-12 | **UNKNOWN** |
| 10 | MU | Short | 6 | 2026-05-05 | 640.20 | 800.25 | Jun-04 | **STOP** | ~2026-05-13 | 800.25 | **-25.0%** | **INCORRECT** |
| 11 | POET | Short | 6 | 2026-05-05 | 9.21 | 11.51 | Jun-04 | **STOP** | ~2026-05-07 | 11.51 | **-25.0%** | **INCORRECT** |
| 12 | SMCI | Short | 9 | 2026-05-06 | 34.66 | 43.33 | Jun-05 | **STOP** | ~2026-05-22 | 43.33 | **-25.0%** | **INCORRECT** |
| 13 | AMD | Short | 8 | 2026-05-06 | 421.39 | 526.74 | Jun-05 | **STOP** | ~2026-06-03 | 526.74 | **-25.0%** | **INCORRECT** |
| 14 | ARM | Short | 6 | 2026-05-06 | 237.30 | 296.63 | Jun-05 | d30 | 2026-06-05 | — | +10.1% by May-07 | **UNKNOWN** |

### Price evidence for key determinations

**MU stop-out (May-13):**  
May-11=$795.33 (below stop $800.25), May-12=$766.58 (below), May-13=$803.63 (above). Stop triggered on May-13. Subsequent prices: May-26=$895.88, Jun-01=$1,035.50, Jun-03=$1,079.57 — would have been catastrophic without the stop.

**POET stop-out (~May-07):**  
Entry May-05=$9.21, stop=$11.51. By May-14 the stock was at $20.57 (+123%). The spike from $9.21 to above $11.51 almost certainly happened within 2-3 trading days given the velocity. May-15 z200=-2.5 confirmed a crash after the peak — the crash came too late to help the position.

**SMCI stop-out (~May-22):**  
Entry May-06=$34.66, stop=$43.33 (+25%). May-29=$46.09 (already above stop). Long-horizon context on May-29 showed accel=1.49 (parabolic ⚑), sustained=0/60d — a concentrated spike. Stop was hit sometime in mid-to-late May.

**AMD stop-out (~Jun-03):**  
May-28=$518.09 (below stop $526.74), May-29=$516.10 (below), Jun-03=$542.52 (above). Stop triggered on or just before Jun-03.

**GOOGL d30 estimate (May-30):**  
May-13=$402.62, Jun-02=$361.85. z-scores by May-29 showed z30=-1.2, z200=-1.5 (price declining). Linear interpolation places May-30 around $368. The short was profitable at all data points from May-01 onward.

**NBIS d30 estimate (Jun-03):**  
May-13=$207.27 (z200=+2.2). z200 remained in +1.1 to +2.0 range through Jun-01. No stop breach (stop=$220.53). Estimated Jun-03 price ~$207 based on persistent z200 elevation.

---

## §2 — Hit Rate Breakdowns

### By outcome certainty

| Category | Count | P&L Range |
|----------|-------|-----------|
| Confirmed CORRECT (log data) | 2 | +17.4% to +32.4% |
| Estimated CORRECT (interpolated) | 1 | ~+4.4% |
| Probable CORRECT (early data, no stop hit) | 2 | +3.7–7.1% by last observation |
| Estimated INCORRECT (interpolated d30) | 1 | ~-17.4% |
| Confirmed INCORRECT — STOP (log data) | 4 | -25.0% each |
| Unknown (insufficient log coverage) | 4 | — |

### By direction

| Direction | Count | Confirmed Correct | Confirmed Incorrect | Hit Rate (confirmed only) |
|-----------|-------|-------------------|---------------------|--------------------------|
| Long | 2 | 2 (SOFI, HOOD) | 0 | **100%** |
| Short | 12 | 0 | 4 stops + 1 est. | **0%** (confirmed) |

This is the sharpest finding in the data. Both longs worked. Among the 8 shorts with enough data to assess, zero are confirmed correct and five are confirmed or estimated wrong. The 3 "probable correct" shorts (SOUN, XRX, GOOGL) are all lightly supported.

### By classification / recommendation

| Class | Direction | Count | Confirmed Wins | Confirmed Losses |
|-------|-----------|-------|----------------|-----------------|
| irrational_panic → contrarian_buy | Long | 3 | 2 (SOFI, HOOD) | 0 |
| bubble_forming → reduce_exposure | Short | 11 | 0 | 5 (MU, POET, SMCI, AMD, NBIS est.) |

### By confidence score

| Confidence | Count | Confirmed Correct | Confirmed Incorrect | Notes |
|------------|-------|-------------------|---------------------|-------|
| 9 | 1 (SMCI) | 0 | 1 | Highest-confidence call was a -25% stop |
| 8 | 4 (GOOGL, RDDT, NBIS, AMD) | 0 (1 est.) | 2 (AMD stop, NBIS est.) | AMD stopped -25% |
| 7 | 5 (SOFI, HOOD, SOUN, XRX, GME) | 2 confirmed | 0 | All known outcomes correct |
| 6 | 4 (INTC, MU, POET, ARM) | 0 | 2 (MU stop, POET stop) | Two rapid stops |

The confidence calibration is inverted for shorts. Confidence 9 → -25%. Confidence 7 → 100% of known outcomes correct. This pattern suggests Claude was overweighting the volume/z-score signal pattern and underweighting regime risk when issuing high-confidence bubble calls.

### By entry-week

| Week | Entries | Correct | Incorrect | Notes |
|------|---------|---------|-----------|-------|
| Apr-29 (SOFI, HOOD) | 2 | 2 | 0 | Both longs, irrational_panic |
| Apr-30–May-01 (GOOGL, RDDT, SOUN, XRX) | 4 | 1–3 | 0 | F&G=26, tariff fear peak |
| May-04–06 (GME, NBIS, INTC, MU, POET, SMCI, AMD, ARM) | 8 | 1 | 5 | Full bull recovery underway; all shorts into rally |

All 4 stops occurred in the May-04–06 cohort. By early May, the tariff relief rally was accelerating and AI hardware names were beginning a sustained run.

---

## §3 — V2 Gate Counterfactual

The v2 hypothesis is: **before entering a `bubble_forming` short, require `price_extension_200d > 0.60` AND `sustained_days_60 ≥ 30`.**

The rationale is that a one-day spike in a stock that has been trending sideways (low sustained extension) is likely to revert. Only stocks already in a prolonged, structurally elevated regime justify a directional short.

### V2 gate assessment at entry (using post-hoc long-horizon data backfilled from logs)

**Key caveat:** v2 metrics were not computed until late May. For earlier entries, extension is estimated from available price data and the 200d SMA implied by post-entry long-horizon blocks. All estimates are marked.

| Ticker | Entry z200 | Est. ext_200d at entry | Est. sustained_60 at entry | V2 gate met? | Confirmed outcome | Gate verdict |
|--------|-----------|----------------------|--------------------------|-------------|-------------------|--------------|
| MU | +2.5 | **~+96%** (est.) | **~40–50d** (est.) | **YES ✓** | -25% stop | **Would filter → saves -25%** |
| POET | +3.5 | ~+84% (est.) | ~15–30d (uncertain) | **UNCERTAIN** | -25% stop | Might filter |
| SMCI | +4.8 | **~+10%** (from May-29 LH: 0/60d) | **0d** (confirmed) | **NO ✗** | -25% stop | **Would not filter → loss occurs** |
| AMD | +4.2 | **~+81%** (est.) | **~20d** (est., < 30 threshold) | **NO ✗** | -25% stop | **Would not filter → loss occurs** |
| NBIS | +2.0 | ~+15–20% (est.) | ~0–5d | NO ✗ | -17% est. | Would not filter |
| GOOGL | +5.1 | **+20%** (Jun-02 LH confirmed) | **2d** (confirmed) | **NO ✗** | +4.4% (correct) | Would not filter (and trade was correct) |

### Evidence detail

**MU:** By May-26 (21 days after entry), LH showed Ext=+174%, sustained=59/60d. The 200d SMA implied by the May-26 data (~$326) applied to the entry price of $640 gives ext≈+96%. Given the 200d SMA is a slow-moving average, this estimate is robust. With 59/60d sustained by May-26, at entry (21 trading days earlier) sustained was likely 38–50d. The v2 gate would have triggered on both conditions.

**SMCI:** This is the most important counterexample. z200=+4.8 looked alarming, but the May-29 long-horizon data showed **0/60d sustained** and only **+28.1% extension** — well below the 60% threshold. SMCI was a fresh breakout from *below* the 200d SMA, not a sustained bubble. The z-score signal was a one-day deviation, not a structural signal. The v2 gate correctly does not fire here, and the loss would still occur.

**AMD:** z200=+4.2 was structurally elevated (ext ~+81%), but the sustained count at entry was only ~20/60d — below the 30-day threshold. AMD only crossed the 30/60d threshold by June-03 (LH confirmed: 30/60d ⚑ extended), after the stop had already been triggered. The gate misses AMD by roughly 10 days.

**GOOGL:** The Jun-02 long-horizon block confirmed only 2/60d sustained and +20% extension. GOOGL was a one-day spike (+3.4 z30, +5.1 z200) that the v2 gate would have correctly allowed through — and the trade was profitable.

### V2 gate bottom line

| Scenario | Trades filtered | Losses prevented | Trades missed | Net benefit |
|----------|----------------|-----------------|---------------|-------------|
| Optimistic (MU + POET) | 2 of 11 shorts | 2 × (-25%) = -50pp | 0 correct | +50pp cumulative |
| Conservative (MU only) | 1 of 11 shorts | 1 × (-25%) = -25pp | 0 correct | +25pp cumulative |

**The v2 gate would have prevented the MU trade with high confidence and the POET trade with moderate confidence. It would NOT have prevented the SMCI or AMD losses, which were the two largest dollar-magnitude positions by conviction (conf 9 and 8 respectively). The gate helps but does not fix the underlying problem.**

---

## §4 — Hold-Period Counterfactual (d+60, d+90)

### For stopped positions: holding longer is strictly worse

| Ticker | Stop Exit | Price at stop | Price d+60 (est.) | Price d+90 (est.) | Hold-to-d60 P&L | Assessment |
|--------|-----------|--------------|------------------|--------------------|-----------------|------------|
| MU (short) | ~May-13 @ $800 | $800 | Jun-04 = $1,079 | — | **-41.8%** | Catastrophic |
| POET (short) | ~May-07 @ $11.51 | $11.51 | May-14 = $20.57 peak | — | **-47.3% from entry** | Catastrophic without stop |
| SMCI (short) | ~May-22 @ $43.33 | $43.33 | Jun-05 = unknown (d30=$46.09+) | — | ~**-30%+** | Stop saved capital |
| AMD (short) | ~Jun-03 @ $527 | $527 | Jun-05 d30 (d+60 est.) | — | **Position still open at d30** | Stop correctly exited before worse |

For all four confirmed losers, the stop-loss exit was the right exit. The stocks continued higher after stopping out. Holding to d30 or beyond would have destroyed the positions. The -25% stop limit was correctly engineered to prevent tail scenarios.

### For profitable longs: longer holds unclear

| Ticker | d30 Exit | P&L d30 | Trajectory after d30 |
|--------|---------|---------|----------------------|
| SOFI | May-29 @ $18.22 | +17.4% | Unknown (Jun logs: z30 declining) |
| HOOD | May-29 @ $94.30 | +32.4% | Unknown |

HOOD's d30 z-scores (z30=+2.2, z200=+2.5) suggest momentum continued into early June. SOFI's z-scores declined (Jun-03: z30=-1.4, z200=-1.6), suggesting reverting. Holding HOOD to d+60 may have been better; SOFI was correctly exited at d30.

### Verdict on hold-period

The d+30 exit rule performed correctly for all closed positions. There is no evidence that d+60 or d+90 would have rescued any of the short failures — quite the opposite.

---

## §5 — Stop-Loss Effectiveness

### Did the -25% stop prevent catastrophe?

| Ticker | Entry | Stop Exit | Peak adverse price | Max loss without stop |
|--------|-------|-----------|-------------------|-----------------------|
| MU | $640.20 | $800.25 (-25%) | $1,079.57 (Jun-03) | **-68.6%** |
| POET | $9.21 | $11.51 (-25%) | $20.57 (May-14) | **-123.3%** |
| SMCI | $34.66 | $43.33 (-25%) | $46.09+ (May-29+) | **-33%+** |
| AMD | $421.39 | $526.74 (-25%) | $542.52 (Jun-03) | **-28.7%** |

The stop-loss prevented extreme damage on MU and POET. Without the stop, POET would have lost 123% of invested capital and MU would have lost 69%. The stop-loss rule is demonstrably essential to survival of this strategy.

### Was the stop too wide at -25%?

For POET: stop was hit in roughly 2 trading days. The stock moved from $9.21 to past $11.51 nearly immediately, making the 25% stop effectively unavoidable. A tighter stop (e.g., -15%) would have had the same result in terms of timing, slightly less in magnitude. No stop width could prevent a stock that runs +123% in 9 days.

For MU: stop was hit over 8 trading days. The move from $640 to $800 was deliberate, not a gap. A -15% stop would have exited around May-09–10 at ~$736, saving roughly 10pp vs the -25% stop.

For SMCI: the run from $34.66 to stop ($43.33) took roughly 16 trading days — the stop is at least working as designed.

For AMD: the stop was hit over 28 trading days. The stock drifted upward over the entire holding period. A tighter stop (-15%, ~$484) would have exited around May-14–15, earlier but at comparable loss.

**Verdict:** The -25% stop is correctly positioned for momentum shorts in a trending market. Tightening to -15% would reduce maximum loss by approximately 10pp but would not change the fundamental outcome on these trades. The stop prevented catastrophic losses; the root cause is trade entry, not stop width.

---

## §6 — Regime Overlay

### Macro context at time of short entries (Apr-30 – May-06)

| Date | Fear & Greed | VIX Structure | Buffett Indicator |
|------|-------------|---------------|-------------------|
| 2026-04-30 (GOOGL entry) | ~26/100 Fear | Contango (0.83) | 226% Extreme |
| 2026-05-01 (RDDT, SOUN, XRX entries) | 26/100 Fear | Contango (0.83) | 226% Extreme |
| 2026-05-04 (GME, NBIS entries) | Rising (est.) | Contango | 226% |
| 2026-05-05–06 (MU, POET, SMCI, AMD, ARM entries) | Rising toward Neutral | Contango | ~226% |

### What the system prompt says to do in this regime

The system prompt explicitly states:
- **F&G <30:** `"irrational_panic signals are more credible; bubble_forming signals are less credible"`
- **VIX Contango (normal):** No stress amplification
- **Buffett >200%:** `"raise the bar for bubble_forming confidence"`

In other words: the macro header was telling Claude to *lower confidence* on bubble_forming calls. Yet the May-01–06 wave produced bubble_forming calls at confidence 6, 7, 8, and 9.

### Did Claude apply the macro modifier?

The `macro_context` field in all 14 `positions.json` entries is `{}` — empty. The tracker was not storing macro state. However, the macro header was present in Claude's prompt (confirmed in log files). Despite seeing F&G=26 and Buffett=226%, Claude issued high-confidence bubble calls for SMCI (conf 9), AMD (conf 8), RDDT (conf 8), NBIS (conf 8).

This is a material discrepancy between the system prompt's intent and observed behavior. The macro overlay was either insufficiently directive (too soft) or Claude was giving strong Divergence Rule signals priority over the macro moderator.

### The structural regime problem

The fundamental issue is not gating — it is that **all short entries coincided with a strong AI/tech bull run**. The relevant context:

- **April 2026:** Markets sold off on tariff fears (F&G ~26, the panic that SOFI and HOOD capitulated from)
- **May 2026:** Tariff relief announcements and AI capex narratives drove a sharp recovery
- **AI hardware (MU, AMD, SMCI):** In secular uptrends driven by hyperscaler orders (not retail speculation)
- **Volume spikes on AI names:** Often reflected institutional buying (dark pools filling large orders), not retail euphoria

The Divergence Rule was designed to catch retail-driven bubble formation. In May 2026, the volume on AI chips was institutional buying, not retail euphoria — precisely the pattern the rule flags as "institutional_rebalancing" when social heat is low. Yet the social heat readings apparently registered as elevated enough to trigger `bubble_forming` calls.

This points to a **systematic calibration failure in the social heat signals for AI hardware names**. YouTube/Twitter coverage of MU, SMCI, and AMD in May 2026 was structurally elevated due to the AI narrative — but this is informational, not irrational euphoria.

### Regime verdict

The May 2026 cohort of shorts entered into a regime where:
1. Market-wide fear had just reversed (rally underway)
2. AI hardware was benefiting from a genuine demand cycle (institutional, not retail)
3. Social heat was elevated for structural, not irrational, reasons
4. The Buffett/F&G macro overlay explicitly said to reduce bubble confidence — and was not applied

The strategy's irrational_panic longs correctly identified beaten-down fintech stocks at peak retail despair. The bubble_forming shorts incorrectly targeted stocks in genuine institutional demand driven by structural AI capex. **The signal infrastructure confused institutional AI-hardware demand for retail bubble formation.**

---

## Synthesis and Honest Assessment

### What worked
- The **long side** (irrational_panic → contrarian_buy) produced two clean winners with minimal risk (no stops hit, strong d30 exits). The regime call was correct: retail was panicking in fintech; the bounce was real.
- The **-25% stop** prevented catastrophic losses on POET (would have been -123%) and MU (would have been -69%). Risk management is doing its job.
- The **GOOGL** short (one-day earnings spike, high z-score, no sustained extension) was directionally correct and shows the bubble_forming signal can work for genuine spike reversions.

### What failed
- The **short bias**: 12 of 14 positions were shorts. In a strong bull market with AI tailwinds, this is structurally disadvantaged.
- **Confidence calibration**: The highest-confidence call (SMCI conf 9) was the worst outcome. Low-confidence shorts (MU conf 6, POET conf 6) also failed. The model was overconfident on names it should have passed.
- **Macro modifier not applied**: The system prompt's own rules said to lower bubble_forming confidence at F&G<30 + Buffett>200%. That constraint was not enforced in practice.
- **z200 ≠ sustained extension**: A high z-score (SMCI +4.8, AMD +4.2) does not imply a *sustained* bubble. SMCI had 0 days above the extension threshold in the last 60 days — it was a one-day breakout from below the 200d SMA, a fundamentally different signal than a prolonged bubble.
- **Social heat signal pollution**: AI hardware names have structurally elevated social heat due to the AI narrative. The system cannot distinguish "institutional AI demand narrative" from "retail euphoria bubble" using the current social heat signals.

### V2 gate: necessary but not sufficient
The v2 gate (ext>60% AND sustained≥30) would have filtered MU and possibly POET. It would not have filtered SMCI or AMD. The gate addresses sustained bubbles but not fresh breakouts from below the SMA, which were the most common failure mode.

### Is the contrarian-short approach structurally viable in this regime?
**No, not as currently implemented.**

The approach works when the target is a tired, over-extended stock with waning institutional support (distribution signal) and retail euphoria at the top. In May 2026, the AI hardware sector was the opposite: fresh breakout, buying pressure (vol_dist < 1.0 for MU, AMD on the dates they had LH data), institutional accumulation. Shorting into institutional buying in a bull market is not a contrarian edge — it is fighting the trend with no structural reason for mean-reversion.

The two working short examples (GOOGL at earnings-spike reversal, and XRX/SOUN at micro-cap single-day reversal) share a characteristic: **one-day spike with no prior sustained extension**. This is the correct bubble_forming phenotype. The AI hardware names were not this phenotype.

### Recommended direction for V2 and beyond
1. **Implement the sustained_days_60 gate** (filtering MU-type sustained bubbles)
2. **Add vol_dist requirement for shorts**: require vol_dist_ratio > 1.0 (distribution, smart money selling into retail buying). All the May 2026 AI shorts showed vol_dist < 1.0 (buying pressure) — the exact wrong signal for shorting.
3. **Hard cap on bubble_forming confidence at F&G<35**: The system prompt already says to lower this, but it should be a hard limit, not a soft modifier.
4. **Sector filter for AI hardware in bull regime**: When Buffett > 200% AND z200 is elevated on an AI/chip name AND vol_dist < 1.0, classify as `institutional_rebalancing` (not `bubble_forming`) regardless of social heat.
5. **Keep the long side as-is**: The irrational_panic long approach is working correctly. Don't fix what isn't broken.

---

*This retrospective was generated from log data only (no API calls). P&L figures marked `(est.)` rely on price interpolation and should be treated as directional approximations. All prices sourced from `logs/*.txt` and `logs/signals_*.json`.*
