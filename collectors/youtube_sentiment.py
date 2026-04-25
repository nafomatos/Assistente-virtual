"""YouTube Data API v3 sentiment collector.

Searches for videos published in the last 48 hours that mention a ticker
or company name in their title. Called only for RED/AMBER pre-filter tickers
to conserve daily quota (YouTube Data API v3: 10,000 units/day free tier;
each search.list costs 100 units).

Degrades gracefully when YOUTUBE_API_KEY is absent or quota is exceeded.
"""

from __future__ import annotations

import datetime as dt
import json
import logging
import os
import re

logger = logging.getLogger(__name__)

_FINANCIAL_KEYWORDS: frozenset[str] = frozenset([
    # General financial terms
    "stock", "stocks", "market", "markets", "trading", "trader", "trade",
    "invest", "investing", "investor", "price", "earnings", "bullish", "bearish",
    "buy", "sell", "dump", "crash", "surge", "rally", "breakout", "dividend",
    "options", "calls", "puts", "futures", "hedge", "portfolio", "ipo", "sec",
    # Technical analysis
    "chart", "analysis", "prediction", "forecast", "target", "support", "resistance",
])

# Extra domain words for each commodity ticker (in addition to _FINANCIAL_KEYWORDS)
_COMMODITY_DOMAIN: dict[str, frozenset[str]] = {
    "GC=F": frozenset(["mining", "ounce", "bullion"]),
    "SI=F": frozenset(["mining", "ounce"]),
    "HG=F": frozenset(["mining", "lb", "lme"]),
    "CL=F": frozenset(["crude", "wti", "brent", "barrel", "opec"]),
    "ZS=F": frozenset(["cbot", "bushel", "harvest"]),
    "NG=F": frozenset(["henry hub", "lng"]),
}

_BEARISH: frozenset[str] = frozenset([
    "crash", "dump", "collapse", "tank", "sell", "selling",
    "bearish", "short", "bubble", "plunge", "fear",
])
_BULLISH: frozenset[str] = frozenset([
    "moon", "explode", "surge", "breakout", "buy", "buying",
    "bullish", "squeeze", "rocket", "rally", "boom",
])

_NULL: dict = {
    "video_count": 0,
    "total_views": 0,
    "top_videos":  [],
    "heat":        "low",
    "tone":        "neutral",
}


def _is_financially_relevant(title: str, ticker: str, company_name: str) -> bool:
    """Return True only if the video title is about the financial asset.

    Two conditions must both be satisfied:
    1. Title contains at least one financial keyword (or commodity-specific domain word).
    2. Title mentions the ticker symbol (word boundary) or company name.
    """
    t = title.lower()

    # Condition 1: financial or commodity-specific keyword present
    keywords = _FINANCIAL_KEYWORDS | _COMMODITY_DOMAIN.get(ticker, frozenset())
    if not any(kw in t for kw in keywords):
        return False

    # Condition 2: ticker or company name appears in the title
    ticker_alpha = re.sub(r"[^a-zA-Z]", "", ticker)  # "GCFF" → "GCF"; "NVDA" → "NVDA"

    # "$TICKER" pattern (e.g., "$NVDA")
    if ticker_alpha and f"${ticker_alpha.lower()}" in t:
        return True

    # Ticker as a standalone word — only when alpha portion is ≥ 3 chars
    # (2-char commodity root like "GC" is too noisy; rely on company name instead)
    if len(ticker_alpha) >= 3 and re.search(
        r"\b" + re.escape(ticker_alpha.lower()) + r"\b", t
    ):
        return True

    # Full company name as a substring (e.g., "Crude Oil WTI")
    name_lower = company_name.lower()
    if name_lower in t:
        return True

    # Any significant word (≥ 4 chars) from the company name
    # Covers "Rocket" from "Rocket Lab", "crude" from "Crude Oil WTI", etc.
    for word in name_lower.split():
        if len(word) >= 4 and word in t:
            return True

    return False


def _classify_tone(titles: list[str]) -> str:
    combined = " ".join(t.lower() for t in titles)
    bearish = sum(1 for kw in _BEARISH if kw in combined)
    bullish = sum(1 for kw in _BULLISH if kw in combined)
    if bearish > bullish:
        return "bearish"
    if bullish > bearish:
        return "bullish"
    return "neutral"


def _heat(video_count: int) -> str:
    if video_count > 10:   return "explosive"
    if video_count >= 4:   return "elevated"
    if video_count >= 1:   return "stable"
    return "low"


def classify_financial_relevance(
    ticker: str,
    company_name: str,
    video_titles: list[str],
) -> list[bool]:
    """Classify video titles as financially relevant using Claude Haiku.

    Sends all titles in a single batch call.  Falls back to the keyword
    filter if the API key is absent or the call fails.
    """
    try:
        import anthropic
    except ImportError:
        logger.warning("YouTube: anthropic package not installed — using keyword filter")
        return [_is_financially_relevant(t, ticker, company_name) for t in video_titles]

    api_key = os.getenv("ANTHROPIC_API_KEY", "").strip()
    if not api_key:
        logger.debug(f"YouTube {ticker}: ANTHROPIC_API_KEY not set — using keyword filter")
        return [_is_financially_relevant(t, ticker, company_name) for t in video_titles]

    system_prompt = (
        "You are a financial relevance classifier. Given a stock ticker or commodity "
        "and a list of YouTube video titles, determine which titles are genuinely about "
        "that financial asset in a market/investment context.\n\n"
        "Return ONLY a JSON array of booleans (true/false), one per title, in the same "
        "order as input.\n"
        "true = the video is about the financial asset (price, trading, market analysis, "
        "earnings, investment)\n"
        "false = the video uses the word incidentally or is about something unrelated "
        "(technology, sports, food, entertainment, etc.)\n\n"
        "Examples:\n"
        '- Ticker: GC=F (Gold), Title: "Gold slips as dollar strengthens" → true\n'
        '- Ticker: GC=F (Gold), Title: "Only 1 Gold Card Visa?" → false\n'
        '- Ticker: HG=F (Copper), Title: "Copper Heatsinks are INSANELY Effective" → false\n'
        '- Ticker: ARM (ARM Holdings), Title: "Why do elite pass rushers have short arms?" → false\n'
        '- Ticker: ARM (ARM Holdings), Title: "ARM Holdings stock jumps after earnings" → true\n'
        '- Ticker: POET (POET Technologies), Title: "We Defended Your Worst Tortured Poets Takes" → false\n'
        '- Ticker: POET (POET Technologies), Title: "POET Technologies surges 28% on Marvell deal" → true'
    )

    numbered = "\n".join(f"{i + 1}. {t}" for i, t in enumerate(video_titles))
    user_prompt = (
        f"Ticker: {ticker} ({company_name})\n"
        f"Titles:\n{numbered}\n\n"
        "Return only a JSON array of booleans."
    )

    try:
        client = anthropic.Anthropic(api_key=api_key)
        message = client.messages.create(
            model="claude-haiku-4-5",
            max_tokens=256,
            system=system_prompt,
            messages=[{"role": "user", "content": user_prompt}],
        )
        raw = message.content[0].text.strip()
        results = json.loads(raw)
        if not isinstance(results, list) or len(results) != len(video_titles):
            raise ValueError(f"unexpected response shape: {raw!r}")
        results = [bool(r) for r in results]
        relevant_count = sum(results)
        logger.info(
            f"Claude Haiku relevance filter: {ticker} — "
            f"{len(video_titles)} titles → {relevant_count} relevant"
        )
        return results
    except Exception as e:
        logger.warning(
            f"YouTube {ticker}: Claude relevance filter failed ({e}) — "
            "falling back to keyword filter"
        )
        return [_is_financially_relevant(t, ticker, company_name) for t in video_titles]


def fetch_youtube_signals(ticker: str, company_name: str) -> dict | None:
    """Search YouTube for recent videos about *ticker* / *company_name*.

    Returns
    -------
    dict with keys: video_count, total_views, top_videos, heat, tone
        when the API key is configured (even if 0 videos found).
    None
        when YOUTUBE_API_KEY is not set or the API client cannot be built
        (caller treats this as "not configured" and skips baseline update).

    Never raises.
    """
    api_key = os.getenv("YOUTUBE_API_KEY", "").strip()
    if not api_key:
        logger.info(f"YouTube {ticker}: YOUTUBE_API_KEY not set — skipping")
        return None

    try:
        from googleapiclient.discovery import build
    except ImportError:
        logger.warning("YouTube: google-api-python-client not installed")
        return dict(_NULL)

    published_after = (
        dt.datetime.utcnow() - dt.timedelta(hours=48)
    ).strftime("%Y-%m-%dT%H:%M:%SZ")

    # Deduplicate query terms (ticker == company_name for some assets)
    queries = list(dict.fromkeys([ticker, company_name]))

    try:
        yt = build("youtube", "v3", developerKey=api_key, cache_discovery=False)
    except Exception as e:
        logger.warning(f"YouTube {ticker}: client build failed — {e}")
        return None

    video_ids: list[str] = []
    title_map: dict[str, str] = {}

    for query in queries:
        try:
            resp = yt.search().list(
                q=query,
                part="id,snippet",
                type="video",
                publishedAfter=published_after,
                maxResults=25,
                relevanceLanguage="en",
                order="relevance",
            ).execute()
        except Exception as e:
            logger.warning(f"YouTube {ticker}: search failed for '{query}' — {e}")
            continue

        for item in resp.get("items", []):
            vid_id = (item.get("id") or {}).get("videoId", "")
            title  = (item.get("snippet") or {}).get("title", "")
            if vid_id and vid_id not in title_map:
                video_ids.append(vid_id)
                title_map[vid_id] = title

    if not video_ids:
        logger.info(f"YouTube {ticker}: 0 videos in last 48h")
        return dict(_NULL)

    # Financial relevance filter — Claude Haiku classifies all titles in one batch call;
    # falls back to keyword filter if the API is unavailable.
    n_raw = len(video_ids)
    titles_for_filter = [title_map[vid_id] for vid_id in video_ids]
    relevance_flags = classify_financial_relevance(ticker, company_name, titles_for_filter)
    video_ids = [vid_id for vid_id, keep in zip(video_ids, relevance_flags) if keep]
    logger.info(
        f"YouTube {ticker}: {n_raw} fetched, "
        f"{len(video_ids)} financially relevant after Claude filter"
    )
    if not video_ids:
        return dict(_NULL)

    # Batch-fetch statistics (max 50 IDs per request)
    view_map:      dict[str, int] = {}
    channel_map:   dict[str, str] = {}
    published_map: dict[str, str] = {}

    try:
        stats_resp = yt.videos().list(
            id=",".join(video_ids[:50]),
            part="statistics,snippet",
        ).execute()
        for item in stats_resp.get("items", []):
            vid_id = item["id"]
            view_map[vid_id]      = int((item.get("statistics") or {}).get("viewCount", 0))
            snippet = item.get("snippet") or {}
            channel_map[vid_id]   = snippet.get("channelTitle", "")
            published_map[vid_id] = snippet.get("publishedAt", "")
    except Exception as e:
        logger.warning(f"YouTube {ticker}: stats fetch failed — {e}")
        # Return heat/tone without view counts (video_ids already filtered)
        titles = [title_map[vid_id] for vid_id in video_ids]
        return {
            "video_count": len(video_ids),
            "total_views": 0,
            "top_videos": [
                {"title": t[:80], "channel": "", "views": 0, "hours_ago": None}
                for t in titles[:3]
            ],
            "heat": _heat(len(video_ids)),
            "tone": _classify_tone(titles),
        }

    now_utc = dt.datetime.utcnow()
    enriched: list[dict] = []
    for vid_id in video_ids:
        pub_str   = published_map.get(vid_id, "")
        hours_ago = None
        if pub_str:
            try:
                pub_dt    = dt.datetime.strptime(pub_str, "%Y-%m-%dT%H:%M:%SZ")
                hours_ago = round((now_utc - pub_dt).total_seconds() / 3600, 1)
            except ValueError:
                pass
        enriched.append({
            "title":     title_map.get(vid_id, "")[:80],
            "channel":   channel_map.get(vid_id, ""),
            "views":     view_map.get(vid_id, 0),
            "hours_ago": hours_ago,
        })

    enriched.sort(key=lambda x: x["views"], reverse=True)
    top_3       = enriched[:3]
    total_views = sum(v["views"] for v in enriched)
    video_count = len(enriched)
    titles      = [v["title"] for v in enriched]

    result = {
        "video_count": video_count,
        "total_views": total_views,
        "top_videos":  top_3,
        "heat":        _heat(video_count),
        "tone":        _classify_tone(titles),
    }
    logger.info(
        f"YouTube {ticker}: {video_count} videos, "
        f"total_views={total_views:,}, heat={result['heat']}, tone={result['tone']}"
    )
    return result
