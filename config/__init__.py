"""Configuration for the Artificial Price Radar.

Edit this file to tweak asset lists, thresholds and model IDs.
"""

US_STOCKS = [
    "NVDA",   # AI, high volatility
    "TSLA",   # Cult stock, emotional extremes
    "AAPL",   # Heavy index weight
    "AMZN",   # #1 WSB 2026
    "GOOGL",  # Best Mag7 performer in 2025
    "PLTR",   # Cult following, highly speculative
    "RKLB",   # #1 Reddit 2026, +180% in 2025
    "ASTS",   # Space race favorite
    "MU",     # Cyclical semiconductor
    "SOFI",   # Retail favorite
    "MSTR",   # Bitcoin proxy, extreme leverage
    "RDDT",   # WSB betting on itself
]

# Metals use ETF proxies, not front-month futures: yfinance silently stitches
# futures contracts at roll, injecting fake volume that poisoned vol_multiple
# and the v2 volume_dist gate (GC=F 310x on 2026-05-18; SI=F vol_dist 58.84 on
# 2026-06-09 — see logs/volume_artifacts.log and backtests/VOLUME_FIX*.md).
# ETFs have no contract rolls, so their volume is real and usable by the gates.
# Copper uses COPX (copper miners, ~millions of shares/day) rather than CPER
# (pure-price proxy but too thin for volume-based signals) — see
# scripts/validate_etf_volume.py for the liquidity evidence.
# TODO: CL=F / ZS=F / NG=F are still front-month futures and rely on the
# Layer-1 artifact containment (analyzers/volume_quality.py) around rolls;
# candidate ETF proxies if their volume ever needs to be gate-usable: USO,
# DBA/SOYB, UNG.
COMMODITIES = [
    "GLD",    # Gold (SPDR Gold Shares — replaces GC=F)
    "SLV",    # Silver (iShares Silver Trust — replaces SI=F)
    "CL=F",   # Crude oil WTI
    "COPX",   # Copper miners (Global X — replaces HG=F; CPER too thin)
    "ZS=F",   # Soybeans
    "NG=F",   # Natural gas
]

# Kept for fallback when active_tickers.json is unavailable.
ALL_TICKERS = US_STOCKS + COMMODITIES

# Human-readable names used in text searches and prompts.
TICKER_NAMES = {
    "NVDA":  "Nvidia",
    "TSLA":  "Tesla",
    "AAPL":  "Apple",
    "AMZN":  "Amazon",
    "GOOGL": "Alphabet",
    "PLTR":  "Palantir",
    "RKLB":  "Rocket Lab",
    "ASTS":  "AST SpaceMobile",
    "MU":    "Micron",
    "SOFI":  "SoFi",
    "MSTR":  "MicroStrategy",
    "RDDT":  "Reddit",
    "GLD":   "Gold (GLD)",
    "SLV":   "Silver (SLV)",
    "CL=F":  "Crude Oil WTI",
    "COPX":  "Copper Miners (COPX)",
    "ZS=F":  "Soybeans",
    "NG=F":  "Natural Gas",
    # Legacy display names — retired front-month futures symbols still appear
    # in historical logs, the weekly summary, and old signals files.
    "GC=F":  "Gold (futures, retired)",
    "SI=F":  "Silver (futures, retired)",
    "HG=F":  "Copper (futures, retired)",
}

# Analyzer thresholds
VOLUME_SPIKE_THRESHOLD   = 2.5       # volume > 2.5x 30d avg = anomalous
PRICE_VELOCITY_SIGMA     = 2.0       # |z| > 2 std dev = extreme
LOOKBACK_DAYS            = 30        # historical window for baselines
SENTIMENT_LOOKBACK_HOURS = 24
SOCIAL_HEAT_THRESHOLD    = 60        # below this, skip Claude call

# Claude models
MODEL_PRIMARY  = "claude-opus-4-7"
MODEL_FALLBACK = "claude-sonnet-4-6"

# Claude call knobs
CLAUDE_MAX_TOKENS  = 600   # per-ticker calls (future advisor.py)
CLAUDE_TEMPERATURE = 0.3

# The daily classifier answers for ALL flagged assets in one call
# (HUMAN_SUMMARY + full JSON array), so it needs a larger budget.
CLAUDE_MAX_TOKENS_DAILY = 2048

# Dynamic ticker management
MAX_DYNAMIC_TICKERS         = 15   # cap on simultaneously tracked dynamic tickers
DYNAMIC_PROMOTION_THRESHOLD = 3    # RED/AMBER triggers within 30d → promote to permanent
FLAT_DEMOTION_THRESHOLD     = 30   # consecutive flat days → demote to inactive
