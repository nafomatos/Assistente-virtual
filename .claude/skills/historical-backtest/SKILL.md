# Historical Backtest Skill

## Purpose

Runs the Artificial Price Radar signal pipeline against a historical date range,
calls Claude Haiku for each flagged (ticker, day) pair, and produces a JSON results
file + HTML report with hit rates broken down by recommendation type.

Use when the user asks to backtest the radar against a historical period, validate
signal logic against a known market event, or add a new period for research.

---

## Architecture

| File | Role |
|------|------|
| `backtesting/historical/main.py` | CLI entry point; owns the `PERIODS` dict; handles caching, reporting, email |
| `backtesting/historical/runner.py` | Core engine: fetches data, loops over days, calls Claude, evaluates outcomes |
| `backtesting/historical/sentiment_proxy.py` | `get_synthetic_sentiment()` + `vix_to_fear_greed()` — replaces missing social data |
| `backtesting/historical/report_builder.py` | Generates the HTML report from a results dict |
| `output/document_builder.py` | `get_alert_tier()` — shared pre-filter (red/amber/None); same logic as daily pipeline |

Results land in `backtesting/historical/results/{period_name}.json` and
`{period_name}_report.html`.

---

## Adding a New Period

Edit `PERIODS` in `backtesting/historical/main.py`:

```python
"gfc_2008": {
    "start":       "2008-09-01",
    "end":         "2009-03-31",
    "tickers":     ["AAPL", "AMZN", "GOOGL", "GC=F", "CL=F", "HG=F"],
    "name":        "Global Financial Crisis",
    "vix_context": "VIX peaked at 89.53 on Oct 24, 2008",   # optional but useful
},
```

- `start` / `end`: ISO date strings. Runner fetches 310 days before `start` automatically (200d warmup).
- `tickers`: use only tickers that existed on `start`. See ticker availability below.
- `name`: human-readable label shown in CLI output and HTML report title.
- `vix_context`: optional free-text note; stored in the dict but not currently read by runner — it's for human reference.

If a ticker symbol is not in `config.TICKER_NAMES`, add it to `_EXTRA_NAMES` in
`runner.py` so the prompt shows a real name instead of the raw symbol:

```python
_EXTRA_NAMES: dict[str, str] = {
    "GME": "GameStop",
    "AMC": "AMC Entertainment",
    "BB":  "BlackBerry",
    # add new ones here
}
```

### Ticker availability by approximate first-trade date

| Ticker | First available |
|--------|----------------|
| RDDT   | 2024-03-21 (IPO) |
| RKLB   | 2021-09-02 (SPAC) |
| ASTS   | 2021-04-07 (SPAC) |
| SOFI   | 2021-06-01 (SPAC) |
| PLTR   | 2020-09-30 (direct listing) |
| MSTR   | 1998 (pre-dates all defined periods) |
| GME / AMC / BB | Pre-2021; safe for gamestop_2021 and earlier |
| NVDA, TSLA, AAPL, AMZN, GOOGL, GC=F, SI=F, CL=F, HG=F | Pre-2000; safe for any period |

---

## Common Gotchas

**yfinance column layout** — newer yfinance versions return a MultiIndex `(field, ticker)`
when downloading a single symbol via `yf.download()`. Runner handles both flat and
MultiIndex for `^VIX`. If you add a new bulk download elsewhere, check:
```python
if isinstance(df.columns, pd.MultiIndex):
    col = df[("Close", "^VIX")]
else:
    col = df["Close"]
```

**VIX date gaps** — VIX has no data on weekends/holidays. `vix_by_date.get(day, _VIX_DEFAULT)`
falls back to `20.0` (neutral). This is correct behaviour; no fix needed.

**Fear & Greed API** — `alternative.me/fng` only has reliable data from ~2018. For any
period before 2018, `vix_to_fear_greed(vix)` in `sentiment_proxy.py` is the only
available proxy. Do not attempt to call the real API for pre-2018 backtests.

**Buffett Indicator** — no historical API exists. Runner does not fetch it. Claude's
`HISTORICAL_MODE_ADDENDUM` in the system prompt tells Claude to ignore Buffett
Indicator adjustments and work from the VIX proxy alone.

**200d warmup truncates early signals** — the runner fetches `_LOOKBACK_BUFFER = 310`
calendar days before `start`. Signals in roughly the first 10–15 trading days of the
range may have low `z_score_200d` accuracy if the underlying ticker had low liquidity
or gapped data in that warmup window. Not a bug; just a known limitation.

**Sparse data for small-caps / SPACs** — tickers with <200 trading days of history
at `start` will still produce signals but `z_score_200d` will be based on whatever
history is available. Inspect `macro_extreme` flags for such tickers with skepticism.

**Confidence penalty is applied twice conceptually** — `HISTORICAL_MODE_ADDENDUM`
tells Claude to self-reduce confidence; runner also subtracts `confidence_penalty` (2)
from Claude's output before storing. `confidence_raw` preserves the pre-penalty value.
This is intentional: aggressive prevention of over-confident historical calls.

**Cached results** — on re-run, `main.py` loads the existing JSON and skips API calls.
Pass `--force` to re-run from scratch and overwrite.

**Ticker with no yfinance data** — `_fetch_ticker_history()` returns `None` and logs
a warning; the ticker is silently skipped. Check logs if a ticker produces zero signals.

---

## How to Run

```bash
# From repo root
python -m backtesting.historical.main --period covid_2020
python -m backtesting.historical.main --period gamestop_2021
python -m backtesting.historical.main --period {period_name} --force   # ignore cache
python -m backtesting.historical.main --period {period_name} --no-report  # skip HTML
python -m backtesting.historical.main --list   # show all defined periods
```

Requires `ANTHROPIC_API_KEY` in the environment (`.env` or shell export).

**GitHub Actions** — no dedicated backtest workflow exists yet. To trigger via UI,
add a `workflow_dispatch` workflow that runs the command above, or run locally and
commit the JSON results to `backtesting/historical/results/`.

---

## Cost Guardrails

- Model: `claude-haiku-4-5-20251001` only (set in `runner.py:MODEL`). Never upgrade
  to Sonnet/Opus without recalculating cost.
- Hard cap: `MAX_CLAUDE_CALLS = 200` in `runner.py`. Backtest stops and logs a warning
  when reached; `cap_reached: true` is stored in the results JSON.
- Estimate before running: `trading_days × tickers_passing_prefilter`. Typical pass
  rate is 10–30% of (days × tickers) during calm markets, higher during crash periods.
  A 4-month crash window with 9 tickers can easily hit 200 calls in the first few weeks.
- To stay under budget on a long/wide period: shorten the date range, reduce the
  ticker list, or raise the pre-filter thresholds in `document_builder.py`.
- Prompt caching is active: `SYSTEM_PROMPT` is marked `cache_control: ephemeral`.
  From call 2 onward, expect `cache_read_input_tokens` to dominate `input_tokens`.
  Effective per-call cost is ~2–3× cheaper than uncached after warmup.
