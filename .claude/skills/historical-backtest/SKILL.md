# Historical Backtest Skill

Run historical backtests of the Artificial Price Radar signal detection system against known market stress events.

## Quick Start

```bash
python -m backtesting.historical.main --period covid_2020
python -m backtesting.historical.main --period tech_bear_2022 --cap 600
python -m backtesting.historical.main --list
```

## Available Periods

- `covid_2020`: COVID crash and recovery (Feb–June 2020). VIX peaked at 82.69.
- `gamestop_2021`: GameStop retail squeeze (Jan–Feb 2021).
- `tech_bear_2022`: Extended tech bear market (Nov 2021–Dec 2022). VIX peaked at 38.94, NASDAQ down 35%.
- `financial_crisis_2008`: Global financial crisis (Sep 2008–Apr 2009). VIX peaked at 89.53 (highest ever).

## CLI Arguments

| Argument | Type | Default | Description |
|----------|------|---------|-------------|
| `--period` | string | required | Period key (e.g., `covid_2020`, `tech_bear_2022`) |
| `--cap` | int | 400 | Max number of Claude API calls before stopping early |
| `--list` | flag | — | List available periods and exit |
| `--no-report` | flag | — | Skip HTML report generation |
| `--no-email` | flag | — | Skip email delivery |
| `--force` | flag | — | Re-run even if cached results exist |

## Cost Guardrails

**Default cap: 400 Claude calls per backtest** (raised from 200 in previous version).

Each backtest processes N trading days and M tickers. For each (day, ticker) pair that passes the pre-filter (RED or AMBER alert):
- 1 Claude call is made to the model
- ~50–200 input tokens per call (compressed signals + macro context)
- ~30–100 output tokens per call (recommendation + reasoning)

### Budget Examples

| Period | Trading Days | Cap (default) | Est. Calls | Est. Cost (Haiku @ $0.80/M) |
|--------|--------------|---------------|------------|----------------------------|
| covid_2020 | ~90 | 400 | ~80–150 | ~$0.50–$1.00 |
| gamestop_2021 | ~42 | 400 | ~50–120 | ~$0.30–$0.70 |
| tech_bear_2022 | ~252 | 400 | ~200–350 | ~$1.20–$2.00 |
| financial_crisis_2008 | ~125 | 400 | ~150–300 | ~$1.00–$1.80 |

### Adjusting the Cap

To trade off cost vs. completeness, override the default:

```bash
# Conservative: 200 calls (old default)
python -m backtesting.historical.main --period tech_bear_2022 --cap 200

# Aggressive: 1000 calls for thorough analysis
python -m backtesting.historical.main --period financial_crisis_2008 --cap 1000
```

When the cap is reached, the backtest stops early and logs the warning. Results are saved as-is; a partial run can still measure signal quality on the completed portion.

## Workflow Integration

The `historical_backtest.yml` GitHub Actions workflow exposes the cap as a manual input:

1. Go to **Actions** → **Historical Backtest**
2. Click **Run workflow**
3. Select period and cap (defaults to 400)
4. Workflow runs and uploads JSON + HTML results as artifact

## Ticker Availability Notes

Historical backtests must respect which tickers existed and were traded in each period:

- **2008 period**: AAPL, AMZN, GOOGL only. Excludes NVDA, TSLA, PLTR, MSTR, RKLB, ASTS, SOFI, RDDT (didn't exist).
- **2020 period**: All modern tickers available (NVDA, TSLA, etc.).
- **2021 period**: All except RDDT (IPO March 2024).
- **2022 period**: All except RDDT.

## Output

Results are saved to `backtesting/historical/results/{period_key}.json` and include:

- `start_date`, `end_date`: Actual date range processed
- `trading_days_processed`: Number of trading days
- `total_signals_generated`: Count of signals sent to Claude
- `total_claude_calls`: Actual calls made (may be less than cap if all tickers/days completed)
- `token_usage`: Input, output, and cache-read token counts
- `hit_rates`: Per-window (d+5, d+10, d+30) hit rates broken down by recommendation type
- `signals`: Full array of all signals with outcomes and classification

An HTML report is also generated at `backtesting/historical/results/{period_key}_report.html` unless `--no-report` is used.

## Development

Entry point: `backtesting/historical/main.py`

Core engine: `backtesting/historical/runner.py`
- Handles date range parsing, market calendar, yfinance data fetching
- Calls Claude for each flagged (day, ticker) pair
- Evaluates outcomes and computes hit rates

Support: `backtesting/historical/sentiment_proxy.py` and `backtesting/historical/report_builder.py`
