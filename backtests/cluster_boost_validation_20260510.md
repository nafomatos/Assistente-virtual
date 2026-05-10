# Cluster Boost Validation Report — 2026-05-10 _(smoke-test fixture — not real backtest data)_

**Verdict threshold:** ≥3 of 4 periods improved by ≥3pp at d+30 (combined contrarian_buy + reduce_exposure).

## 1. Summary Table — d+30 hit rate

| Period | Boost OFF | Boost ON | Delta | Result |
|--------|-----------|----------|-------|--------|
| COVID Crash & Recovery (Feb–Jun 2020) | 57.1% (28) | 60.7% (28) | +3.6pp ✓ | ⚠ INC |
| GameStop & Silver Squeeze (Jan–Feb 2021) | 62.5% (16) | 62.5% (16) | +0.0pp | ⚠ INC |
| 2022 Tech Bear Market (Nov 2021–Dec 2022) | 55.6% (27) | 59.3% (27) | +3.7pp ✓ | ⚠ INC |
| 2008 Global Financial Crisis (Sep 2008–Apr 2009) | 53.8% (26) | 57.7% (26) | +3.9pp ✓ | ⚠ INC |

## 2. Per-Period Detail

### COVID Crash & Recovery (Feb–Jun 2020)

**Boost OFF**
- Total signals: 28
- Boosted signals: 0
- Cap reached: False
- d+10 hit rate: 57.1% (28)
- d+30 hit rate: 57.1% (28)
- d+30 (conf ≥ 5): 57.1% (28)
- d+30 (conf ≥ 7): 57.1% (14)
> **Note:** historical-mode signals are subject to a −2 confidence penalty (VIX-based sentiment proxy). Conf ≥ 5 in historical mode is roughly equivalent to conf ≥ 7 in production.
- d+30 by recommendation:
  - `contrarian_buy`: 60.0% (10)
  - `reduce_exposure`: 55.6% (18)

**Boost ON**
- Total signals: 28
- Boosted signals: 6
- Cap reached: False
- d+10 hit rate: 60.7% (28)
- d+30 hit rate: 60.7% (28)
- d+30 (conf ≥ 5): 60.7% (28)
- d+30 (conf ≥ 7): 64.3% (14)
> **Note:** historical-mode signals are subject to a −2 confidence penalty (VIX-based sentiment proxy). Conf ≥ 5 in historical mode is roughly equivalent to conf ≥ 7 in production.
- d+30 by recommendation:
  - `contrarian_buy`: 60.0% (10)
  - `reduce_exposure`: 61.1% (18)

### GameStop & Silver Squeeze (Jan–Feb 2021)

**Boost OFF**
- Total signals: 16
- Boosted signals: 0
- Cap reached: False
- d+10 hit rate: 62.5% (16)
- d+30 hit rate: 62.5% (16)
- d+30 (conf ≥ 5): 62.5% (16)
- d+30 (conf ≥ 7): 62.5% (8)
> **Note:** historical-mode signals are subject to a −2 confidence penalty (VIX-based sentiment proxy). Conf ≥ 5 in historical mode is roughly equivalent to conf ≥ 7 in production.
- d+30 by recommendation:
  - `contrarian_buy`: 66.7% (6)
  - `reduce_exposure`: 60.0% (10)

**Boost ON**
- Total signals: 16
- Boosted signals: 4
- Cap reached: False
- d+10 hit rate: 62.5% (16)
- d+30 hit rate: 62.5% (16)
- d+30 (conf ≥ 5): 62.5% (16)
- d+30 (conf ≥ 7): 62.5% (8)
> **Note:** historical-mode signals are subject to a −2 confidence penalty (VIX-based sentiment proxy). Conf ≥ 5 in historical mode is roughly equivalent to conf ≥ 7 in production.
- d+30 by recommendation:
  - `contrarian_buy`: 66.7% (6)
  - `reduce_exposure`: 60.0% (10)

### 2022 Tech Bear Market (Nov 2021–Dec 2022)

**Boost OFF**
- Total signals: 27
- Boosted signals: 0
- Cap reached: False
- d+10 hit rate: 55.6% (27)
- d+30 hit rate: 55.6% (27)
- d+30 (conf ≥ 5): 55.6% (27)
- d+30 (conf ≥ 7): 57.1% (14)
> **Note:** historical-mode signals are subject to a −2 confidence penalty (VIX-based sentiment proxy). Conf ≥ 5 in historical mode is roughly equivalent to conf ≥ 7 in production.
- d+30 by recommendation:
  - `contrarian_buy`: 55.6% (9)
  - `reduce_exposure`: 55.6% (18)

**Boost ON**
- Total signals: 27
- Boosted signals: 5
- Cap reached: False
- d+10 hit rate: 59.3% (27)
- d+30 hit rate: 59.3% (27)
- d+30 (conf ≥ 5): 59.3% (27)
- d+30 (conf ≥ 7): 57.1% (14)
> **Note:** historical-mode signals are subject to a −2 confidence penalty (VIX-based sentiment proxy). Conf ≥ 5 in historical mode is roughly equivalent to conf ≥ 7 in production.
- d+30 by recommendation:
  - `contrarian_buy`: 66.7% (9)
  - `reduce_exposure`: 55.6% (18)

### 2008 Global Financial Crisis (Sep 2008–Apr 2009)

**Boost OFF**
- Total signals: 26
- Boosted signals: 0
- Cap reached: False
- d+10 hit rate: 53.8% (26)
- d+30 hit rate: 53.8% (26)
- d+30 (conf ≥ 5): 53.8% (26)
- d+30 (conf ≥ 7): 53.8% (13)
> **Note:** historical-mode signals are subject to a −2 confidence penalty (VIX-based sentiment proxy). Conf ≥ 5 in historical mode is roughly equivalent to conf ≥ 7 in production.
- d+30 by recommendation:
  - `contrarian_buy`: 55.6% (9)
  - `reduce_exposure`: 52.9% (17)

**Boost ON**
- Total signals: 26
- Boosted signals: 5
- Cap reached: False
- d+10 hit rate: 57.7% (26)
- d+30 hit rate: 57.7% (26)
- d+30 (conf ≥ 5): 57.7% (26)
- d+30 (conf ≥ 7): 61.5% (13)
> **Note:** historical-mode signals are subject to a −2 confidence penalty (VIX-based sentiment proxy). Conf ≥ 5 in historical mode is roughly equivalent to conf ≥ 7 in production.
- d+30 by recommendation:
  - `contrarian_buy`: 55.6% (9)
  - `reduce_exposure`: 58.8% (17)

## 3. Sector Attribution (Boost ON runs only)

Sector attribution tracks which sectors triggered the most boosts
and whether boosted signals in those sectors were directionally correct at d+30.

| Period | Sector | Boosted signals | d+30 hit rate (directional) |
|--------|--------|-----------------|------------------------------|
| COVID Crash & Recovery (Feb–Jun 2020) | `semis` | 6 | 100.0% (6) |
| GameStop & Silver Squeeze (Jan–Feb 2021) | `semis` | 4 | 100.0% (4) |
| 2022 Tech Bear Market (Nov 2021–Dec 2022) | `semis` | 5 | 100.0% (5) |
| 2008 Global Financial Crisis (Sep 2008–Apr 2009) | `semis` | 5 | 100.0% (5) |

## 4. Verdict

**FAIL ✗** — 0/4 periods passed, 0 failed, 4 inconclusive (< 10 boosted signals).

| Period | Result |
|--------|--------|
| COVID Crash & Recovery (Feb–Jun 2020) | ⚠ INCONCLUSIVE |
| GameStop & Silver Squeeze (Jan–Feb 2021) | ⚠ INCONCLUSIVE |
| 2022 Tech Bear Market (Nov 2021–Dec 2022) | ⚠ INCONCLUSIVE |
| 2008 Global Financial Crisis (Sep 2008–Apr 2009) | ⚠ INCONCLUSIVE |

## 5. Recommended Action

**DO NOT FLIP** — investigate hypothesis: _all non-passing periods were INCONCLUSIVE (insufficient boosted-signal sample, < 10): COVID Crash & Recovery (Feb–Jun 2020); GameStop & Silver Squeeze (Jan–Feb 2021); 2022 Tech Bear Market (Nov 2021–Dec 2022); 2008 Global Financial Crisis (Sep 2008–Apr 2009). Accumulate more data before drawing conclusions._. Consider narrowing the cluster threshold, adjusting the window, or reviewing sector mapping before re-running validation.

⚠ **Needs more data:** COVID Crash & Recovery (Feb–Jun 2020); GameStop & Silver Squeeze (Jan–Feb 2021); 2022 Tech Bear Market (Nov 2021–Dec 2022); 2008 Global Financial Crisis (Sep 2008–Apr 2009) — fewer than 10 boosted signals; verdict is INCONCLUSIVE.

---
_Generated by `scripts/run_cluster_validation.py` on 2026-05-10_
