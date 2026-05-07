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
    "commodities_metals": [
        "GC=F", "SI=F", "HG=F", "PL=F", "PA=F",
        "GLD", "SLV", "GDX", "GDXJ",
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

DIRECTION_GROUPS = {
    "bearish_overheating": ["bubble_forming", "reduce_exposure"],
    "bullish_panic": ["irrational_panic", "contrarian_buy"],
    "institutional": ["institutional_rebalancing", "silent_accumulation"],
}


def get_sector(ticker: str) -> str | None:
    for sector, tickers in SECTOR_MAP.items():
        if ticker in tickers:
            return sector
    return None


def get_direction_group(classification: str, recommendation: str) -> str | None:
    for group, members in DIRECTION_GROUPS.items():
        if classification in members or recommendation in members:
            return group
    return None
