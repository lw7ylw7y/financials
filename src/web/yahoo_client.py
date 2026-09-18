"""Thin client for one Yahoo Finance field Finnhub's free tier can't
provide: an ETF's aggregate trailing P/E across its underlying
holdings (`/stock/metric`'s `peTTM` is always empty for a fund --
Finnhub only computes it for individual companies, confirmed live
against every symbol in the stocks/international/sector groups).

This is Yahoo's undocumented `quoteSummary` endpoint -- no account or
registration needed, but also no stability guarantee. Yahoo can change
or remove this at any time, which is why every call here is expected
to fail occasionally and `ticker_dashboard.py` treats that as a normal,
silent "n/a" rather than an error that takes down a ticker's whole
card. A cookie + "crumb" handshake (`/v1/test/getcrumb`) was tried
first, but dropped: it isn't actually required for this endpoint (a
plain GET works without one), and it reliably 429'd from Render's
shared-hosting IP, which made ETF P/E permanently "n/a" there --
removing it fixes that and simplifies this module.
"""

import requests
from requests.adapters import HTTPAdapter

_QUOTE_SUMMARY_URL = "https://query1.finance.yahoo.com/v10/finance/quoteSummary/{symbol}"
_USER_AGENT = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0 Safari/537.36"

# Shared across every call for connection reuse (see finnhub_client.py's
# identical _session, including its pool_maxsize=25 -- matched here for
# the same reason: this fallback is called from inside the same
# per-ticker critical section `finnhub_client._session` is, gated by
# the same `ticker_dashboard._fetch_concurrency_limit`, so it's exposed
# to the same up-to-25-concurrent-calls pattern and the same "pool
# full, discarding connection" problem if left at `requests`' default
# of 10).
_session = requests.Session()
_session.mount("https://", HTTPAdapter(pool_maxsize=25))
_session.headers.update({"User-Agent": _USER_AGENT})


class YahooApiError(Exception):
    """Raised for a genuine Yahoo request/response problem. Never
    raised just because a fund has no aggregate P/E to report -- see
    fetch_etf_pe_ratio, which returns None for that instead.
    """


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
    try:
        response = _session.get(
            _QUOTE_SUMMARY_URL.format(symbol=symbol),
            params={"modules": "topHoldings"},
            timeout=10,
        )
        response.raise_for_status()
    except requests.RequestException as e:
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
