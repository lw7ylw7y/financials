"""Thin client for Yahoo Finance's public chart endpoint.

Finnhub's free tier blocks `/stock/candle` (historical daily closes)
outright -- a known free-tier restriction, not a request-shape problem.
`/stock/metric` still gives Finnhub's own 52-week high/low for free,
but nothing for moving averages, which need the daily close series
itself. This Yahoo endpoint is undocumented but public (no API key, no
auth, no bot/JS challenge, unlike stooq.com which gates every request
behind a proof-of-work challenge), and is what libraries like yfinance
call under the hood; used directly here via plain `requests` to avoid
pulling in that library's much heavier dependency tree for one field.
"""

import requests

YAHOO_CHART_URL = "https://query1.finance.yahoo.com/v8/finance/chart/{symbol}"
_USER_AGENT = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0 Safari/537.36"


class YahooApiError(Exception):
    """Raised for any Yahoo chart-endpoint request/response problem for a single symbol."""


def fetch_daily_closes(symbol: str, range_: str = "1y") -> list[float]:
    """Daily closes for `symbol` over `range_` (Yahoo's range syntax,
    e.g. "1y"), oldest to newest. Source data for the 20-day/200-day
    simple moving averages -- Yahoo doesn't return those directly.
    Days with no close (e.g. a still-forming current session) are
    skipped rather than raising.
    """
    try:
        response = requests.get(
            YAHOO_CHART_URL.format(symbol=symbol),
            params={"range": range_, "interval": "1d"},
            headers={"User-Agent": _USER_AGENT},
            timeout=10,
        )
        response.raise_for_status()
    except requests.RequestException as e:
        raise YahooApiError(f"chart request failed for {symbol}: {e}") from e

    try:
        result = response.json()["chart"]["result"][0]
        closes = result["indicators"]["quote"][0]["close"]
    except (KeyError, IndexError, TypeError) as e:
        raise YahooApiError(f"unexpected chart response shape for {symbol}: {e}") from e

    closes = [float(c) for c in closes if c is not None]
    if not closes:
        raise YahooApiError(f"no daily closes returned for {symbol}")
    return closes
