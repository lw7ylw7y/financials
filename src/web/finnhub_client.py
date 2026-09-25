"""Thin client for the Finnhub REST endpoints the Ticker Dashboard
needs: quote, 52-week range + market cap + P/E + PEG + growth/quality
stats, company industry, and general market news. Each endpoint is
independently callable so one ticker's failure (bad symbol, rate
limit, request error) can't affect another's -- ticker_dashboard.py
catches failures per-ticker, not here.

`/stock/candle` (historical daily closes) and `/stock/price-target`
are deliberately not used here -- both confirmed returning 403 "You
don't have access to this resource." for every symbol/resolution/
asset-class tried, a free-tier restriction Finnhub has put in place,
not a request-shape problem. The 52-week range, market cap, P/E, PEG,
growth/quality stats (`/stock/metric`), company industry
(`/stock/profile2`), and analyst recommendation trends
(`/stock/recommendation`, not currently used by this app but confirmed
free-tier) all remain free.
"""

import os

import requests
from requests.adapters import HTTPAdapter

FINNHUB_BASE_URL = "https://finnhub.io/api/v1"

# Shared across every call (including concurrent ones from
# ticker_dashboard.build_ticker_cards's thread pools) so repeated
# requests to Finnhub reuse an already-open, already-TLS-negotiated
# connection instead of paying a fresh DNS+TCP+TLS handshake every
# single call -- a full page's background check makes up to ~90 of
# these (2 per ETF, 3 per individual company -- quote, metrics, and a
# profile/industry lookup), and that per-call handshake cost is far
# more noticeable on a CPU-constrained host than on a well-resourced
# one. Session objects are documented thread-safe for exactly this
# kind of concurrent reuse.
#
# `requests`' default HTTPAdapter caps each host's connection pool at
# 10, silently below `ticker_dashboard._fetch_concurrency_limit`'s 25
# -- confirmed live via urllib3's own "Connection pool is full,
# discarding connection: finnhub.io" warning once every call in this
# module started going through this shared session concurrently.
# Discarding (rather than reusing) a connection means the excess
# calls pay the DNS+TCP+TLS handshake cost this session exists to
# avoid, so the pool needs to be at least as large as the real
# concurrency ceiling already enforced upstream, not `requests`'
# generic default. `pool_connections` (the number of distinct per-host
# pools kept before the LRU-est is evicted) is left at its default --
# this module only ever talks to one host, so it was never the
# bottleneck.
_session = requests.Session()
_session.mount("https://", HTTPAdapter(pool_maxsize=25))


class FinnhubApiError(Exception):
    """Raised for any Finnhub request/response problem for a single symbol."""


def _require_api_key(api_key: str | None) -> str:
    api_key = api_key or os.environ.get("FINNHUB_API_KEY")
    if not api_key:
        raise FinnhubApiError("FINNHUB_API_KEY not set")
    return api_key


def fetch_quote(symbol: str, api_key: str | None = None) -> dict:
    """Current price plus today's change vs. the previous close, for
    `symbol`. Returns {"price": float, "change": float | None,
    "change_percent": float | None} -- `change`/`change_percent` are
    Finnhub's `d`/`dp` fields; `None` if the response doesn't carry
    them (degrades to "n/a" in the UI rather than crashing).

    Finnhub returns `c: 0` for an unrecognized/delisted symbol rather
    than an HTTP error, so that case is treated as a failure here too.
    """
    api_key = _require_api_key(api_key)

    try:
        response = _session.get(
            f"{FINNHUB_BASE_URL}/quote",
            params={"symbol": symbol, "token": api_key},
            timeout=10,
        )
        response.raise_for_status()
    except requests.RequestException as e:
        raise FinnhubApiError(f"quote request failed for {symbol}: {e}") from e

    data = response.json()
    price = data.get("c")
    if not price:
        raise FinnhubApiError(f"no quote data for {symbol}")

    change = data.get("d")
    change_percent = data.get("dp")
    return {
        "price": float(price),
        "change": float(change) if change is not None else None,
        "change_percent": float(change_percent) if change_percent is not None else None,
    }


def fetch_stock_metrics(symbol: str, api_key: str | None = None) -> dict:
    """52-week high/low, market cap, trailing P/E, PEG ratio, and a
    handful of growth/quality stats for `symbol`, all from Finnhub's
    own precomputed `/stock/metric` (free tier, unlike `/stock/candle`)
    -- one call covers everything, no extra request per field. Returns
    {"low": float, "high": float, "market_cap": float | None,
    "pe_ratio": float | None, "peg_ratio": float | None,
    "revenue_growth": float | None, "eps_growth": float | None, "roe":
    float | None, "net_margin": float | None, "debt_to_equity": float |
    None, "dividend_yield": float | None, "return_13w": float | None,
    "return_26w": float | None, "return_ytd": float | None}. The
    growth/margin/yield/return fields are plain percentages as Finnhub
    returns them (e.g. `14.24` means 14.24%, not `0.1424`);
    `debt_to_equity` is a plain ratio, not a percentage. The returns
    (`13WeekPriceReturnDaily`, `26WeekPriceReturnDaily`,
    `yearToDatePriceReturnDaily`) are price changes over those periods,
    populated for funds as well as companies.

    52-week low/high are required -- a response missing either raises.
    Every other field degrades to `None` (not a raised error) when
    absent -- common for micro-caps, non-US-listed symbols, a company
    with no trailing twelve months of earnings/growth data, or (for
    all of them) an ETF, which Finnhub never computes fund-level
    fundamentals for at all; callers show "n/a" rather than erroring
    the whole row over an optional field. `pe_ratio` prefers `peTTM`,
    falling back to `peBasicExclExtraTTM` then `peNormalizedAnnual`;
    `peg_ratio` prefers the trailing `pegTTM`, falling back to the
    forward-looking `forwardPEG` -- Finnhub doesn't populate every
    field for every symbol, and these fallbacks are the closest
    equivalents it does usually have. The growth/quality fields have no
    such fallback chain (`revenueGrowthTTMYoy`, `epsGrowthTTMYoy`,
    `roeTTM`, `netProfitMarginTTM`, `totalDebt/totalEquityAnnual`,
    `dividendYieldIndicatedAnnual` respectively) -- picked as a
    representative, not exhaustive, cross-section of growth,
    profitability, leverage, and income for a future valuation
    assessment (see CLAUDE.md); Finnhub's `/stock/metric` response
    carries dozens more fields not surfaced here.
    """
    api_key = _require_api_key(api_key)

    try:
        response = _session.get(
            f"{FINNHUB_BASE_URL}/stock/metric",
            params={"symbol": symbol, "metric": "all", "token": api_key},
            timeout=10,
        )
        response.raise_for_status()
    except requests.RequestException as e:
        raise FinnhubApiError(f"metric request failed for {symbol}: {e}") from e

    metric = response.json().get("metric") or {}
    low, high = metric.get("52WeekLow"), metric.get("52WeekHigh")
    if low is None or high is None:
        raise FinnhubApiError(f"no 52-week range for {symbol}")

    market_cap = metric.get("marketCapitalization")
    pe_ratio = metric.get("peTTM")
    if pe_ratio is None:
        pe_ratio = metric.get("peBasicExclExtraTTM")
    if pe_ratio is None:
        pe_ratio = metric.get("peNormalizedAnnual")

    peg_ratio = metric.get("pegTTM")
    if peg_ratio is None:
        peg_ratio = metric.get("forwardPEG")

    revenue_growth = metric.get("revenueGrowthTTMYoy")
    eps_growth = metric.get("epsGrowthTTMYoy")
    roe = metric.get("roeTTM")
    net_margin = metric.get("netProfitMarginTTM")
    debt_to_equity = metric.get("totalDebt/totalEquityAnnual")
    dividend_yield = metric.get("dividendYieldIndicatedAnnual")
    return_13w = metric.get("13WeekPriceReturnDaily")
    return_26w = metric.get("26WeekPriceReturnDaily")
    return_ytd = metric.get("yearToDatePriceReturnDaily")

    return {
        "low": float(low),
        "high": float(high),
        "market_cap": float(market_cap) if market_cap is not None else None,
        "pe_ratio": float(pe_ratio) if pe_ratio is not None else None,
        "peg_ratio": float(peg_ratio) if peg_ratio is not None else None,
        "revenue_growth": float(revenue_growth) if revenue_growth is not None else None,
        "eps_growth": float(eps_growth) if eps_growth is not None else None,
        "roe": float(roe) if roe is not None else None,
        "net_margin": float(net_margin) if net_margin is not None else None,
        "debt_to_equity": float(debt_to_equity) if debt_to_equity is not None else None,
        "dividend_yield": float(dividend_yield) if dividend_yield is not None else None,
        "return_13w": float(return_13w) if return_13w is not None else None,
        "return_26w": float(return_26w) if return_26w is not None else None,
        "return_ytd": float(return_ytd) if return_ytd is not None else None,
    }


def fetch_company_industry(symbol: str, api_key: str | None = None) -> str | None:
    """`symbol`'s Finnhub-assigned industry (`/stock/profile2`'s
    `finnhubIndustry`, e.g. "Semiconductors", "Media", "Automobiles"),
    or `None` if the profile has none -- an ETF or a thinly-covered
    listing, not an error. This is Finnhub's own proprietary industry
    taxonomy, not a GICS sector name; `ticker_dashboard._SECTOR_ETF_BY_INDUSTRY`
    is what maps a handful of these strings to one of the configured
    sector-ETF tickers for a peer-benchmark comparison.

    `/stock/profile2` is free-tier (unlike `/stock/candle` or
    `/etf/*`), confirmed live.
    """
    api_key = _require_api_key(api_key)

    try:
        response = _session.get(
            f"{FINNHUB_BASE_URL}/stock/profile2",
            params={"symbol": symbol, "token": api_key},
            timeout=10,
        )
        response.raise_for_status()
    except requests.RequestException as e:
        raise FinnhubApiError(f"profile request failed for {symbol}: {e}") from e

    return response.json().get("finnhubIndustry")


def fetch_market_news(api_key: str | None = None, limit: int = 10) -> list[dict]:
    """Recent US stock market headlines. Returns up to `limit`
    {"headline": str, "url": str, "source": str, "datetime": int}
    dicts, newest first (Finnhub already returns them in that order).

    Finnhub's `/news?category=general` is a broad news wire, not
    stock-market-specific -- most of it is general business/world news,
    with only a minority tagged `"top news"`, which is the closest
    thing to "market news" Finnhub's own categorization offers on the
    free tier. Filtered to `category == "top news"` here rather than
    attempting fragile keyword matching on headlines.
    """
    api_key = _require_api_key(api_key)

    try:
        response = _session.get(
            f"{FINNHUB_BASE_URL}/news",
            params={"category": "general", "token": api_key},
            timeout=10,
        )
        response.raise_for_status()
    except requests.RequestException as e:
        raise FinnhubApiError(f"market news request failed: {e}") from e

    articles = response.json() or []
    headlines = [
        {
            "headline": a["headline"],
            "url": a["url"],
            "source": a.get("source", ""),
            "datetime": a["datetime"],
        }
        for a in articles
        if a.get("category") == "top news" and a.get("headline") and a.get("url")
    ]
    return headlines[:limit]
