# Cluster Validation Harness — Diagnostic Report

_Read-only inspection. No code was modified. Branch: `diagnostic/cluster-harness`._

---

## 1. Data Flow Trace

When `scripts/run_cluster_validation.py` executes **without** `--smoke-test`:

```
run_cluster_validation.py
  └─ for each period × {boost_off, boost_on}:
       └─ run_historical_backtest()  [backtesting/historical/runner.py]
            │
            ├─ PRICE DATA: yfinance.Ticker(ticker).history(...)
            │   Fetches real OHLCV from Yahoo Finance for each ticker.
            │   Also fetches ^VIX history for synthetic sentiment proxy.
            │   Lookback: 310 calendar days before start (for 200d signal windows).
            │   Outcome buffer: 60 calendar days after end (for d+30 prices).
            │   NO cached CSVs, NO hardcoded fixtures — live network download every run
            │   (unless results/{result_key}.json is already cached on disk).
            │
            ├─ SIGNAL CLASSIFICATION: claude-haiku-4-5-20251001 via real API
            │   Each (ticker, trading_day) pair that clears the RED/AMBER pre-filter
            │   gets one Claude API call. Up to 200 calls per run (hard cap).
            │   Signals are NOT pre-stored anywhere; they are generated fresh
            │   from the yfinance price data + VIX-derived synthetic sentiment.
            │
            ├─ CLUSTER DETECTION (cluster_boost=True only):
            │   After each trading day, writes per-day signal log to:
            │     backtesting/historical/results/_tmp_{result_key}/signals_YYYYMMDD.json
            │   Then calls detect_clusters(logs_dir=tmp_dir, reference_date=day).
            │   Production logs/ directory is never touched.
            │   Temp dir is deleted after the run completes.
            │
            └─ OUTPUT:
                 backtesting/historical/results/{result_key}.json
                 (result_key = e.g. "covid_2020_boost_off" / "covid_2020_boost_on")

run_cluster_validation.py
  └─ _extract_metrics() on each results dict
  └─ generate_report() → backtests/cluster_boost_validation_YYYYMMDD.md
```

**Summary**: price data = real yfinance; signal data = real Claude API calls generated
on the fly from price data; cluster detection input = per-day logs written to an
isolated temp directory during the run; no external signal database is needed.

---

## 2. Why "(smoke-test fixture — not real backtest data)"?

The watermark comes from `scripts/run_cluster_validation.py` at these exact lines:

```python
# line 363
watermark = " _(smoke-test fixture — not real backtest data)_" if smoke_test else ""

# line 366
lines.append(f"# Cluster Boost Validation Report — {today}{watermark}")
```

The `smoke_test` variable is set from:

```python
# line 563
smoke_test = args.smoke_test
...
# line 602
report_md = generate_report(all_metrics, smoke_test=smoke_test)
```

And `args.smoke_test` is `True` only when the CLI is invoked with `--smoke-test`:

```python
# lines 540–547
parser.add_argument(
    "--smoke-test",
    action="store_true",
    help=(
        "Use a synthetic fixture instead of running real backtests. "
        "No API calls made. Confirms the harness wires up end-to-end."
    ),
)
```

**Concrete chain of events that produced the committed report:**

During the development session, the harness wiring was verified locally by running:

```
python scripts/run_cluster_validation.py --smoke-test
```

That wrote `backtests/cluster_boost_validation_20260507.md` to disk. The file was
then staged and committed as part of the same commit that introduced the harness
(`feat: cluster boost validation harness + GitHub Actions workflow`, commit `a752d9a`),
so the smoke-test output file was included in PR #31 as a demonstration artifact.

The GitHub Actions workflow (`cluster_validation.yml`) was **never triggered** — the
committed report is a local smoke-test run, not a workflow output.

---

## 3. Scenario Verdict

**Scenario C is true** — definitively.

> "The harness has a flag that defaults to fixture mode and was not flipped to real
> mode for this run."

More precisely: the flag (`--smoke-test`) **does not** default to fixture mode
(its `default` is `False`). It was **explicitly passed** when the committed report
was generated. Without that flag the harness calls the real backtester.

Scenarios A, B, and D are ruled out:

| Scenario | Verdict | Reason |
|----------|---------|--------|
| A — backtester always uses synthetic data | **False** | `runner.py` fetches from `yf.Ticker.history()` and makes live Claude API calls. No fixture path exists in the real code. |
| B — backtester is real but cluster detector input format doesn't exist | **False** | `runner.py` writes `signals_YYYYMMDD.json` to a temp dir itself when `cluster_boost=True`; `detect_clusters()` then reads from that temp dir. No pre-existing signal logs are required. |
| C — explicit flag, not a default | **True** | `--smoke-test` was passed at the CLI. Default is `False` (real-data mode). |
| D — something else | **False** | No other code path produces the watermark. |

### Why the sector attribution shows 100% hit rate for `semis` in all periods

This is a fixture artifact, not a signal of a data problem. In `_build_smoke_fixture()`,
signals are built so the first `hit_count` entries are all hits:

```python
# lines 268–276
hit_count = round(n * (on_pct if boost_on else off_pct) / 100)
for i in range(n):
    hit = i < hit_count           # first hit_count signals are all hits
    ...
    boosted = boost_on and i < n_boost  # first n_boost signals are all boosted
    signals.append(_make_signal(..., hit_d10=hit, hit_d30=hit, boosted=boosted))
```

Because `n_boost < hit_count` for every period in the fixture, **all boosted signals
are hits** by construction. This produces the implausible 100% sector hit rate and
is meaningless outside the smoke-test wiring check.

---

## 4. What It Would Take to Run Real Validation

In order of effort:

1. **Set `ANTHROPIC_API_KEY` as a GitHub Actions secret** (if not already set).
   The workflow already references `${{ secrets.ANTHROPIC_API_KEY }}`. Without it
   the real backtester will fail at the first Claude API call.

2. **Trigger the workflow without `--smoke-test`**. Go to:
   > Actions → Cluster Boost Validation → Run workflow

   Leave "Smoke test" **unchecked**. Leave "Single period" blank to run all 4.
   The workflow will run `scripts/run_cluster_validation.py` with no `--smoke-test`
   flag, which invokes `run_historical_backtest()` for all 8 combinations.

3. **Wait for yfinance downloads and Claude API calls** (see §5 for timing).
   Results are cached to `backtesting/historical/results/{result_key}.json` after
   the first run, so subsequent re-runs with `--force` omitted will skip API calls.

4. **No code changes are required.** The pipeline from price data → Claude classification
   → cluster detection → hit-rate evaluation → markdown report is fully wired and
   correct. The only missing ingredient is the API key and a real trigger.

**What does NOT need to be done** (common misconceptions):

- You do NOT need to backfill historical signal logs into `logs/`. The runner
  creates its own signal logs in an isolated temp directory during execution.
- You do NOT need to change any environment variables except `ANTHROPIC_API_KEY`.
- You do NOT need to add a `--real-data` flag — the real-data path is the default.

---

## 5. Estimated Effort

| Task | Effort | Blocker? |
|------|--------|----------|
| Confirm `ANTHROPIC_API_KEY` secret is set in the repo | 2 min | Yes — run fails without it |
| Trigger workflow from Actions tab | 2 min | No |
| Wait for all 8 backtest runs to complete | 2–4 h | External — Claude API rate limits + yfinance |
| Review the real report | 15 min | No |

**Total developer effort: ~20 minutes.** The rest is wall-clock wait time.

### Caveats

- **Hard call cap**: each of the 8 runs is individually capped at 200 Claude API
  calls (`MAX_CLAUDE_CALLS = 200` in `runner.py`). For the longer periods (2022 Tech
  Bear = 14 months, COVID = 4 months) this cap may be reached before all trading
  days × tickers are evaluated, producing a `cap_reached: true` flag in the results
  and a shorter-than-full sample. The cap can be raised in `runner.py` if needed.

- **yfinance reliability**: yfinance occasionally returns empty data for certain
  tickers or date ranges, especially for commodity futures (`GC=F`, `SI=F`, `CL=F`).
  The runner silently skips tickers with no data. Real results may have fewer
  signals than the fixture.

- **2008 period + 310-day lookback**: the start date is 2008-09-01, so the lookback
  buffer requests data from late 2007. Yahoo Finance coverage for that era is complete
  for major equities but may be sparse for some futures contracts.

- **Cost**: 200 Claude Haiku calls × 8 runs = up to 1,600 API calls. At Haiku pricing
  (≈$0.25/M input tokens, ≈$1.25/M output tokens) and roughly 1,200 input + 80 output
  tokens per call, total API cost is approximately **$0.60–$1.00** for the full suite.

---

_Generated by read-only code inspection on 2026-05-07. No files were modified._
