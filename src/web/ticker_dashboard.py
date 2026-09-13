"""Ticker Dashboard: config loading (Story 2) + per-ticker card assembly
(Story 3).

Loads `config/tickers.json`'s `groups` map -- group names are never
hardcoded here or in `page_template.py`, the dashboard renders whatever
group keys are present, in file order, so adding, renaming, or removing
a group is a config-only edit (Story 2's AC, Section 3.2 of the tech
design). For each ticker, `build_ticker_cards` independently fetches a
quote + 52-week range from Finnhub, a year of daily closes from Yahoo
(for the moving averages -- Finnhub's free tier doesn't serve candles,
see finnhub_client.py's docstring), and recent news from Finnhub; a
failure for one ticker (bad symbol, rate limit, request error, from
either provider) is caught locally and turned into that card's error
state rather than aborting the rest of the dashboard (Story 3's AC,
Section 5.2 of the tech design) -- same per-item isolation pattern as
v1's `run_ingestion`.
"""

import json
import logging
import os
import re

from finnhub_client import fetch_52_week_range, fetch_company_news, fetch_quote
from yahoo_client import fetch_daily_closes

CONFIG_PATH = os.path.join(
    os.path.dirname(__file__), "..", "..", "config", "tickers.json"
)

_TICKER_RE = re.compile(r"^[A-Za-z0-9]+$")
MA_WINDOWS = (20, 200)

logger = logging.getLogger(__name__)


def _is_valid_ticker(symbol) -> bool:
    return isinstance(symbol, str) and bool(_TICKER_RE.match(symbol))


def load_ticker_config(path: str = CONFIG_PATH) -> dict[str, list[str]]:
    """Return `{group_name: [symbols]}` in file order.

    A malformed symbol (empty, non-alphanumeric) is skipped and logged
    rather than raising, before it ever reaches the Finnhub client
    (Story 2's AC) -- well-formed symbols in the same group still load.
    """
    with open(path) as f:
        config = json.load(f)

    groups: dict[str, list[str]] = {}
    for group_name, symbols in config.get("groups", {}).items():
        valid_symbols = []
        for symbol in symbols:
            if _is_valid_ticker(symbol):
                valid_symbols.append(symbol)
            else:
                logger.warning(
                    "skipping malformed ticker symbol=%r group=%s", symbol, group_name
                )
        groups[group_name] = valid_symbols

    return groups


def _simple_moving_average(closes: list[float], window: int) -> float | None:
    """None if fewer than `window` closes are available (e.g. a
    recently-listed ticker) -- documented behavior: show what's
    computable, don't crash (Story 3's test plan)."""
    if len(closes) < window:
        return None
    return sum(closes[-window:]) / window


def _build_card(
    symbol: str,
    group_name: str,
    fetch_quote_fn,
    fetch_week52_fn,
    fetch_closes_fn,
    fetch_news_fn,
) -> dict:
    try:
        price = fetch_quote_fn(symbol)["price"]
        week52 = fetch_week52_fn(symbol)
        closes = fetch_closes_fn(symbol)
        news = fetch_news_fn(symbol)
        return {
            "symbol": symbol,
            "group": group_name,
            "price": price,
            "week52_low": week52["low"],
            "week52_high": week52["high"],
            "ma20": _simple_moving_average(closes, 20),
            "ma200": _simple_moving_average(closes, 200),
            "news": news,
            "error": None,
        }
    except Exception as e:
        logger.error("ticker card build failed symbol=%s error=%s", symbol, e)
        return {
            "symbol": symbol,
            "group": group_name,
            "price": None,
            "week52_low": None,
            "week52_high": None,
            "ma20": None,
            "ma200": None,
            "news": [],
            "error": str(e),
        }


def build_ticker_cards(
    config: dict[str, list[str]] | None = None,
    fetch_quote_fn=fetch_quote,
    fetch_week52_fn=fetch_52_week_range,
    fetch_closes_fn=fetch_daily_closes,
    fetch_news_fn=fetch_company_news,
) -> dict[str, list[dict]]:
    """Return `{group_name: [card, ...]}` in file order, one card per
    ticker in `config` (defaults to `load_ticker_config()`).

    Each card is `{symbol, group, price, week52_low, week52_high, ma20,
    ma200, news, error}` -- `error` is `None` on success, or a message
    with every other field left as `None`/`[]` if that ticker's fetch
    failed. One ticker's failure (from either data source) never
    affects the others.
    """
    config = config if config is not None else load_ticker_config()

    grouped_cards = {}
    for group_name, symbols in config.items():
        grouped_cards[group_name] = [
            _build_card(symbol, group_name, fetch_quote_fn, fetch_week52_fn, fetch_closes_fn, fetch_news_fn)
            for symbol in symbols
        ]
    return grouped_cards
