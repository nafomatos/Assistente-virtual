# AGENT.md — Artificial Price Radar

## Project Context

Personal copilot for detecting **artificial prices** in financial markets.
Runs once per day (NYSE trading days only), analyzes a dynamic list of US
stocks + commodities for behavioral signals, classifies the flagged assets
with Claude, applies code-enforced strategy gates, tracks the resulting
positions, and delivers a digest email plus a full HTML report on GitHub
Pages.

**Why it exists:** bubbles and panics leave detectable footprints —
anomalous volume, price moves outside the recent distribution, RSI
extremes, sudden news/social concentration. Catch the distortion before
the herd reacts.

**Scope:** personal, single user. No UI, no auth, no DB. Simple,
readable, easy to tweak.

> This file describes intent and shape. When it disagrees with the code,
> the code wins — thresholds and rules live in the modules listed below.

---

## Current Architecture

```
Assistente-virtual/
├── .env.example
├── AGENT.md                         # this file
├── main.py                          # orchestrator (see Data Flow)
├── requirements.txt
├── config/
│   ├── __init__.py                  # tickers, thresholds, model IDs, knobs
│   ├── ticker_manager.py            # three-tier dynamic ticker list
│   └── active_tickers.json          # persisted ticker state
├── collectors/
│   ├── market_data.py               # yfinance 2y history + news + long_horizon
│   ├── fear_greed.py                # alternative.me Fear & Greed Index
│   ├── vix_structure.py             # ^VIX vs ^VIX3M term structure
│   ├── buffett_indicator.py         # Wilshire 5000 / GDP (needs FRED_API_KEY)
│   ├── trending_tickers.py          # ApeWisdom + Yahoo trending discovery
│   ├── youtube_sentiment.py         # YouTube Data API v3 (RED/AMBER only)
│   └── stocktwits_sentiment.py      # DISABLED stub (403 on CI runner IPs)
├── analyzers/
│   ├── volume_analyzer.py           # current vs 30d avg (roll-aware)
│   ├── price_velocity.py            # dual-window z-score + macro_extreme
│   ├── rsi.py                       # 14-day RSI (Wilder smoothing)
│   ├── sentiment_aggregator.py      # social_heat_zscore (YouTube-weighted)
│   └── position_sizing.py           # size %, targets, time window, strikes
├── claude_advisor/
│   ├── prompts.py                   # SYSTEM_PROMPT (thresholds interpolated
│   │                                #   from signal_gates constants)
│   ├── classifier.py                # automated daily Claude classification
│   ├── signal_gates.py              # Strategy v2 short gates (code-enforced)
│   └── weekly_advisor.py            # Friday narrative via Claude Haiku
├── tracker/
│   ├── sectors.py                   # SECTOR_MAP + direction groups
│   ├── cluster_detector.py          # detect_clusters + apply_cluster_boosts
│   ├── position_tracker.py          # open/closed positions, stop loss, d+30
│   ├── recommendation_parser.py     # manual-paste entry path (conf floors)
│   ├── add_recommendations.py       # CLI for the manual-paste workflow
│   └── positions.json               # persisted positions
├── output/
│   ├── document_builder.py          # daily .txt report + RED/AMBER tiers
│   └── weekly_summary.py            # parses the week's logs for the digest
├── delivery/
│   ├── email_sender.py              # Gmail SMTP, HTML + plain-text
│   ├── digest_builder.py            # mobile-first one-screen digest email
│   └── pages_publisher.py           # docs/reports/<date>.html + index
├── utils/
│   └── token_optimizer.py           # compress_signals + long-horizon block
├── backtesting/
│   ├── tracker.py / evaluate.py     # manual recommendation log + evaluation
│   └── historical/                  # standalone historical backtest engine
├── scripts/
│   └── run_cluster_validation.py    # cluster-boost A/B validation harness
├── tests/                           # pytest suite (pure-logic modules)
├── logs/                            # daily .txt + signals_*.json + clusters_*.json
├── docs/                            # GitHub Pages (reports + index)
└── .github/workflows/
    ├── daily_radar.yml              # cron 20:00 UTC Mon-Fri + dispatch
    ├── cluster_validation.yml       # manual dispatch
    └── historical_backtest.yml      # manual dispatch
```

---

## Data Flow (main.main)

```
1.  check_trading_day(date)        # NYSE calendar; weekend/holiday/early-close → clean exit
                                   # --force bypasses for non-weekend; weekend + --force
                                   #   runs the weekly-only email path
2.  Ticker discovery               # get_active_tickers() + fetch_trending_tickers();
                                   #   skipped when explicit tickers passed on the CLI
3.  Macro context (once)           # Fear & Greed, VIX structure, Buffett Indicator
4.  run_pipeline(tickers)          # per ticker: market_data → volume / velocity / RSI
                                   #   + sentiment aggregate (StockTwits disabled)
5.  enrich_with_youtube(results)   # YouTube fetched ONLY for RED/AMBER tickers (quota)
6.  Ticker state updates           # record triggers/flats, promote/demote, stale removal
7.  Position tracker               # close stop-outs (25% adverse) and d+30 expiries,
                                   #   refresh open positions
8.  write_document(...)            # paste-ready .txt (RED first, then AMBER)
9.  archive_log(...)               # copy to logs/<date>.txt (committed by the Action)
10. classify_signals(report)       # Claude call (no-op without ANTHROPIC_API_KEY)
11. apply_short_gates(...)         # Strategy v2 — code-enforced; persist signals JSON
12. Cluster boost (opt-in)         # CLUSTER_BOOST_ENABLED=true: detect_clusters +
                                   #   apply_cluster_boosts; re-persist signals
13. _attach_sizing_blocks(...)     # position sizing from the gated+boosted signals
14. publish_report(...)            # full HTML to docs/reports/<date>.html
15. send_report(...)               # digest email (unless --no-email)
16. Weekly summary                 # Fridays (or weekend + --force): logs → summary →
                                   #   Haiku narrative → weekly email
```

CLI flags: `--no-email`, `--force`, `--date YYYY-MM-DD`, `--debug`
(implies `--force --no-email`; prints per-ticker table, writes no state),
or explicit tickers (`python main.py NVDA TSLA`) to skip discovery.

---

## Monitored Assets

The ticker list is **dynamic**, managed by `config/ticker_manager.py` in
three tiers persisted to `config/active_tickers.json`:

- **permanent** — the original 18 (12 US stocks + 6 commodities defined in
  `config/__init__.py`) plus promoted dynamic tickers.
- **dynamic** — discovered daily via ApeWisdom/Yahoo trending; promoted to
  permanent after `DYNAMIC_PROMOTION_THRESHOLD` RED/AMBER triggers in 30
  days; removed when stale.
- **inactive** — demoted after `FLAT_DEMOTION_THRESHOLD` consecutive flat
  days; paused, not deleted.

---

## Alert Tiers (pre-filter)

`output/document_builder.py: get_alert_tier()` decides which assets reach
Claude:

- **RED** — extreme volume (>5x, unless `data_quality == "suspicious_volume"`,
  i.e. a futures contract-roll artifact) OR `macro_extreme`
  (|z30| > 2 AND |z200| > 2).
- **AMBER** — any of: |z30| > 1.5 with vol > 1.5x; anomalous volume (>2.5x);
  RSI > 75 or < 25; social-heat z > 2.0 with vol > 1.0x.
- Everything else is filtered out but shown in the debug summary with the
  reason it fell short.

---

## Classification & Strategy v2 Gates

`claude_advisor/classifier.py` sends the daily report to `MODEL_PRIMARY`
(falling back to `MODEL_FALLBACK`), expecting the two-section
`HUMAN_SUMMARY:` / `JSON_OUTPUT:` contract defined in `prompts.py`. The
parser tolerates markdown fences and falls back to a bare JSON array.

Each signal is `{ticker, classification, recommendation, reasoning,
confidence}` with classifications: `irrational_panic` (→ contrarian_buy),
`bubble_forming` (→ reduce_exposure), `institutional_rebalancing`,
`silent_accumulation`, `ambiguous`/`no_signal`.

**`claude_advisor/signal_gates.py` is the single source of truth for all
strategy thresholds** — the SYSTEM_PROMPT interpolates them, so prompt and
code cannot drift. The v2 gates run after classification and only ever
tighten SHORT signals (longs are never touched):

1. **AI-hardware-in-bull** — semis + Buffett > 200% + z200 ≥ +2 +
   vol_dist ≤ 1.0 → reclassify to `institutional_rebalancing`/`wait`.
2. **Volume distribution (PRIMARY)** — vol_dist must exceed 1.0
   (down-day volume > up-day volume); missing = not confirmed → wait.
3. **Sustained extension** — needs ext vs 200d MA > +60% (single name,
   +40% index) AND ≥ 30/60 sustained days → otherwise wait.
4. **Macro fear cap** — F&G < 35 caps surviving bubble confidence at 5,
   below the actionable short floor.

Actionable-confidence floors (code-enforced in
`recommendation_parser.py`): shorts ≥ `MIN_SHORT_CONFIDENCE` (6), longs ≥
`MIN_LONG_CONFIDENCE` (7).

The long-horizon inputs to the gates (`price_extension_200d`,
`sustained_days_60`, `volume_dist_ratio`, etc.) are computed in
`collectors/market_data.py: _compute_long_horizon()` from 2 years of
history; `volume_dist_ratio` excludes flat days and zero-volume roll rows.

### Cluster Signal Booster (opt-in: `CLUSTER_BOOST_ENABLED=true`)

`tracker/cluster_detector.py` scans the last 5 business days of
`logs/signals_YYYY-MM-DD.json` for 3+ same-sector tickers signalling the
same direction (sector map in `tracker/sectors.py`). `apply_cluster_boosts`
adds +1 (3-4 tickers) or +2 (5+) confidence, with two safety rules:

- never boosts a signal whose confidence was capped by the macro fear gate;
- only boosts a signal that is itself a member of the cluster (today's
  signals are persisted before detection, so a genuine match is always a
  member — this keeps stale clusters from arming today's signal).

---

## Position Tracking & Sizing

- `tracker/position_tracker.py` — positions persist in
  `tracker/positions.json`. Stop loss closes at a 25% adverse move
  (checked first); otherwise positions close at d+30. Aggregate "correct"
  under v2 means realized P&L > 0.
- `analyzers/position_sizing.py` — pure post-classification math: position
  size % (confidence-banded, zero below the floors, 1.25x multiplier when
  cluster-boosted), price targets, time window, option strikes.
- Entry paths: automated (classifier → gates → sizing) or manual paste
  (`python -m tracker.add_recommendations --json '...'`).

---

## Delivery

- **Digest email** (`digest_builder.py` via `email_sender.py`) — one-screen
  mobile summary linking to the full report. Gmail SMTP with App Password;
  `EmailConfigError` degrades to a warning instead of crashing the run.
- **GitHub Pages** (`pages_publisher.py`) — full HTML report at
  `docs/reports/YYYY-MM-DD.html` + newest-first `docs/index.html`.
- **Weekly email** — Fridays (or weekend + `--force`):
  `output/weekly_summary.py` parses the week's logs and
  `claude_advisor/weekly_advisor.py` writes a short Portuguese narrative
  (Claude Haiku; empty string on failure so the email still sends).

---

## Environment Variables

Required for full operation (see `.env.example`):

```
GMAIL_ADDRESS / GMAIL_APP_PASSWORD / EMAIL_RECIPIENT   # email delivery
ANTHROPIC_API_KEY      # automated classification + weekly narrative
FRED_API_KEY           # Buffett Indicator (GDP series)
YOUTUBE_API_KEY        # social heat for RED/AMBER tickers
CLUSTER_BOOST_ENABLED  # "true" to enable the cluster booster (default off)
TWITTER_BEARER_TOKEN   # reserved; not used by the daily pipeline
```

Everything degrades gracefully when a key is missing: classification is
skipped, the Buffett line shows unavailable, YouTube heat is n/a.

---

## GitHub Actions

- `daily_radar.yml` — cron `0 20 * * 1-5` (20:00 UTC Mon-Fri) +
  `workflow_dispatch`. Runs `python main.py`, uploads the report artifact,
  commits `logs/` and `docs/` back to the repo.
- `cluster_validation.yml` — manual; runs
  `scripts/run_cluster_validation.py` (A/B of boost on/off over history).
- `historical_backtest.yml` — manual; runs the standalone engine in
  `backtesting/historical/` (cached yfinance data, Haiku per flagged day,
  hit rates at d+5/d+10/d+30).

---

## Testing

`python -m pytest tests/ -q` — the suite covers the pure-logic core:
signal gates (including a replay of the May-2026 V1 cohort), cluster
detection and boost rules, classifier JSON parsing, long-horizon metrics,
position tracker close logic, position sizing, recommendation-parser
floors, tier suppression, and volume data quality. Network modules
(collectors, delivery) are validated by running the pipeline.

---

## Code Principles

- Simplicity > elegance. Linear, obvious code.
- Clear logs at each step via `logging`.
- No database — local JSON/txt files only.
- One function, one responsibility.
- Fault-tolerant: one broken collector never takes the pipeline down.
- Strategy rules are code-enforced, never prompt-only — the V1
  retrospective showed prompt guidance is ignored under pressure.
- Constants live in one place (`signal_gates.py` for strategy,
  `config/__init__.py` for pipeline knobs); prose that repeats them must
  be generated from them.
- When in doubt, do the smaller thing.

---

## History (phases, all shipped)

1. **Phase 1-2.6** — signal skeleton (volume/velocity/RSI), Gmail delivery,
   daily Action with log commit-back, dual-window z-scores, market-calendar
   guard, Fear & Greed, relaxed pre-filter with debug summary.
2. **Tiered alerts + macro** — RED/AMBER tiers, VIX term structure,
   Buffett Indicator, dynamic ticker discovery/promotion, YouTube
   sentiment with quota gating (StockTwits built then disabled — 403s).
3. **Automation** — automated Claude classification, position tracker,
   position sizing, digest email + GitHub Pages, weekly summary email.
4. **Strategy v2** (current) — code-enforced short gates + macro fear cap
   (from the V1 retrospective: longs went 2/2, AI-hardware shorts 0/4),
   long-horizon metrics, cluster signal booster behind
   `CLUSTER_BOOST_ENABLED`, historical backtest + cluster validation
   harnesses.
