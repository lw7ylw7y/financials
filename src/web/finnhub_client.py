"""Thin client for the Finnhub REST endpoints the Ticker Dashboard needs
(Story 3): quote and 52-week range. Each endpoint is independently
callable so one ticker's failure (bad symbol, rate limit, request
error) can't affect another's -- ticker_dashboard.py catches failures
per-ticker, not here.

`/stock/candle` (historical daily closes) is deliberately not used here
-- confirmed returning 403 "You don't have access to this resource."
for every symbol/resolution/asset-class tried, a free-tier restriction
Finnhub has put in place, not a request-shape problem. The 52-week
range is still free via `/stock/metric`; moving averages need the
daily close series itself, which comes from `yahoo_client.py` instead.
"""

import os

import requests

FINNHUB_BASE_URL = "https://finnhub.io/api/v1"


class FinnhubApiError(Exception):
    """Raised for any Finnhub request/response problem for a single symbol."""


def _require_api_key(api_key: str | None) -> str:
    api_key = api_key or os.environ.get("FINNHUB_API_KEY")
    if not api_key:
        raise FinnhubApiError("FINNHUB_API_KEY not set")
    return api_key


def fetch_quote(symbol: str, api_key: str | None = None) -> dict:
    """Current price for `symbol`. Returns {"price": float}.

    Finnhub returns `c: 0` for an unrecognized/delisted symbol rather
    than an HTTP error, so that case is treated as a failure here too.
    """
    api_key = _require_api_key(api_key)

    try:
        response = requests.get(
            f"{FINNHUB_BASE_URL}/quote",
            params={"symbol": symbol, "token": api_key},
            timeout=10,
        )
        response.raise_for_status()
    except requests.RequestException as e:
        raise FinnhubApiError(f"quote request failed for {symbol}: {e}") from e

    price = response.json().get("c")
    if not price:
        raise FinnhubApiError(f"no quote data for {symbol}")
    return {"price": float(price)}


def fetch_52_week_range(symbol: str, api_key: str | None = None) -> dict:
    """52-week high/low for `symbol`, from Finnhub's own precomputed
    metric (free tier, unlike `/stock/candle`). Returns
    {"low": float, "high": float}.
    """
    api_key = _require_api_key(api_key)

    try:
        response = requests.get(
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
    return {"low": float(low), "high": float(high)}
