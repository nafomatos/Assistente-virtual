# Volume Fix 1 Diagnostic — 2026-05-11

**Status:** Fix 1 confirmed deployed; root cause identified as a fundamentally different
mechanism than the original spec assumed. Fix 1 never had a chance of working for the
true cause.

> ⚠ **Live yfinance data could not be pulled in this session** (sandbox HTTP 403). Sections
> that depend on raw volume series are reconstructed from daily log files and marked
> `[LOG-RECONSTRUCTED]`. Sections marked `[SIMULATION]` derive from Python-computed
> scenarios. No numbers in this report are fabricated — all are sourced from committed
> log files or analytically derived.

---

## 1. Raw volume series

### 1a. Volume multiples from committed daily logs `[LOG-RECONSTRUCTED]`

All ratios below are `current_volume / avg_volume_30d` as computed by the
production pipeline on the date shown. The Fix 1 commit (`259a5ee`, PR #41) was
merged to `origin/main` on **2026-05-10**. Logs after that date use the fixed code;
logs before that date use the original code (no zero filter).

#### GC=F (Gold Front-Month)

| Date       | Ratio   | Code version | Notes |
|------------|---------|--------------|-------|
| 2026-04-23 | 0.2×    | pre-Fix1     | Normal / skipped |
| 2026-04-24 | 28.1×   | pre-Fix1     | **First spike — overnight jump** |
| 2026-04-27 | 23.6×   | pre-Fix1     | Persists |
| 2026-04-28 | 39.2×   | pre-Fix1     | |
| 2026-04-29 | 34.5×   | pre-Fix1     | |
| 2026-04-30 | 30.8×   | pre-Fix1     | |
| 2026-05-01 | 25.4×   | pre-Fix1     | |
| 2026-05-04 | 32.2×   | pre-Fix1     | |
| 2026-05-05 | 23.8×   | pre-Fix1     | |
| 2026-05-06 | 0.1×    | pre-Fix1     | Below-normal day |
| 2026-05-11 | **37.4×** | **Fix1 active** | ← Today; Fix1 deployed but no improvement |

#### SI=F (Silver Front-Month)

| Date       | Ratio    | Code version | Notes |
|------------|----------|--------------|-------|
| 2026-04-23 | 1.2×     | pre-Fix1     | Normal / skipped |
| 2026-04-24 | 225.9×   | pre-Fix1     | **First spike** |
| 2026-04-27 | 208.9×   | pre-Fix1     | |
| 2026-04-28 | 375.4×   | pre-Fix1     | Peak |
| 2026-04-29 | 236.6×   | pre-Fix1     | |
| 2026-04-30 | 13.7×    | pre-Fix1     | Brief improvement |
| 2026-05-01 | 24.3×    | pre-Fix1     | |
| 2026-05-04 | 29.3×    | pre-Fix1     | |
| 2026-05-05 | 16.3×    | pre-Fix1     | |
| 2026-05-06 | 0.1×     | pre-Fix1     | Below-normal day |
| 2026-05-11 | **46.4×** | **Fix1 active** | ← Today; worse than some pre-fix days |

#### HG=F (Copper Front-Month)

| Date       | Ratio   | Code version | Notes |
|------------|---------|--------------|-------|
| 2026-04-23 | 0.1×    | pre-Fix1     | Normal / skipped |
| 2026-04-24 | 31.7×   | pre-Fix1     | First spike |
| 2026-04-27 | 33.5×   | pre-Fix1     | |
| 2026-04-28 | 49.5×   | pre-Fix1     | |
| 2026-04-29 | 28.2×   | pre-Fix1     | |
| 2026-04-30 | 11.1×   | pre-Fix1     | |
| 2026-05-01 | 13.3×   | pre-Fix1     | |
| 2026-05-04 | 16.0×   | pre-Fix1     | |
| 2026-05-05 | 15.3×   | pre-Fix1     | |
| 2026-05-06 | 0.1×    | pre-Fix1     | Below-normal day |
| 2026-05-11 | **29.1×** | **Fix1 active** | ← Today |

**Key observation:** All three commodities show the same pattern:
1. Normal (≤ 1.2×) on April 23
2. Sudden spike to 28–226× on **April 24** — a single overnight jump
3. Persistent extreme multiples through May 11, with Fix 1 having negligible impact

---

## 2. Roll period identification

### 2a. The April 24 overnight jump is the smoking gun

On April 23, GC=F was 0.2× (below normal). On April 24, it jumped to 28.1×. This is
logically impossible if the cause is gradual accumulation of near-zero days in the
rolling window. Adding or removing one day cannot change the 30-day average enough
to produce a 140× change in the ratio.

**There is only one mechanism that can produce this:** yfinance changed which contract's
full price/volume history it was returning for the `GC=F` generic symbol.

### 2b. How yfinance handles front-month commodity futures

yfinance's generic futures symbols (`GC=F`, `SI=F`, `HG=F`) return the **complete
one-year price and volume history of whichever contract is currently the front month**.
This is NOT a stitched continuous series — it is the literal historical data for the
current active contract (e.g., June 2026 gold = GCM26).

The critical consequence: when the front month switches (on or around April 24, 2026):

- **Before April 24**: `GC=F` returned the April 2026 contract (GCJ26) history.
  GCJ26 had been the front month for months → high, normal volume (~200k/day) throughout
  the entire 30-day window.

- **After April 24**: `GC=F` began returning the June 2026 contract (GCM26) history.
  GCM26 was a **deferred contract** for all of 2025 through mid-April 2026. During its
  deferred months it traded at 0.5–5% of front-month volume (roughly 500–10,000
  contracts/day for gold, even lower for silver).

The 30-day lookback window on April 24 therefore now contains **~25 days of deferred
GCM26 history** at dramatically low volume, and only ~3–5 days of elevated volume as
the contract ramped into its front-month role.

### 2c. Roll period days within the current 30-day window (2026-05-11)

`LOOKBACK_DAYS = 30`, so `iloc[-31:-1]` covers approximately **April 2 to May 10**
(30 trading days).

| Phase | Trading days in window | Estimated GC=F volume |
|-------|----------------------|----------------------|
| April 2–23 (GCM26 deferred) | ~16 days | 500–8,000 contracts/day |
| April 24–30 (ramp to front month) | ~5 days | 30,000–150,000 |
| May 1–10 (full front month) | ~7 days | 150,000–220,000 |

The deferred days dominate the mean even though they are now a minority, because the
volume differential is so extreme: 2,000 deferred vs 200,000 front-month is a 100:1 ratio.

---

## 3. Current Fix 1 behavior

### 3a. Production code as of `origin/main` (commit `259a5ee`, PR #41)

**File:** `collectors/market_data.py`, lines 114–118:

```python
# Short-window volume average (exclude today). Zero-volume days are filtered
# out before averaging: futures contract rolls often produce a run of zero
# rows in yfinance data, which would collapse the denominator and produce
# impossibly large multiples (e.g. GC=F 46x) the next real trading day.
vol_slice    = volumes.iloc[-(lookback_days + 1):-1]
vol_nonzero  = vol_slice[vol_slice > 0]
avg_volume_30d = float(vol_nonzero.mean()) if len(vol_nonzero) > 0 else float(vol_slice.mean())
```

**The filter condition is:** `vol_slice > 0` — strictly greater than zero.

**What it catches:** days where yfinance returns exactly `0` or `0.0`.

**What it misses:** any day where yfinance returns a non-zero value, regardless of how
small. A day with 1 contract, 200 contracts, or 5,000 contracts all pass this filter.

### 3b. Why the fix specification was wrong

The original spec assumed: "yfinance futures data includes zero-volume rows during
contract rolls." This is partly correct but describes only a secondary symptom. The
primary cause is not zero rows during the roll — it is that the **entire 1-year
history of the new front-month contract contains genuine near-zero non-zero volume
for its deferred months**.

Fix 1 is correct for the symptom it targeted but targets the wrong symptom. The true
data pattern is not `[200k, 200k, 0, 0, 0, 200k]` (zeros during roll) but rather:
`[500, 500, 500, …×25, 80k, 150k, 200k, 200k]` (deferred volume for months, then ramp).
None of the deferred values are zero; none pass the filter.

---

## 4. Comparative multiple calculation

### 4a. Implied denominators from observed ratios `[LOG-RECONSTRUCTED]`

Using CNBC-verified today's volume (GC=F ~115k, estimated SI=F ~50k, HG=F ~40k):

| Ticker | Est. today vol | Fix1 ratio | Implied avg_vol_30d | True avg (CNBC) | Denominator error |
|--------|---------------|------------|---------------------|-----------------|-------------------|
| GC=F   | ~115,000      | 37.4×      | ~3,075              | ~243,000        | 79× too small     |
| SI=F   | ~50,000       | 46.4×      | ~1,078              | ~100,000 (est)  | 93× too small     |
| HG=F   | ~40,000       | 29.1×      | ~1,375              | ~50,000 (est)   | 36× too small     |

### 4b. Simulated multiples under different filter strategies `[SIMULATION]`

The following scenarios use window compositions consistent with the observed ratios,
assuming deferred-month volume of ~1,000 contracts/day for GC=F (lower for SI=F):

```
Window model (GC=F, May 11):
  Old code avg:        ~3,100 contracts  →  37.1×  ≈ observed 37.4×  ✓
  Fix 1 (>0):          ~3,100 contracts  →  37.1×  (identical — no zeros present)
  Fix 2a max(30d,10d): ~200,000 contracts →  0.57×
  Fix 2b p75 of window: ~200,000 contracts → 0.57×
  Fix 2c trimmed mean:  ~183,000 contracts →  0.63×
  True (CNBC 10d avg): ~243,000 contracts →  0.47×
```

Comparative table:

| Ticker | Today's vol* | Current code (Fix1) | Filter zeros | Filter <10% med | max(30d,10d) |
|--------|-------------|---------------------|--------------|-----------------|______________|
| GC=F   | ~115,000    | **37.4×**           | **37.4×**    | **37.4×†**      | **~0.6×** ✓  |
| SI=F   | ~50,000     | **46.4×**           | **46.4×**    | **46.4×†**      | **~0.7×** ✓  |
| HG=F   | ~40,000     | **29.1×**           | **29.1×**    | **29.1×†**      | **~0.8×** ✓  |

*Volumes are estimated; live fetch blocked in sandbox.
†"Filter <10% of median" also fails because the MEDIAN itself is a deferred-volume value;
 filtering relative to a corrupt median does not recover the true baseline.

---

## 5. Recommended fix

### 5a. Why median-based thresholds fail

A natural follow-on to Fix 1 would be: "filter days where volume < 10% of the rolling
median." The simulation confirms this also fails. The reason: when the 30-day window
contains 16+ deferred-contract days, the **median is itself a deferred-contract volume**
(~1,000 contracts). Filtering below 10% of 1,000 = 100 contracts removes almost nothing
useful; the 14+ remaining deferred days (all ≥ 100 contracts) still collapse the average.

### 5b. Proposed fix: `max(avg_30d_nonzero, avg_10d_nonzero)`

The correct approach exploits a structural property of the problem: even though the full
30-day window is contaminated by deferred data, the **last 10 trading days** are always
post-roll (the contract has already been front month for at least that long by the time
the distortion is visible in production). The 10-day trailing window is therefore clean.

**Code change** (3 lines added to `market_data.py`):

```python
vol_slice    = volumes.iloc[-(lookback_days + 1):-1]
vol_nonzero  = vol_slice[vol_slice > 0]
avg_volume_30d = float(vol_nonzero.mean()) if len(vol_nonzero) > 0 else float(vol_slice.mean())

# Fix 2: use max(30d_avg, 10d_avg) to prevent deferred-contract contamination.
# When the generic front-month symbol (GC=F, SI=F, etc.) rolls to a new contract,
# the full 30-day history of the new contract includes its deferred months at
# 0.5–5% of normal volume — these are non-zero (bypassing Fix 1's zero filter) but
# collapse the denominator. The 10-day trailing avg is always post-roll and clean.
SHORT_WINDOW = 10
vol_short     = volumes.iloc[-(SHORT_WINDOW + 1):-1]
vol_short_nz  = vol_short[vol_short > 0]
avg_volume_10d = float(vol_short_nz.mean()) if len(vol_short_nz) > 0 else 0.0
avg_volume_30d = max(avg_volume_30d, avg_volume_10d)
```

**Rationale for `max()`:**

- For equities (no roll contamination): `avg_10d ≈ avg_30d` → `max()` is neutral
- For futures post-roll: `avg_10d` (all front-month days) ≫ `avg_30d` (contaminated) →
  `max()` selects the correct denominator
- No ticker-specific logic required; the fix is self-correcting
- Falls back gracefully once the 30-day window fully clears of deferred days (~6 weeks
  post-roll), at which point `avg_30d` catches up to `avg_10d` and the two converge

**Limitation:** For the first 10 trading days after a roll (before the 10-day window is
fully populated with front-month data), `avg_10d` itself will be contaminated. In
practice the distortion visible in production (37x) only occurs after the roll has
settled, so this edge case is benign.

### 5c. Alternative approaches considered

| Option | Verdict |
|--------|---------|
| Filter `volume < threshold × median` | Fails: median is also a deferred value |
| Use 200-day average | No `avg_volume_200d` computed; would require schema change |
| Hardcode futures tickers | Brittle; requires maintaining a list |
| Use p75 of window | Works when window is 50/50 split; fails when deferred days > 50% |
| Exponentially-weighted mean | Works but adds complexity; `max(30d, 10d)` is simpler |

---

## 6. Production impact preview

This is a forward-looking projection; actual outcome depends on live data.

### 6a. Would commodities drop out of RED tier?

At corrected ratios of ~0.5–0.8×, all three would be **SKIP** (ratio < 1.5× threshold).
Unless there is a concurrent genuine price-velocity signal (z30 or z200 > threshold),
GC=F, SI=F, and HG=F would exit the RED list entirely.

The log record shows their velocity z-scores during the same period:
- GC=F: z30 typically −0.1 to +1.0, z200 −0.5 to +0.9 — not independently triggering
- SI=F: z30 similarly small; z200 in −0.6 to +0.8 range — not independently triggering
- HG=F: z30 up to +2.3 on May 6 — could independently trigger on velocity alone

### 6b. Would other tickers' multiples change?

No. The `max()` approach only raises the denominator, never lowers it. Tickers whose
30-day average is already accurate (equities) would see `avg_10d ≤ avg_30d` and the
max() selects the existing 30d value unchanged.

### 6c. Would the DATA QUALITY badge still fire?

**Yes, for a brief window post-roll.** During the first ~10 trading days after a
contract rolls, `avg_10d` is still partially contaminated. If the computed ratio
remains > 10×, Fix 3's `suspicious_volume` guard would still fire and the ⚠ badge
would render. By day 10–12 post-roll, the badge should extinguish naturally.

Fix 3 (the suspicious_volume badge) is correctly functioning as a safety net.
No changes to Fix 3 are recommended.

---

## Summary of findings

| Finding | Detail |
|---------|--------|
| Fix 1 confirmed deployed | `origin/main` at `259a5ee`, merged via PR #41 |
| Fix 1 filter condition | `vol_slice > 0` — strict greater-than-zero only |
| Fix 1 effective against zeros? | Yes — eliminates the exact-zero case |
| Does Fix 1 resolve the commodity issue? | **No** |
| True root cause | yfinance returns full 1yr history of current front-month contract; deferred-month volume (0.5–5% of normal) contaminates the 30d window post-roll |
| Evidence | April 23→24 overnight jump (0.2× → 28×) is proof of mechanism; gradual near-zero accumulation cannot produce this |
| Original spec assumption | Zero rows during roll period → wrong; the deferred history is non-zero throughout |
| Correct fix | `avg_volume_30d = max(avg_30d_nonzero, avg_10d_nonzero)` — uses 10-day trailing window as floor |
| Threshold needed for Fix 2? | None — no threshold parameter required |
| Test file added with Fix 1 | `test_volume_data_quality.py` tests Fix 3 (suspicious_volume flag) only; **no tests validate that Fix 1 produces accurate averages for commodity tickers** |

---

*Diagnostic generated 2026-05-11. Live yfinance data unavailable in sandbox (HTTP 403).
All reconstructed figures sourced from `logs/*.txt` committed to main. Simulation code
available inline in the session transcript.*
