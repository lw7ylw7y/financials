"""Ticker Dashboard: config loading (Story 2), per-ticker card assembly
(Story 3), and a stored-snapshot fast-render + background-refresh split
(Story 5, added 2026-09-13 after using the page live -- it blocked on
every ticker's Finnhub+Yahoo fetch before showing anything).

Loads `config/tickers.json`'s `groups` map -- group names are never
hardcoded here or in `page_template.py`, the dashboard renders whatever
group keys are present, in file order, so adding, renaming, or removing
a group is a config-only edit (Story 2's AC, Section 3.2 of the tech
design). For each ticker, `build_ticker_cards` independently fetches a
quote + 52-week range from Finnhub and a year of daily closes from
Yahoo (for the moving averages -- Finnhub's free tier doesn't serve
candles, see finnhub_client.py's docstring); a failure for one ticker
(bad symbol, rate limit, request error, from either provider) is caught
locally and turned into that ticker's error state rather than aborting
the rest of the dashboard (Story 3's AC, Section 5.2 of the tech
design) -- same per-item isolation pattern as v1's `run_ingestion`.

`get_initial_ticker_page_data`/`check_for_ticker_updates` mirror
`live_pull.py`'s split for the Indicator Digest Page: the initial page
render reads only `data/tickers.json` (a local snapshot cache, one
entry per ticker, gitignored -- it's a cache, not the historical record
`data/indicators.json` is) so it paints instantly regardless of how
long a live fetch would take; a ticker with no snapshot yet renders as
a pending/loading placeholder. The background check then does the real
fetch and persists every success, so the *next* load has fresher stale
data to show. Unlike the indicator pipeline, there's no "skip if
nothing changed" gate here -- there's no expensive AI call to protect,
so the background check always re-fetches live (Story 3's AC: reloading
re-fetches, never just replays a stale snapshot as if it were current).
A ticker whose live fetch fails falls back to its last stored snapshot
silently (no visible stale/live distinction, matching the Indicator
Digest Page's dropped Live/Saved badge -- see CLAUDE.md); only a ticker
that has *never* been successfully fetched renders as a genuine error.
"""

import json
import logging
import os
import re
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone

from finnhub_client import fetch_52_week_range, fetch_quote
from yahoo_client import fetch_daily_closes

CONFIG_PATH = os.path.join(
    os.path.dirname(__file__), "..", "..", "config", "tickers.json"
)
TICKER_DATA_PATH = os.path.join(
    os.path.dirname(__file__), "..", "..", "data", "tickers.json"
)

_TICKER_RE = re.compile(r"^[A-Za-z0-9]+$")
MA_WINDOWS = (20, 50, 200)
_SNAPSHOT_FIELDS = ("price", "week52_low", "week52_high", "ma20", "ma50", "ma200")

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
) -> dict:
    try:
        price = fetch_quote_fn(symbol)["price"]
        week52 = fetch_week52_fn(symbol)
        closes = fetch_closes_fn(symbol)
        ma20, ma50, ma200 = (_simple_moving_average(closes, w) for w in MA_WINDOWS)
        return {
            "symbol": symbol,
            "group": group_name,
            "price": price,
            "week52_low": week52["low"],
            "week52_high": week52["high"],
            "ma20": ma20,
            "ma50": ma50,
            "ma200": ma200,
            "error": None,
            "pending": False,
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
            "ma50": None,
            "ma200": None,
            "error": str(e),
            "pending": False,
        }


def build_ticker_cards(
    config: dict[str, list[str]] | None = None,
    fetch_quote_fn=fetch_quote,
    fetch_week52_fn=fetch_52_week_range,
    fetch_closes_fn=fetch_daily_closes,
    max_workers: int = 5,
) -> dict[str, list[dict]]:
    """Return `{group_name: [card, ...]}` in file order, one card per
    ticker in `config` (defaults to `load_ticker_config()`).

    Fetches every ticker concurrently (`max_workers` threads) rather
    than one at a time -- with a large watchlist, sequential fetching
    made the background check (Story 5) take tens of seconds.
    `max_workers` is deliberately modest rather than maxed out: Finnhub's
    free tier enforces an overall calls-per-minute rate limit, and
    firing every ticker's calls at once risks 429s, which would just
    turn into more error/stale-fallback cards than the sequential
    version had. `executor.map` preserves input order in its output, so
    the result is grouped/ordered exactly as if this were still
    sequential, regardless of which ticker's fetch finishes first.

    Each card is `{symbol, group, price, week52_low, week52_high, ma20,
    ma50, ma200, error, pending}` -- `error` is `None` on success, or a
    message with every other field left as `None` if that ticker's
    fetch failed. `pending` is always `False` here (this function only
    ever returns the result of an attempted fetch); see
    `get_initial_ticker_page_data` for the stored-only, not-yet-fetched
    case. One ticker's failure (from either data source) never affects
    the others.
    """
    config = config if config is not None else load_ticker_config()
    tasks = [(group_name, symbol) for group_name, symbols in config.items() for symbol in symbols]

    grouped_cards = {group_name: [] for group_name in config}
    if not tasks:
        return grouped_cards

    symbols = [symbol for _, symbol in tasks]
    task_group_names = [group_name for group_name, _ in tasks]
    n = len(tasks)

    with ThreadPoolExecutor(max_workers=min(max_workers, n)) as executor:
        cards = executor.map(
            _build_card,
            symbols,
            task_group_names,
            [fetch_quote_fn] * n,
            [fetch_week52_fn] * n,
            [fetch_closes_fn] * n,
        )
        for (group_name, _symbol), card in zip(tasks, cards):
            grouped_cards[group_name].append(card)

    return grouped_cards


def load_ticker_state(path: str = TICKER_DATA_PATH) -> dict:
    """The local snapshot cache: `{symbol: {price, week52_low,
    week52_high, ma20, ma50, ma200, fetched_at}}`. `{}` if the file
    doesn't exist yet (first run) or is corrupted."""
    try:
        with open(path) as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return {}


def save_ticker_state(state: dict, path: str = TICKER_DATA_PATH) -> None:
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w") as f:
        json.dump(state, f, indent=2)
        f.write("\n")


def _pending_card(symbol: str, group_name: str) -> dict:
    card = {field: None for field in _SNAPSHOT_FIELDS}
    card.update(symbol=symbol, group=group_name, error=None, pending=True)
    return card


def _card_from_snapshot(symbol: str, group_name: str, snapshot: dict) -> dict:
    card = {field: snapshot.get(field) for field in _SNAPSHOT_FIELDS}
    card.update(symbol=symbol, group=group_name, error=None, pending=False)
    return card


def get_initial_ticker_page_data(
    config: dict[str, list[str]] | None = None, state_path: str = TICKER_DATA_PATH
) -> dict[str, list[dict]]:
    """What "/tickers" renders -- instantly, from the local snapshot
    cache only, no network calls. A ticker with no cached snapshot yet
    (first-ever run, or just added to the config) renders as a pending
    placeholder rather than an error -- it hasn't failed, it just
    hasn't been fetched yet; the page's own script then calls
    `/api/check-tickers` to fetch for real.
    """
    config = config if config is not None else load_ticker_config()
    stored = load_ticker_state(state_path)

    grouped_cards = {}
    for group_name, symbols in config.items():
        grouped_cards[group_name] = [
            _card_from_snapshot(symbol, group_name, stored[symbol])
            if symbol in stored
            else _pending_card(symbol, group_name)
            for symbol in symbols
        ]
    return grouped_cards


def check_for_ticker_updates(
    config: dict[str, list[str]] | None = None,
    fetch_quote_fn=fetch_quote,
    fetch_week52_fn=fetch_52_week_range,
    fetch_closes_fn=fetch_daily_closes,
    state_path: str = TICKER_DATA_PATH,
    now: datetime | None = None,
) -> dict[str, list[dict]]:
    """The real live pull, called by the page's own background script
    after the instant stored-only render. Always re-fetches every
    ticker live (Story 3's AC: reloading re-fetches rather than
    replaying a stale snapshot) and persists every success back to
    `state_path` so the *next* instant render has fresher stale data to
    fall back on.

    A ticker whose live fetch fails is quietly replaced with its last
    stored snapshot if one exists -- no visible stale/live distinction
    (same call as the Indicator Digest Page's dropped Live/Saved
    badge). Only a ticker with no stored snapshot *and* a failed live
    fetch renders as a genuine error.
    """
    now = now or datetime.now(timezone.utc)
    config = config if config is not None else load_ticker_config()
    stored = load_ticker_state(state_path)

    live_cards = build_ticker_cards(config, fetch_quote_fn, fetch_week52_fn, fetch_closes_fn)

    grouped_cards = {}
    for group_name, cards in live_cards.items():
        resolved = []
        for card in cards:
            if card["error"] is None:
                stored[card["symbol"]] = {
                    **{field: card[field] for field in _SNAPSHOT_FIELDS},
                    "fetched_at": now.isoformat(),
                }
                resolved.append(card)
            elif card["symbol"] in stored:
                resolved.append(_card_from_snapshot(card["symbol"], group_name, stored[card["symbol"]]))
            else:
                resolved.append(card)
        grouped_cards[group_name] = resolved

    save_ticker_state(stored, state_path)
    return grouped_cards
