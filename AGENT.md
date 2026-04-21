# AGENT.md — Artificial Price Radar

## Project Context

Personal copilot for detecting **artificial prices** in financial markets.
Runs once per day (NYSE trading days only), analyzes 18 US stocks +
commodities for behavioral signals, and emails a paste-ready report the
user can drop into Claude.ai manually.

**Why it exists:** bubbles and panics leave detectable footprints —
anomalous volume, price moves outside the recent distribution, RSI
extremes, sudden news concentration. Catch the distortion before the
herd reacts.

**Scope:** personal, single user. No UI, no auth, no DB. Simple,
readable, easy to tweak.

---

## Current Architecture (what's actually in the repo)

```
artificial-price-radar/
├── .env.example
├── .gitignore
├── AGENT.md                        # this file
├── README.md
├── requirements.txt
├── main.py                          # orchestrator
├── config.py                        # tickers + thresholds + constants
├── collectors/
│   ├── __init__.py
│   ├── market_data.py              # yfinance: 1y history + news
│   └── fear_greed.py               # alternative.me Fear & Greed Index
├── analyzers/
│   ├── __init__.py
│   ├── volume_analyzer.py          # current vs 30d avg
│   ├── price_velocity.py           # dual-window z-score + macro_extreme
│   └── rsi.py                      # 14-day RSI (Wilder smoothing)
├── claude_advisor/
│   ├── __init__.py
│   └── prompts.py                  # system prompt (embedded in header)
├── delivery/
│   ├── __init__.py
│   └── email_sender.py             # Gmail SMTP plain-text
├── output/
│   ├── __init__.py
│   └── document_builder.py         # writes output/daily_report_<date>.txt
├── utils/
│   ├── __init__.py
│   └── token_optimizer.py          # compress_signals + helpers
├── logs/
│   └── YYYY-MM-DD.txt              # tracked; CI commits new ones daily
└── .github/workflows/
    └── daily_radar.yml             # 06:00 UTC cron + workflow_dispatch
```

### Not yet built

These modules are referenced in the roadmap but intentionally absent:

- `collectors/reddit_sentiment.py`, `twitter_sentiment.py`, `youtube_sentiment.py`
- `analyzers/sentiment_aggregator.py`
- `claude_advisor/advisor.py` — live Claude API with prompt caching and
  token logging. Until this exists, the pipeline writes a paste-ready
  `.txt` and the user runs the analysis manually in Claude.ai.

---

## Data Flow

```
main.main()
  ├─ check_trading_day(date)        # exits cleanly if weekend / holiday / early close
  ├─ fetch_fear_greed()             # one shared macro snapshot
  ├─ for ticker in tickers:
  │     market   = fetch_market_data(ticker)   # prices, vol, news (top 3)
  │     volume   = analyze_volume(market)
  │     velocity = analyze_price_velocity(market)   # z_30d + z_200d + macro_extreme
  │     rsi      = analyze_rsi(market)
  │     -> signals dict
  ├─ write_document(results, date, fear_greed)
  │     └─ passes_prefilter per ticker, render compressed sections
  ├─ archive_log(report, date)      # copy to logs/<date>.txt
  └─ send_report(report_path, date) # Gmail SMTP
```

---

## Monitored Assets (18)

US stocks: NVDA, TSLA, AAPL, AMZN, GOOGL, PLTR, RKLB, ASTS, MU, SOFI, MSTR, RDDT.
Commodities: GC=F, SI=F, CL=F, HG=F, ZS=F, NG=F.

Edit `config.py` to change the list; no other file needs to change.

---

## Module Specifications

### `config.py`
- `US_STOCKS`, `COMMODITIES`, `ALL_TICKERS`, `TICKER_NAMES`
- Thresholds: `VOLUME_SPIKE_THRESHOLD`, `PRICE_VELOCITY_SIGMA`,
  `LOOKBACK_DAYS`, `SENTIMENT_LOOKBACK_HOURS`, `SOCIAL_HEAT_THRESHOLD`
- Model IDs (for Phase 3): `MODEL_PRIMARY = "claude-opus-4-7"`,
  `MODEL_FALLBACK = "claude-sonnet-4-6"`
- Claude call knobs: `CLAUDE_MAX_TOKENS = 600`, `CLAUDE_TEMPERATURE = 0.3`

### `collectors/market_data.py`
`fetch_market_data(ticker, lookback_days=30) -> dict`
- Pulls `period="1y"` from yfinance (enough for 200d window + RSI warmup)
- Returns a compact dict:
  - scalars: `current_price`, `previous_close`, `current_volume`,
    `avg_volume_30d`, `daily_return_pct`,
    `returns_mean_30d`, `returns_std_30d`,
    `returns_mean_200d`, `returns_std_200d`
  - `closes_recent`: last 60 daily closes (for the RSI analyzer)
  - `recent_news`: top 3 items, each `{title, publisher, age_hours}` —
    no URLs, no bodies, token-safe
  - `price_series_summary`: {first, last, min, max}
- Never returns raw OHLC — keeps token budget low when this dict flows
  into `compress_signals()`.

### `collectors/fear_greed.py`
`fetch_fear_greed() -> dict | None`
- GET `https://api.alternative.me/fng/?limit=2` (no auth).
- Returns `{score, label, previous_score, direction}` or `None` on failure.
- `format_summary(fg)` renders a single-line header for the report.
- Graceful: network errors log a warning and degrade to "unavailable".

### `analyzers/volume_analyzer.py`
`analyze_volume(market_data) -> {classification, ratio}`
- Classes: `normal` (<1.5x), `elevated` (1.5-2.5x),
  `anomalous` (2.5-5x), `extreme` (>5x).

### `analyzers/price_velocity.py`
`analyze_price_velocity(market_data) -> dict`
- Dual-window z-score: `z_score_30d` and `z_score_200d`.
- Classification uses whichever is larger in magnitude:
  `normal` (|z|<1), `notable` (1-2), `extreme` (2-3), `blowout` (>3).
- `macro_extreme = True` iff `|z_30d| > 2 AND |z_200d| > 2`.
- `direction`: up / down / flat.

### `analyzers/rsi.py`
`analyze_rsi(market_data) -> {rsi, classification, period}`
- 14-day RSI using Wilder's smoothing over `closes_recent`.
- Bands: `extreme_oversold` (<20), `oversold` (<30),
  `normal` (30-70), `overbought` (>70), `extreme_overbought` (>80).
- Returns `rsi=None` if history is too short.

### `utils/token_optimizer.py`
Pure string helpers — no API calls.
- `truncate_text(text, max_chars=120)`
- `format_top_items(items, max_items=3)`
- `format_news(items, max_items=3)` — one-liners: `"title" — publisher, Nh ago`
- `estimate_tokens(text)` — char/4 heuristic
- `compress_signals(ticker, name, signals) -> str` — the compact user-prompt
  body. Includes dual-z, RSI, and top-3 news lines.

### `claude_advisor/prompts.py`
- `SYSTEM_PROMPT` — sized past Anthropic's 1024-token cache minimum so
  that when Phase 3 wires up the live API, `cache_read_input_tokens` will
  actually fire from call 2 onward. For now the prompt is embedded in
  the report header and sent to Claude.ai manually.

### `output/document_builder.py`
Not allowed to embed model calls. Produces:
```
ARTIFICIAL PRICE RADAR — Daily Report <date>
========================================================================
Macro context — Fear & Greed: NN/100 — Label (+X vs yesterday, direction)
Coverage — 18 tickers processed · N passed · M filtered
  passed:  NVDA, AAPL, ...
  skipped: TSLA, GOOGL, ...
========================================================================

[FILTERED TICKERS — Debug Summary]
  TICKER | VOL | Z_30D | Z_200D | RSI | REASON
  TSLA | 3.2x | -1.1 | +0.2 | 45 | anomalous 3.2x — need >5x or other signal | heat=5 (need >60)
  ...

[SYSTEM PROMPT — ...]
<SYSTEM_PROMPT>

[ASSETS WITH NON-TRIVIAL SIGNALS]
------------------------------------------------------------------------
Asset: <T> (<name>)
Market signals:
- Volume: <class> (<ratio>x 30d avg)
- Price velocity: <class> (z_30d, z_200d, direction, macro_extreme) [⚠ macro_extreme]
- RSI-14: <value> (<band>)
- Current price: $<p> (<ret>% today)
Recent news (last 3):
1. "<title>" — <publisher>, <age>h ago
...
Social signals (social_heat: N/100):
- Reddit / Twitter / YouTube: n/a   (until Phase 4)
========================================================================
[INSTRUCTION]
<closing JSON-array request>
```

**Pre-filter (include an asset in the report):**
- **Extreme volume (>5x) always passes** — leading capitulation signals often
  appear before other confirmations; extreme spikes are caught immediately.
- **Anomalous volume (2.5-5x) requires additional signal confirmation** — must have
  one of: `macro_extreme=True`, `velocity.classification in {"extreme", "blowout"}`,
  or `sentiment.social_heat > SOCIAL_HEAT_THRESHOLD`.
- **Other cases pass only if other signals present:**
  ```
  macro_extreme
    OR velocity.classification in {"extreme", "blowout"}
    OR sentiment.social_heat > SOCIAL_HEAT_THRESHOLD
  ```

**Debug summary:** Each filtered ticker shows:
- Volume ratio and classification
- 30-day and 200-day z-scores
- RSI
- Detailed reason explaining which conditions it failed
  (e.g., "anomalous 3.2x — need >5x or other signal | heat=5 (need >60)")

### `delivery/email_sender.py`
`send_report(report_path=None, date=None)`
- Gmail SMTP `smtp.gmail.com:587` with STARTTLS + App Password.
- Subject: `[Radar] Artificial Price Signals — <date>`.
- Plain-text body = the report file verbatim.
- Raises `EmailConfigError` if env vars missing (pipeline continues
  with a warning rather than crashing).

### `main.py`
Flags:
- `--no-email` — skip the SMTP step.
- `--force`   — bypass the market-calendar check.
- `--date YYYY-MM-DD` — run against an explicit date (useful for tests).
- `--debug` — diagnostic mode: run all 18 tickers (or the explicit list
  you pass), print a per-ticker table with `ticker / volume_ratio /
  z_30d / z_200d / RSI / pre-filter reason`, then exit. Implies
  `--force` and `--no-email`; skips report write and log archival so
  debug runs have no side effects beyond stdout.

Exit codes: `0` on success or clean market-closed exit; `1` only if
email send itself fails after the report was written.

### `.github/workflows/daily_radar.yml`
- Cron `0 6 * * *` (06:00 UTC), plus `workflow_dispatch`.
- `permissions: contents: write` so the archival step can push.
- Steps: checkout → setup-python → `pip install -r requirements.txt`
  → `python main.py` → upload artifact → commit `logs/` back with
  message `[radar] daily log YYYY-MM-DD`.
- Artifact (`daily-report`) is always uploaded when present,
  retention 14 days.

### `logs/` (tracked)
Daily reports land here and get committed by the Action. Makes the
repo an append-only archive you can grep through historically.

---

## Token Optimization Strategy (for Phase 3)

Not active yet, but the current compressed format was designed with
these rules in mind. When `claude_advisor/advisor.py` is added:

1. **Prompt caching** — mark `SYSTEM_PROMPT` with
   `cache_control: {"type": "ephemeral"}`. The prompt is already sized
   past the 1024-token Opus minimum for this to fire.
2. **Pre-filter** — the exact `passes_prefilter` logic in
   `document_builder.py` will move into `advisor.needs_claude_analysis`.
   Catches extreme volume (>5x) immediately as leading capitulation
   signal; anomalous (2.5-5x) requires additional signal confirmation.
   Skips ~60-80% of calls on a typical day.
3. **Data compression** — the `compress_signals()` output is the prompt
   body. No URLs, no IDs, no timestamps, no author names. Text truncated
   to 120 chars. Top 3 items per source max.
4. **Structured output** — JSON schema, `reasoning` capped at 400 chars.
5. **Model choice** — Opus 4.7 only for recommendation generation. Any
   summarization step would use Haiku 4.5.
6. **Temperature 0.3, max_tokens 600.**
7. **Batch API (optional)** — deferred; morning delivery doesn't need
   real-time anyway.
8. **Token logging** — `logger.info(f"{ticker}: input={...} output={...} cached={usage.cache_read_input_tokens}")` on every call.
9. **Dedup macro context** — already done: Fear & Greed is fetched once
   and appears in the header, not per-asset.
10. **Debug summary included** — filtered tickers are shown with their
    metrics and failure reasons, enabling rapid iteration on filter tuning.
11. **Daily budget target** — <30k input tokens total across up to 18
    assets, after pre-filter.

---

## Environment Variables (`.env.example`)

Required today (Phase 2):
```
GMAIL_ADDRESS
GMAIL_APP_PASSWORD
EMAIL_RECIPIENT
```

Reserved for future phases:
```
ANTHROPIC_API_KEY   # Phase 3
REDDIT_CLIENT_ID / REDDIT_CLIENT_SECRET / REDDIT_USER_AGENT   # Phase 4
TWITTER_BEARER_TOKEN                                           # Phase 4
YOUTUBE_API_KEY                                                # Phase 4
```

---

## Implementation Phases

- **Phase 1 (done)** — skeleton + market_data + volume_analyzer +
  price_velocity + token_optimizer + document_builder. No Claude calls.
- **Phase 2 (done)** — Gmail delivery + daily GitHub Action +
  log archive commit-back.
- **Phase 2.5 (done)** — dual-window z-score, RSI-14, market-calendar guard,
  news headlines, Fear & Greed macro context.
- **Phase 2.6 (current)** — relaxed pre-filter (extreme volume >5x always passes,
  anomalous requires confirmation), debug summary showing why filtered tickers
  failed (volume ratio, z-scores, RSI, detailed reasons). Enables rapid iteration
  on filter tuning and catches true panics early (e.g., 17x volume spikes before
  velocity confirmation).
- **Phase 3** — `claude_advisor/advisor.py` with prompt caching and
  token logging. Replaces the manual paste-into-Claude.ai step.
- **Phase 4** — sentiment collectors (Reddit → YouTube → X) and
  `analyzers/sentiment_aggregator.py`.

---

## Code Principles

- Simplicity > elegance. Linear, obvious code.
- Clear logs at each step via `logging`.
- No database — local files only.
- No automated tests in MVP — validate by running `python main.py`.
- One function, one responsibility.
- Fault-tolerant: one broken collector doesn't take the pipeline down
  (Fear & Greed returns `None`, news returns `[]`, a ticker that fails
  to fetch is skipped with an error log and the rest continue).
- When in doubt, do the smaller thing.

---

## "Done" for the current phase

- `python main.py` runs cleanly on a trading day; skips cleanly on
  weekends/holidays/early-close days with no email sent.
- The report written to `output/daily_report_<date>.txt` contains:
  the Fear & Greed header line, coverage summary with passed/skipped lists,
  a debug summary section showing why each filtered ticker was rejected
  (volume ratio, z-scores, RSI, and detailed reasoning), the cached system
  prompt, one section per asset that passes the pre-filter (with dual
  z-scores, RSI, macro_extreme flag, and top-3 news one-liners), and the
  closing JSON-array instruction.
- Pre-filter logic: extreme volume (>5x) always passes (leading capitulation
  signal); anomalous (2.5-5x) requires additional signal confirmation.
- `logs/<date>.txt` is created for every run and (under the Action)
  committed back to the repo.
- Email arrives with Subject `[Radar] Artificial Price Signals — <date>`
  and the full report as plain-text body.
