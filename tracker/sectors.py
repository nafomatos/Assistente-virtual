"""Sector and direction-group mappings for cluster detection."""

from __future__ import annotations

SECTOR_MAP = {
    "semis": ["NVDA", "AMD", "INTC", "MU", "SMCI", "ARM", "POET", "SNDK", "NBIS", "SOUN"],
    "fintech": ["SOFI", "HOOD", "COIN", "MSTR"],
    "mega_tech": ["AAPL", "MSFT", "GOOGL", "META", "AMZN"],
    "commodities_metals": ["GC=F", "SI=F", "HG=F"],
    "energy": ["CL=F", "NG=F"],
    "agri": ["ZS=F"],
    "meme_retail": ["GME", "RDDT", "PLTR", "RKLB", "ASTS"],
    "etfs_broad": ["SPY", "QQQ"],
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
