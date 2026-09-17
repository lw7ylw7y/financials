"""Thin client for one Yahoo Finance field Finnhub's free tier can't
provide: an ETF's aggregate trailing P/E across its underlying
holdings (`/stock/metric`'s `peTTM` is always empty for a fund --
Finnhub only computes it for individual companies, confirmed live
against every symbol in the stocks/international/sector groups).

Unlike a plain, fully public endpoint, Yahoo's `quoteSummary` now sits
behind an undocumented cookie + "crumb" anti-bot gate -- no account or
registration needed, but also no stability guarantee. Yahoo can change
or remove this at any time, which is why every call here is expected
to fail occasionally and `ticker_dashboard.py` treats that as a normal,
silent "n/a" rather than an error that takes down a ticker's whole
card. A crumb is fetched once per process and cached in memory; a
request that comes back 401 (an expired/invalidated crumb) is retried
exactly once against a freshly-fetched crumb before giving up.
"""

import threading

import requests

_CRUMB_COOKIE_URL = "https://fc.yahoo.com"
_CRUMB_URL = "https://query2.finance.yahoo.com/v1/test/getcrumb"
_QUOTE_SUMMARY_URL = "https://query1.finance.yahoo.com/v10/finance/quoteSummary/{symbol}"
_USER_AGENT = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0 Safari/537.36"

# Shared across every call for connection reuse (see finnhub_client.py's
# identical _session) -- also what carries the cookie the crumb
# handshake sets, which every subsequent quoteSummary call needs
# alongside the crumb value itself.
_session = requests.Session()
_session.headers.update({"User-Agent": _USER_AGENT})

_crumb: str | None = None
_crumb_lock = threading.Lock()


class YahooApiError(Exception):
    """Raised for a genuine Yahoo request/response problem. Never
    raised just because a fund has no aggregate P/E to report -- see
    fetch_etf_pe_ratio, which returns None for that instead.
    """


def _fetch_crumb() -> str:
    try:
        _session.get(_CRUMB_COOKIE_URL, timeout=10)
        response = _session.get(_CRUMB_URL, timeout=10)
        response.raise_for_status()
    except requests.RequestException as e:
        raise YahooApiError(f"crumb request failed: {e}") from e

    crumb = response.text.strip()
    if not crumb:
        raise YahooApiError("empty crumb response")
    return crumb


def _get_crumb() -> str:
    global _crumb
    with _crumb_lock:
        if _crumb is None:
            _crumb = _fetch_crumb()
        return _crumb


def _refresh_crumb_if_unchanged(stale_crumb: str) -> str:
    """Refetches the crumb, unless some other thread already refreshed
    it out from under `stale_crumb` while this one was waiting for the
    lock -- avoids every thread that hit a 401 at once each paying for
    its own redundant crumb fetch.
    """
    global _crumb
    with _crumb_lock:
        if _crumb is None or _crumb == stale_crumb:
            _crumb = _fetch_crumb()
        return _crumb


def _request_quote_summary(symbol: str, crumb: str) -> requests.Response:
    try:
        return _session.get(
            _QUOTE_SUMMARY_URL.format(symbol=symbol),
            params={"modules": "topHoldings", "crumb": crumb},
            timeout=10,
        )
    except requests.RequestException as e:
        raise YahooApiError(f"quoteSummary request failed for {symbol}: {e}") from e


def fetch_etf_pe_ratio(symbol: str) -> float | None:
    """Aggregate trailing P/E across `symbol`'s equity holdings, or
    `None` if there's nothing to report -- `symbol` isn't a fund at all
    (no fundamentals data, e.g. an individual stock), or it is one but
    holds no equities (e.g. a bond fund). Neither case is an error.

    Yahoo's own field (`equityHoldings.priceToEarnings`) is an
    earnings *yield* (E/P), not a P/E multiple -- e.g. SPY's raw
    `0.04035` is its P/E of ~24.8 inverted -- so this inverts it before
    returning.
    """
    crumb = _get_crumb()
    response = _request_quote_summary(symbol, crumb)
    if response.status_code == 401:
        response = _request_quote_summary(symbol, _refresh_crumb_if_unchanged(crumb))

    try:
        response.raise_for_status()
    except requests.HTTPError as e:
        raise YahooApiError(f"quoteSummary request failed for {symbol}: {e}") from e

    try:
        result = response.json()["quoteSummary"]["result"]
    except (KeyError, TypeError) as e:
        raise YahooApiError(f"unexpected quoteSummary response shape for {symbol}: {e}") from e

    if not result:
        return None

    try:
        raw = result[0]["topHoldings"]["equityHoldings"]["priceToEarnings"]["raw"]
    except (KeyError, IndexError, TypeError):
        return None

    return (1 / raw) if raw else None
