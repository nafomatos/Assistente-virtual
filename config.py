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

COMMODITIES = [
    "GC=F",   # Gold
    "SI=F",   # Silver
    "CL=F",   # Crude oil WTI
    "HG=F",   # Copper
    "ZS=F",   # Soybeans
    "NG=F",   # Natural gas
]

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
    "GC=F":  "Gold",
    "SI=F":  "Silver",
    "CL=F":  "Crude Oil WTI",
    "HG=F":  "Copper",
    "ZS=F":  "Soybeans",
    "NG=F":  "Natural Gas",
}

# Analyzer thresholds
VOLUME_SPIKE_THRESHOLD = 2.5       # volume > 2.5x 30d avg = anomalous
PRICE_VELOCITY_SIGMA   = 2.0       # |z| > 2 std dev = extreme
LOOKBACK_DAYS          = 30        # historical window for baselines
SENTIMENT_LOOKBACK_HOURS = 24
SOCIAL_HEAT_THRESHOLD  = 60        # below this, skip Claude call

# Subreddits monitored by the Reddit collector
MONITORED_SUBREDDITS = ["wallstreetbets", "stocks", "investing", "commodities"]

# Claude models
MODEL_PRIMARY  = "claude-opus-4-7"
MODEL_FALLBACK = "claude-sonnet-4-6"

# Claude call knobs
CLAUDE_MAX_TOKENS  = 600
CLAUDE_TEMPERATURE = 0.3
