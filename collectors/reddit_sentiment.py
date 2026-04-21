"""Reddit sentiment collector using PRAW.

Searches r/wallstreetbets, r/stocks, and r/investing for posts mentioning
a ticker or company name in the last 24 hours and returns a compact signal
dict for the sentiment aggregator.

Requires REDDIT_CLIENT_ID, REDDIT_CLIENT_SECRET, and REDDIT_USER_AGENT in
the environment.  Returns all-None fields (never raises) when credentials
are absent or any API call fails, so the pipeline degrades gracefully.
"""

from __future__ import annotations

import datetime as dt
import json
import logging
import os
import time

import praw
import praw.exceptions

logger = logging.getLogger(__name__)

SUBREDDITS = ["wallstreetbets", "stocks", "investing"]
LOOKBACK_HOURS = 24
TRENDING_WINDOW = 7        # days used to compute the rolling average
TRENDING_MULTIPLIER = 2.0  # today must exceed this × avg to be "trending"

BASELINE_FILE = os.path.join("logs", "reddit_baseline.json")

# Keyword sets for tone classification — checked against lowercased title+selftext
_NEGATIVE = frozenset([
    "crash", "panic", "dump", "dumping", "crashing", "sell", "selling",
    "short", "bubble", "overvalued", "collapse", "collapsing", "rekt",
    "baghold", "bagholder", "puts", "blowup", "implode",
])
_POSITIVE = frozenset([
    "buy the dip", "buy dip", "buying the dip", "opportunity", "moon",
    "mooning", "bullish", "undervalued", "long", "calls", "breakout",
    "squeeze", "short squeeze", "earnings beat", "beat expectations",
])

_NULL_RESULT: dict = {
    "mention_count":  None,
    "avg_score":      None,
    "top_posts":      [],
    "trending":       None,
    "sentiment_tone": None,
}


# ---------------------------------------------------------------------------
# Baseline helpers (trending computation)
# ---------------------------------------------------------------------------

def _load_baseline() -> dict:
    if not os.path.exists(BASELINE_FILE):
        return {}
    try:
        with open(BASELINE_FILE, encoding="utf-8") as f:
            return json.load(f)
    except Exception as e:
        logger.warning(f"reddit baseline load failed: {e}; starting fresh")
        return {}


def _save_baseline(baseline: dict) -> None:
    os.makedirs(os.path.dirname(BASELINE_FILE), exist_ok=True)
    try:
        with open(BASELINE_FILE, "w", encoding="utf-8") as f:
            json.dump(baseline, f, indent=2)
    except Exception as e:
        logger.warning(f"reddit baseline save failed: {e}")


def _update_and_trending(ticker: str, today_count: int) -> bool | None:
    """Persist today's count and return trending flag.

    Returns None when there are fewer than TRENDING_WINDOW days of history
    (can't yet determine a meaningful baseline).
    """
    baseline = _load_baseline()
    history: list[dict] = baseline.get(ticker, [])

    today_str = dt.date.today().isoformat()
    history = [e for e in history if e.get("date") != today_str]
    history.append({"date": today_str, "count": today_count})
    history = history[-(TRENDING_WINDOW + 1):]  # keep one extra for safety
    baseline[ticker] = history
    _save_baseline(baseline)

    prior = [e["count"] for e in history if e.get("date") != today_str]
    if len(prior) < TRENDING_WINDOW:
        return None  # not enough history yet

    avg = sum(prior[-TRENDING_WINDOW:]) / TRENDING_WINDOW
    return today_count > TRENDING_MULTIPLIER * avg


# ---------------------------------------------------------------------------
# Sentiment tone
# ---------------------------------------------------------------------------

def _classify_tone(texts: list[str]) -> str | None:
    combined = " ".join(texts).lower()
    neg = sum(1 for kw in _NEGATIVE if kw in combined)
    pos = sum(1 for kw in _POSITIVE if kw in combined)
    if neg == 0 and pos == 0:
        return None
    if neg > pos:
        return "negative"
    if pos > neg:
        return "positive"
    return "neutral"


# ---------------------------------------------------------------------------
# Core collector
# ---------------------------------------------------------------------------

def _build_client() -> praw.Reddit | None:
    client_id     = os.getenv("REDDIT_CLIENT_ID",     "").strip()
    client_secret = os.getenv("REDDIT_CLIENT_SECRET", "").strip()
    user_agent    = os.getenv("REDDIT_USER_AGENT",    "artificial-price-radar/1.0").strip()

    if not client_id or not client_secret:
        logger.info("Reddit credentials not set; skipping Reddit sentiment")
        return None

    return praw.Reddit(
        client_id=client_id,
        client_secret=client_secret,
        user_agent=user_agent,
        read_only=True,
        ratelimit_seconds=5,
    )


def _search_one_sub(
    reddit: praw.Reddit,
    sub_name: str,
    query: str,
    cutoff_utc: float,
) -> list[praw.models.Submission]:
    """Return all submissions in sub_name matching query within the last 24h."""
    found = []
    try:
        sub = reddit.subreddit(sub_name)
        for post in sub.search(query, sort="new", time_filter="day", limit=100):
            if post.created_utc >= cutoff_utc:
                found.append(post)
    except praw.exceptions.PRAWException as e:
        logger.warning(f"Reddit: r/{sub_name} search error: {e}")
    except Exception as e:
        logger.warning(f"Reddit: r/{sub_name} unexpected error: {e}")
    return found


def fetch_reddit_signals(ticker: str, company_name: str) -> dict:
    """Search Reddit for posts mentioning `ticker` or `company_name` in last 24h.

    Searches r/wallstreetbets, r/stocks, and r/investing.

    Returns
    -------
    {
        "mention_count":  int,           # total matching posts across subreddits
        "avg_score":      float,         # mean upvote score of matching posts
        "top_posts":      list[dict],    # top 3 by score: {title, score, age_hours}
        "trending":       bool | None,   # True if today > 2× 7-day avg; None if not enough history
        "sentiment_tone": str | None,    # "positive" | "negative" | "neutral" | None
    }

    All fields return their null equivalent on any failure — the pipeline
    continues regardless.
    """
    client = _build_client()
    if client is None:
        return dict(_NULL_RESULT)

    cutoff_utc = time.time() - LOOKBACK_HOURS * 3600

    # Search for both ticker symbol and company name to maximise recall.
    # Use a set of post IDs to deduplicate across queries and subreddits.
    seen_ids: set[str] = set()
    all_posts: list[praw.models.Submission] = []

    queries = list({ticker, company_name})  # dedup if name == ticker

    for sub_name in SUBREDDITS:
        for query in queries:
            for post in _search_one_sub(client, sub_name, query, cutoff_utc):
                if post.id not in seen_ids:
                    seen_ids.add(post.id)
                    all_posts.append(post)

    if not all_posts:
        _update_and_trending(ticker, 0)
        return {
            "mention_count":  0,
            "avg_score":      None,
            "top_posts":      [],
            "trending":       _update_and_trending(ticker, 0),
            "sentiment_tone": None,
        }

    # --- Metrics ---
    mention_count = len(all_posts)
    avg_score     = sum(p.score for p in all_posts) / mention_count

    top_three = sorted(all_posts, key=lambda p: p.score, reverse=True)[:3]
    now_utc = time.time()
    top_posts = [
        {
            "title":     (p.title or "")[:120],
            "score":     p.score,
            "age_hours": round((now_utc - p.created_utc) / 3600, 1),
        }
        for p in top_three
    ]

    # Tone: analyse titles (+ selftext snippet) of all matching posts
    texts = [(p.title or "") + " " + (p.selftext or "")[:200] for p in all_posts]
    sentiment_tone = _classify_tone(texts)

    trending = _update_and_trending(ticker, mention_count)

    logger.info(
        f"{ticker}: Reddit — {mention_count} posts, "
        f"avg_score={avg_score:.0f}, trending={trending}, tone={sentiment_tone}"
    )

    return {
        "mention_count":  mention_count,
        "avg_score":      round(avg_score, 1),
        "top_posts":      top_posts,
        "trending":       trending,
        "sentiment_tone": sentiment_tone,
    }
