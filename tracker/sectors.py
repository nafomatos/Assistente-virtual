"""Sector and direction-group mappings for cluster detection."""

from __future__ import annotations

SECTOR_MAP = {
    "semis": [
        "NVDA", "AMD", "INTC", "MU", "SMCI", "ARM", "POET",
        "SNDK", "NBIS", "SOUN", "TSM", "AVGO", "QCOM", "MRVL",
        "ASML", "AMAT", "LRCX", "KLAC",
    ],
    "fintech": [
        "SOFI", "HOOD", "COIN", "MSTR", "PYPL", "SQ", "AFRM",
        "UPST", "LC", "NU",
    ],
    "mega_tech": [
        "AAPL", "MSFT", "GOOGL", "GOOG", "META", "AMZN", "TSLA",
        "NFLX", "ORCL", "CRM",
    ],
    # Active metal symbols are the ETF proxies (GLD/SLV/COPX — see
    # config/__init__.py). The retired front-month futures symbols stay mapped
    # so historical signals files within the rolling cluster window and
    # backtests keep clustering correctly.
    "commodities_metals": [
        "GLD", "SLV", "COPX", "CPER", "GDX", "GDXJ",
        "GC=F", "SI=F", "HG=F", "PL=F", "PA=F",
    ],
    "energy": [
        "CL=F", "NG=F", "BZ=F", "RB=F",
        "XOM", "CVX", "COP", "OXY", "USO", "XLE",
    ],
    "agri": [
        "ZS=F", "ZC=F", "ZW=F", "KC=F", "SB=F", "CC=F",
        "DBA", "MOO",
    ],
    "meme_retail": [
        "GME", "RDDT", "PLTR", "RKLB", "ASTS", "AMC", "BB",
        "BBBY", "KOSS", "EXPR",
    ],
    "etfs_broad": [
        "SPY", "QQQ", "IWM", "DIA", "VTI", "VOO",
    ],
    "biotech": [
        "MRNA", "BNTX", "PFE", "JNJ", "GILD", "AMGN", "REGN", "VRTX",
        "XBI", "IBB",
    ],
    "china_tech": [
        "BABA", "JD", "PDD", "BIDU", "NIO", "XPEV", "LI",
        "KWEB", "FXI",
    ],
    # MSTR and COIN already appear in fintech; crypto_proxies covers the
    # remaining pure-play mining and spot/futures tickers.
    "crypto_proxies": [
        "MARA", "RIOT", "CLSK", "HUT",
        "BTC-USD", "ETH-USD", "GBTC", "BITO",
    ],
}

TICKER_TO_SECTOR = {
    ticker: sector for sector, tickers in SECTOR_MAP.items() for ticker in tickers
}

DIRECTION_GROUPS = {
    "bearish_overheating": ["bubble_forming", "reduce_exposure"],
    "bullish_panic": ["irrational_panic", "contrarian_buy"],
    "institutional": ["institutional_rebalancing", "silent_accumulation"],
}


def get_sector(ticker: str) -> str | None:
    return TICKER_TO_SECTOR.get(ticker)


def get_direction_group(classification: str, recommendation: str) -> str | None:
    for group, members in DIRECTION_GROUPS.items():
        if classification in members or recommendation in members:
            return group
    return None
