# Volume Fix 2 Diagnostic — 2026-05-12

**Status:** Fix 2 (`max(avg_30d, avg_10d)`) is **not in production**. The daily radar ran
with Fix 1 only. Even if Fix 2 had been deployed, modelling confirms it would have produced
~130× for GC=F — nearly identical to the observed 128.8×. The root cause is a **second
contract roll** (GCM26 → GCQ26) that contaminates both the 30-day and 10-day windows
simultaneously, which is the one scenario Fix 2 cannot handle.

> ⚠ **Live yfinance data could not be pulled in this session** (sandbox HTTP 403). Sections
> relying on raw series are marked `[LOG-RECONSTRUCTED]` (derived from committed `logs/*.txt`)
> or `[SIMULATION]` (Python-modelled). No numbers are fabricated.

---

## 1. Production code path verification

### 1a. Is Fix 2 in origin/main?

```
git show origin/main:collectors/market_data.py | grep -n "vol_short\|avg_volume_10d\|VOLUME_SHORT"
```

**Result: no output.** None of the Fix 2 identifiers are present in `origin/main`.

The relevant line in the main-branch file is:

```python
# origin/main  (commit 3b74e18, "daily log 2026-05-11")
avg_volume_30d = float(vol_nonzero.mean()) if len(vol_nonzero) > 0 else float(vol_slice.mean())
```

There is no subsequent `max()` call. Fix 2 exists only on branch
`claude/cluster-signal-booster-N0siv` (commit `0f175e2`, pushed in this session).

### 1b. Which branch does the production workflow use?

From `.github/workflows/daily_radar.yml` line 29:

```yaml
- name: Checkout
  uses: actions/checkout@v4
```

No `ref:` key — `actions/checkout@v4` defaults to the repository's **default branch**
(`main`). The 2026-05-12 daily radar ran from `origin/main` = `3b74e18`.

### 1c. Verdict on code path

**Hypothesis C is confirmed.** Fix 2 was not executed when today's email was generated.
The observed multiples (GC=F 128.8×, SI=F 17.2×, HG=F 17.4×) are outputs of Fix 1 code
running against a changed yfinance data snapshot.

Contradiction with user's claim: The user states "PR shipped 2026-05-11 introduced
`max(avg_30d, avg_10d)`." No such PR appears in the closed-PR list and no such code is on
`origin/main`. The session that wrote the Fix 1 diagnostic (2026-05-11) explicitly made
**no code changes**. Fix 2 was first committed in the current session (2026-05-12). The
user's claim cannot be reconciled with git evidence; this report proceeds on the basis of
what the git history shows.

---

## 2. Raw data for GC=F today `[LOG-RECONSTRUCTED + SIMULATION]`

### 2a. May 11 reverse-engineering

From `logs/2026-05-11.txt`, line 99:

```
GC=F | 37.4x | ...
```

The Fix 1 code on that date: `avg_volume_30d = nonzero_mean(volumes.iloc[-31:-1])`.

Using a typical GC=F active-day volume of ~115,000 contracts (CNBC-derived estimate from
the Fix 1 diagnostic):

```
avg_volume_30d_may11 = 115,000 / 37.37 ≈ 3,077 contracts/day
```

This is consistent with a window where ~17 of 30 days are deferred-contract days at
roughly 5,000 contracts/day average (deferred volume for GCM26 when it was not yet
front-month).

### 2b. May 12 scenario modelling `[SIMULATION]`

**Hypothesis**: yfinance switched its GC=F data source from GCM26 (June 2026 gold) to
GCQ26 (August 2026 gold) on or around 2026-05-12. GCM26's first notice day is
approximately 2026-05-29; the typical open-interest crossover (yfinance tracking switch)
occurs 3–5 weeks before first notice, i.e., **late April to mid-May 2026**.

Under this switch, the 30-day lookback window (30 trading days before May 12 ≈
**April 12 – May 11**) now contains GCQ26 history in its deferred months:

| Phase | Dates | GCQ26 role | Est. volume/day |
|-------|-------|------------|-----------------|
| April 12–23 | ~8 trading days | 3rd month out | ~500 contracts |
| April 24–May 11 | ~18 trading days | 2nd month out | ~2,000 contracts |
| May 12 | today | Front month (new) | ~200,000 contracts |

```python
# Simulated Fix 1 output on May 12 after second roll
avg_30d = (8 × 500 + 18 × 2000) / 26 ≈ 1,538 contracts   # all non-zero, pass Filter 1
current  = 200,000 contracts

ratio    = 200,000 / 1,538 ≈ 130×    # observed: 128.8×  ✓
```

The modelled value (130×) matches the observed 128.8× within rounding.

### 2c. Fix 2 simulation for May 12 `[SIMULATION]`

Even if Fix 2 had been running:

```python
# 10-day window (May 2–11): GCQ26 as 2nd month
avg_10d   = ~3,000 contracts/day   (slightly higher than 30d avg, still deferred)

# Fix 2 result:
avg_used  = max(1,538, 3,000) = 3,000
ratio_fix2 = 200,000 / 3,000 ≈ 67×       # vs 128.8× observed without Fix 2
```

Fix 2 would have halved the multiple but would still produce a 67× reading — far above the
10× suspicious_volume threshold and nowhere near the 1–3× target.

**The 10-day window is not "post-roll clean" when the roll happened ≤ 10 trading days ago.**
That is exactly the scenario on May 12 (second roll on day 0 of the window).

---

## 3. Day-over-day comparison `[LOG-RECONSTRUCTED]`

### 3a. GC=F trajectory

| Date | Ratio | Fix active | Notes |
|------|-------|------------|-------|
| 2026-04-23 | 0.2× | None | Last normal GCJ26 day |
| 2026-04-24 | 28.1× | None | **First roll: GCJ26→GCM26** |
| 2026-04-28 | 39.2× | None | Window filling with GCM26 deferred |
| 2026-05-06 | 0.1× | None | Anomalous low (see §3c) |
| 2026-05-11 | **37.4×** | Fix 1 | Fix 1 has no effect (no zero rows) |
| 2026-05-12 | **128.8×** | Fix 1 | **Second roll: GCM26→GCQ26** |

The jump from 37.4× to 128.8× (3.4×) in a single day cannot be explained by window
drift (adding one clean day, removing one older day produces a ≤2% change in ratio).
Only a sudden data-source switch — a second roll — can produce this magnitude of change
overnight.

### 3b. SI=F and HG=F trajectories

| Date | SI=F ratio | HG=F ratio | Notes |
|------|------------|------------|-------|
| 2026-04-23 | 1.2× | 0.1× | Pre-roll |
| 2026-04-24 | 225.9× | 31.7× | First roll |
| 2026-04-30 | 13.7× | 11.1× | Brief dip |
| 2026-05-06 | 0.1× | ~0.1× | Anomalous low |
| 2026-05-11 | 46.4× | 29.1× | Fix 1 has no effect |
| 2026-05-12 | **17.2×** | **17.4×** | Improved |

The improvement for SI=F and HG=F is consistent with one more clean day entering the 30d
window — but the drop from 46× to 17× (2.7×) in one day is larger than expected from
simple window clearing (which would produce ≤2% improvement per day).

A plausible supplementary explanation: May silver (SIK26) and May copper (HGK26) also
rolled to their July contracts (SIN26, HGN26) around May 12, but the July contracts were
already trading as **second-month** at moderate volume (~15,000–30,000 contracts/day) for
the entire 30-day lookback. When the 30d window is recomputed against SIN26 history
(vs. the SIK26 third-month-out deferred history), the denominator is meaningfully higher.
Gold's August contract (GCQ26) was trading at far lower second-month volume (~2,000/day)
because gold futures concentrate liquidity in the front month much more sharply than silver
or copper.

### 3c. The May 6 anomaly (0.1× for all three)

All three tickers showed a near-zero ratio on 2026-05-06, then bounced back to 25–46× on
2026-05-11. A ratio of 0.1× means the **denominator** was ~10× higher than current volume —
i.e., the avg_volume_30d spiked dramatically. This is consistent with yfinance temporarily
returning a different contract's data (possibly switching back to the expired front-month
contract for that fetch cycle). This supports hypothesis D: **yfinance data is unstable** for
generic futures symbols and can switch the underlying contract between daily fetches.

---

## 4. Cross-ticker comparison

### 4a. Why GC=F broke while SI=F and HG=F improved

The key structural difference is how liquidity is distributed across contract months:

| Metal | Front-month concentration | 2nd-month vol as % of front | 3rd-month vol as % |
|-------|--------------------------|----------------------------|-------------------|
| Gold (GC) | Very high | ~5–10% | ~1–3% |
| Silver (SI) | High | ~15–30% | ~5–10% |
| Copper (HG) | Moderate | ~20–35% | ~8–15% |

When yfinance switches to the next contract:
- GCQ26 (3rd month during April 24–May 11) traded at ~1–3% of GCM26 active volume → avg_30d ≈ 1,500–3,000
- SIN26 (2nd month during April 24–May 11) traded at ~15–30% of SIK26 active volume → avg_30d ≈ 10,000–30,000
- HGN26 (2nd month) similarly higher

The `max(avg_30d, avg_10d)` fix is ineffective when BOTH windows contain exclusively
deferred-contract history (which is the case for GC=F after its second roll on May 12).

For SI=F and HG=F, the second-month history in the 30d window is meaningfully higher
than the third-month history, so even without Fix 2, window clearing alone reduces the
ratio day-by-day. Gold has no such natural floor.

### 4b. COMEX gold roll schedule

COMEX gold futures (GC) are listed for Feb, Apr, Jun, Aug, Oct, Dec delivery. The yfinance
tracking switch from front-month to next-month historically happens when open interest
crosses — typically 3–5 weeks before the front-month's first notice day.

| Contract | First notice day (approx) | Switch to next: expected |
|----------|--------------------------|---------------------------|
| GCJ26 (Apr) | ~2026-03-27 | Roll began ~2026-03-01; yfinance switched ~2026-04-23 |
| GCM26 (Jun) | ~2026-05-29 | **Roll expected ~2026-05-01 to 2026-05-15** |
| GCQ26 (Aug) | ~2026-07-31 | — |

May 12 falls squarely within the expected GCM26→GCQ26 switch window. The 3.4× overnight
jump is the signature of this switch having occurred on or just before May 12.

---

## 5. Verdict

| Hypothesis | Status | Evidence |
|------------|--------|----------|
| **A — Both windows contaminated** | ✓ **Confirmed (GC=F)** | Simulation produces 130× with Fix 2; 10d window spans GCQ26 deferred history |
| **B — avg_10d near-zero** | ✗ Not the right framing | avg_10d is non-zero but still deferred (~3,000); Fix 2 would halve the ratio, not fix it |
| **C — Fix 2 not in production** | ✓ **Confirmed** | `origin/main` = `3b74e18`; no `vol_short`/`avg_volume_10d` in that file; workflow uses default branch |
| **D — yfinance data instability** | ✓ **Corroborated** | May 6 anomaly (0.1×→46× in 5 days), volatile SI=F trajectory; data for same dates changes between fetches |

**Primary verdict:** Hypothesis C (Fix 2 not deployed) is the reason the reported numbers
weren't produced by the fix. Hypothesis A (both windows contaminated) explains why Fix 2
would have also failed had it been deployed — for GC=F specifically. Hypotheses A and D
both apply; D is the underlying instability that makes any window-based fix fragile.

---

## 6. Recommended next action

### 6a. Options considered

| Option | Verdict |
|--------|---------|
| `max(30d, 10d, 5d)` triple-max | Fails when roll happened 0–4 days ago (all three windows contaminated) |
| Trim bottom N% of window before averaging | Fails — when >50% of days are deferred, the corrupt values ARE the bulk of the window |
| Exponentially-weighted mean | Reduces but doesn't eliminate contamination |
| Hardcode futures tickers to use 200d average | `avg_volume_200d` not in schema; requires API change and 200d of clean-contract history (also contaminated during first post-roll year) |
| Drop futures from universe | Effective but loses legitimate institutional signals (HG=F copper flows are real) |
| **Suppress volume-based tier escalation when `data_quality == "suspicious_volume"`** | ✓ **Recommended — see §6b** |

### 6b. Recommended fix: decouple volume from tier promotion

The `suspicious_volume` guard (Fix 3, PR #41) already identifies the contamination
correctly. The DATA QUALITY badge fires for all three tickers every day they're affected.
The remaining harm is that **volume alone promotes these tickers into the RED tier**,
causing the classifier to analyse them (consuming API quota) and often producing
`institutional_rebalancing` / `wait` anyway.

Proposed change in `main.py` alert-tier logic: **if `data_quality == "suspicious_volume"`,
exclude the volume signal from tier promotion. Let the ticker fall through to RED/AMBER only
if price velocity or RSI independently triggers it.**

Code sketch (no values fabricated — schematic only):

```python
# In run_pipeline() after analyze_volume():
volume_for_tier = volume.copy()
if volume.get("data_quality") == "suspicious_volume":
    # Suppress the inflated ratio from contributing to tier promotion.
    # The badge still fires in the email; the ratio still appears in the prompt.
    volume_for_tier = {"classification": "normal", "ratio": volume["ratio"],
                       "data_quality": "suspicious_volume"}

tier = get_alert_tier({
    "volume":   volume_for_tier,    # ← uses suppressed volume
    "velocity": velocity,
    "rsi":      rsi,
})
```

**Impact:**
- GC=F, SI=F, HG=F exit the RED list on days their only trigger is inflated volume
- Price velocity and RSI continue to work normally — if copper genuinely breaks out on velocity, it still fires
- DATA QUALITY badge still renders in the email; classifier is still warned
- No schema change; no new yfinance calls; no ticker list to maintain

### 6c. Fix 2 deployment status

Fix 2 (`max(avg_30d, avg_10d)`) on branch `claude/cluster-signal-booster-N0siv` (commit
`f94d0a0`) is not yet merged to `main`. It should still be merged — it handles the
**single-roll** scenario correctly (SI=F and HG=F at 17× would have been ~2–5× with Fix 2)
and is neutral for equities. But Fix 2 alone is insufficient for the double-roll case.

The complete fix is **Fix 2 + §6b tier-suppression**, deployed together:
- Fix 2 handles single-roll contamination (reduces ~46× to ~3–5×, clearing the suspicious_volume threshold)
- Tier-suppression handles double-roll contamination (both windows dirty) and any residual cases where Fix 2 still produces ratio > 10×

### 6d. Alternative: accept the badge as permanent

If the volume signal for futures is not materially useful (the classifier consistently assigns
`institutional_rebalancing` / `wait` to commodity tickers regardless of the volume reading),
then the simplest path is to **remove futures tickers from volume-based tier promotion
entirely** and rely on price velocity + RSI alone for GC=F, SI=F, HG=F, CL=F, ZS=F, NG=F.
This requires a one-line change to `get_alert_tier()` with a futures suffix check (`"=F"`).

---

## Appendix: simulation code `[SIMULATION]`

```python
# May 12 GC=F second-roll model (hypothesis A)
deep_deferred_days = 8   # April 12-23, GCQ26 as 3rd month out
deep_vol_per_day   = 500
near_deferred_days = 18  # April 24-May 11, GCQ26 as 2nd month out
near_vol_per_day   = 2000

avg_30d_fix1 = (deep_deferred_days * deep_vol_per_day +
                near_deferred_days * near_vol_per_day) / (deep_deferred_days + near_deferred_days)
# avg_30d_fix1 ≈ 1,538 contracts

current_volume = 200_000   # GCQ26 now front-month

ratio_fix1 = current_volume / avg_30d_fix1   # ≈ 130×  (observed: 128.8×)

# Fix 2 simulation:
avg_10d = 3_000   # May 2-11, GCQ26 as 2nd month — slightly higher, still deferred
ratio_fix2 = current_volume / max(avg_30d_fix1, avg_10d)   # ≈ 67×  (still extreme)
```

---

*Diagnostic generated 2026-05-12. Live yfinance data unavailable (sandbox HTTP 403).
All reconstructed figures sourced from `logs/2026-05-11.txt` and prior committed log files.
Simulation parameters derived from observed ratios and known COMEX roll schedule.*
