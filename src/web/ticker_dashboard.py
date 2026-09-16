"""Ticker Dashboard: config loading, per-ticker card assembly, and a
stored-snapshot fast-render + background-refresh split.

Loads `config/tickers.json`'s `groups` map -- group names are never
hardcoded here or in `page_template.py`, the dashboard renders whatever
group keys are present, in file order, so adding, renaming, or removing
a group is a config-only edit. For each ticker, `build_ticker_cards`
independently fetches a quote + 52-week range/market cap/P/E from
Finnhub and a year of daily closes from Yahoo (for the moving averages
-- Finnhub's free tier doesn't serve candles, see finnhub_client.py's
docstring); a failure for one ticker (bad symbol, rate limit, request
error, from either provider) is caught locally and turned into that
ticker's error state rather than aborting the rest of the dashboard --
same per-item isolation pattern as v1's `run_ingestion`.

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
so the background check always re-fetches live rather than just
replaying a stale snapshot as if it were current. A ticker whose live
fetch fails falls back to its last stored snapshot silently (no visible
stale/live distinction, matching the Indicator Digest Page's dropped
Live/Saved badge -- see CLAUDE.md); only a ticker that has *never* been
successfully fetched renders as a genuine error.

`get_initial_market_news`/`check_for_market_news` are the same split
applied to one more thing: a page-level feed of general market
headlines, cached in `data/market_news.json` -- separate from the
per-ticker cache since it's a single item, not one per symbol. Folded
into the same `/api/check-tickers` background check as the ticker
prices rather than given its own route.

`add_ticker_to_group`/`remove_ticker_from_group` let the /tickers page
itself edit config/tickers.json -- adding or removing a ticker within
an existing group, not creating or renaming groups (that's still a
hand-edit of the file). Both read-modify-write the raw file directly
rather than going through `load_ticker_config`'s cleanup pass, so an
edit never silently drops an unrelated malformed entry elsewhere in the
file.

Redis-backed storage: Render's free tier has no persistent local disk,
so without this, the ticker config and both caches reset to empty on
every restart/redeploy/idle-spindown. `_load_raw_config`/
`_save_raw_config` (the config) and `load_ticker_state`/
`save_ticker_state`/`load_market_news_state`/`save_market_news_state`
(the two caches) each check `kv_store.is_configured()` -- true only
when `UPSTASH_REDIS_REST_URL` is set -- and route through `kv_store`
instead of the local file when it is. Local development is unaffected:
that env var is never set locally, so every one of these functions
takes the exact same local-file path they always have. On first
Redis-backed read with no `ticker_config` key yet, `_load_raw_config`
seeds it from the repo's own bundled `config/tickers.json` once, so a
fresh deploy starts with the existing watchlist rather than empty.
Config failures propagate loudly (a broken watchlist load is worse
than a broken page); a cache failure degrades to the same
empty/pending state a missing local file would produce, never taking
the page down.
"""

import json
import logging
import os
import re
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone

from finnhub_client import fetch_market_news, fetch_quote, fetch_stock_metrics
from kv_store import KvStoreError, get_json, is_configured, set_json
from yahoo_client import fetch_daily_closes

CONFIG_PATH = os.path.join(
    os.path.dirname(__file__), "..", "..", "config", "tickers.json"
)
TICKER_DATA_PATH = os.path.join(
    os.path.dirname(__file__), "..", "..", "data", "tickers.json"
)
MARKET_NEWS_PATH = os.path.join(
    os.path.dirname(__file__), "..", "..", "data", "market_news.json"
)

_TICKER_RE = re.compile(r"^[A-Za-z0-9]+$")
MA_WINDOWS = (20, 50, 200)
_SNAPSHOT_FIELDS = (
    "price", "change", "change_percent", "week52_low", "week52_high",
    "pct_off_high", "market_cap", "pe_ratio", "ma20", "ma50", "ma200",
)

_TICKER_CONFIG_KEY = "ticker_config"
_TICKER_CACHE_KEY = "ticker_cache"
_MARKET_NEWS_CACHE_KEY = "market_news_cache"

logger = logging.getLogger(__name__)


def _is_valid_ticker(symbol) -> bool:
    return isinstance(symbol, str) and bool(_TICKER_RE.match(symbol))


def load_ticker_config(path: str = CONFIG_PATH) -> dict[str, list[str]]:
    """Return `{group_name: [symbols]}` in file order.

    A malformed symbol (empty, non-alphanumeric) is skipped and logged
    rather than raising, before it ever reaches the Finnhub client --
    well-formed symbols in the same group still load.
    """
    raw = _load_raw_config(path)

    groups: dict[str, list[str]] = {}
    for group_name, symbols in raw.get("groups", {}).items():
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


class TickerConfigError(Exception):
    """Raised for an invalid add/remove request from the /tickers page's
    inline editor -- an unknown group or a malformed symbol. Distinct
    from the malformed-entry-in-the-file case in `load_ticker_config`
    (logged and skipped, not raised), since this path is driven by live
    user input from a form, where the right response is telling the
    user what's wrong, not silently dropping their edit."""


def _load_raw_config(path: str = CONFIG_PATH) -> dict:
    """The full config/tickers.json dict (not just `groups`), shared by
    `load_ticker_config` and the in-app editor. Redis-backed when
    `kv_store.is_configured()`: seeds Redis from the repo's bundled
    `path` the first time there's no `ticker_config` key yet, then
    never touches `path` again for that deployment. Any Redis failure
    here propagates -- see the module docstring.
    """
    if is_configured():
        raw = get_json(_TICKER_CONFIG_KEY)
        if raw is None:
            with open(path) as f:
                raw = json.load(f)
            set_json(_TICKER_CONFIG_KEY, raw)
        return raw

    with open(path) as f:
        return json.load(f)


def _save_raw_config(raw: dict, path: str = CONFIG_PATH) -> None:
    if is_configured():
        set_json(_TICKER_CONFIG_KEY, raw)
        return

    with open(path, "w") as f:
        json.dump(raw, f, indent=2)
        f.write("\n")


def add_ticker_to_group(symbol: str, group_name: str, path: str = CONFIG_PATH) -> None:
    """Append `symbol` to `group_name`'s ticker list in
    config/tickers.json and write the file back -- the in-app
    alternative to hand-editing that file, which remains a perfectly
    valid way to make the same edit. No-op if `symbol` is already in
    that group. Only adds to an existing group -- creating a new group
    is still a hand-edit of the file, out of scope for this editor.
    """
    symbol = symbol.strip().upper()
    if not _is_valid_ticker(symbol):
        raise TickerConfigError(f"{symbol!r} isn't a valid ticker symbol")

    raw = _load_raw_config(path)
    groups = raw.setdefault("groups", {})
    if group_name not in groups:
        raise TickerConfigError(f"unknown group: {group_name!r}")

    if symbol not in groups[group_name]:
        groups[group_name].append(symbol)
        _save_raw_config(raw, path)


def remove_ticker_from_group(symbol: str, group_name: str, path: str = CONFIG_PATH) -> None:
    """Remove `symbol` from `group_name`'s ticker list and write the
    file back. No-op if `symbol` isn't in that group."""
    raw = _load_raw_config(path)
    groups = raw.setdefault("groups", {})
    if group_name not in groups:
        raise TickerConfigError(f"unknown group: {group_name!r}")

    if symbol in groups[group_name]:
        groups[group_name] = [s for s in groups[group_name] if s != symbol]
        _save_raw_config(raw, path)


def _simple_moving_average(closes: list[float], window: int) -> float | None:
    """None if fewer than `window` closes are available (e.g. a
    recently-listed ticker) -- show what's computable, don't crash."""
    if len(closes) < window:
        return None
    return sum(closes[-window:]) / window


def _build_card(
    symbol: str,
    group_name: str,
    fetch_quote_fn,
    fetch_metrics_fn,
    fetch_closes_fn,
) -> dict:
    try:
        quote = fetch_quote_fn(symbol)
        price = quote["price"]
        metrics = fetch_metrics_fn(symbol)
        closes = fetch_closes_fn(symbol)
        ma20, ma50, ma200 = (_simple_moving_average(closes, w) for w in MA_WINDOWS)
        week52_high = metrics["high"]
        pct_off_high = (week52_high - price) / week52_high * 100 if week52_high else None
        return {
            "symbol": symbol,
            "group": group_name,
            "price": price,
            "change": quote.get("change"),
            "change_percent": quote.get("change_percent"),
            "week52_low": metrics["low"],
            "week52_high": week52_high,
            "pct_off_high": pct_off_high,
            "market_cap": metrics.get("market_cap"),
            "pe_ratio": metrics.get("pe_ratio"),
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
            "change": None,
            "change_percent": None,
            "week52_low": None,
            "week52_high": None,
            "pct_off_high": None,
            "market_cap": None,
            "pe_ratio": None,
            "ma20": None,
            "ma50": None,
            "ma200": None,
            "error": str(e),
            "pending": False,
        }


def build_ticker_cards(
    config: dict[str, list[str]] | None = None,
    fetch_quote_fn=fetch_quote,
    fetch_metrics_fn=fetch_stock_metrics,
    fetch_closes_fn=fetch_daily_closes,
    max_workers: int = 5,
) -> dict[str, list[dict]]:
    """Return `{group_name: [card, ...]}` in file order, one card per
    ticker in `config` (defaults to `load_ticker_config()`).

    Fetches every ticker concurrently (`max_workers` threads) rather
    than one at a time -- with a large watchlist, sequential fetching
    made the background check take tens of seconds. `max_workers` is
    deliberately modest rather than maxed out: Finnhub's
    free tier enforces an overall calls-per-minute rate limit, and
    firing every ticker's calls at once risks 429s, which would just
    turn into more error/stale-fallback cards than the sequential
    version had. `executor.map` preserves input order in its output, so
    the result is grouped/ordered exactly as if this were still
    sequential, regardless of which ticker's fetch finishes first.

    Each card is `{symbol, group, price, change, change_percent,
    week52_low, week52_high, pct_off_high, market_cap, pe_ratio, ma20,
    ma50, ma200, error, pending}` -- `error` is `None` on success, or a
    message with every other field left as `None` if that ticker's
    fetch failed. `market_cap`/`pe_ratio` can independently be `None`
    even on an otherwise-successful card (Finnhub doesn't always carry
    them -- see `finnhub_client.fetch_stock_metrics`). `pending`
    is always `False` here (this function only
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
            [fetch_metrics_fn] * n,
            [fetch_closes_fn] * n,
        )
        for (group_name, _symbol), card in zip(tasks, cards):
            grouped_cards[group_name].append(card)

    return grouped_cards


def load_ticker_state(path: str = TICKER_DATA_PATH) -> dict:
    """The snapshot cache: `{symbol: {price, week52_low, week52_high,
    market_cap, pe_ratio, ma20, ma50, ma200, fetched_at}}`. `{}` if
    there's nothing cached yet, the local file is corrupted, or (Redis-
    backed) Redis itself is unreachable -- this cache degrades
    gracefully rather than failing loudly the way `_load_raw_config`
    does, since losing it just means every row shows "Loading..."
    again, not an empty watchlist.
    """
    if is_configured():
        try:
            return get_json(_TICKER_CACHE_KEY) or {}
        except KvStoreError as e:
            logger.error("ticker cache read failed, degrading to empty: %s", e)
            return {}

    try:
        with open(path) as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return {}


def save_ticker_state(state: dict, path: str = TICKER_DATA_PATH) -> None:
    if is_configured():
        try:
            set_json(_TICKER_CACHE_KEY, state)
        except KvStoreError as e:
            logger.error("ticker cache write failed: %s", e)
        return

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
    fetch_metrics_fn=fetch_stock_metrics,
    fetch_closes_fn=fetch_daily_closes,
    state_path: str = TICKER_DATA_PATH,
    now: datetime | None = None,
) -> dict[str, list[dict]]:
    """The real live pull, called by the page's own background script
    after the instant stored-only render. Always re-fetches every
    ticker live -- reloading re-fetches rather than replaying a stale
    snapshot -- and persists every success back to `state_path` so the
    *next* instant render has fresher stale data to fall back on.

    A ticker whose live fetch fails is quietly replaced with its last
    stored snapshot if one exists -- no visible stale/live distinction
    (same call as the Indicator Digest Page's dropped Live/Saved
    badge). Only a ticker with no stored snapshot *and* a failed live
    fetch renders as a genuine error.
    """
    now = now or datetime.now(timezone.utc)
    config = config if config is not None else load_ticker_config()
    stored = load_ticker_state(state_path)

    live_cards = build_ticker_cards(config, fetch_quote_fn, fetch_metrics_fn, fetch_closes_fn)

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


def load_market_news_state(path: str = MARKET_NEWS_PATH) -> dict | None:
    """`{"headlines": [...], "fetched_at": ...}`, or `None` if there's
    nothing cached yet, the local file is corrupted, or (Redis-backed)
    Redis itself is unreachable -- `None` distinguished from
    `{}` deliberately, so callers can tell "never fetched" apart from
    "fetched, turned out empty". Same graceful-degradation behavior as
    `load_ticker_state`."""
    if is_configured():
        try:
            return get_json(_MARKET_NEWS_CACHE_KEY)
        except KvStoreError as e:
            logger.error("market news cache read failed, degrading to no-cache-yet: %s", e)
            return None

    try:
        with open(path) as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return None


def save_market_news_state(state: dict, path: str = MARKET_NEWS_PATH) -> None:
    if is_configured():
        try:
            set_json(_MARKET_NEWS_CACHE_KEY, state)
        except KvStoreError as e:
            logger.error("market news cache write failed: %s", e)
        return

    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w") as f:
        json.dump(state, f, indent=2)
        f.write("\n")


def get_initial_market_news(path: str = MARKET_NEWS_PATH) -> dict:
    """What "/tickers" renders for the market-news section -- instantly,
    from the local cache only, no network call. A single page-level
    feed, not per-ticker, so unlike ticker cards there's only one
    pending/not-pending state for the whole section, not one per row.
    Returns `{"headlines": [...], "pending": bool}`.
    """
    stored = load_market_news_state(path)
    if stored is None:
        return {"headlines": [], "pending": True}
    return {"headlines": stored.get("headlines", []), "pending": False}


def check_for_market_news(
    fetch_news_fn=fetch_market_news, path: str = MARKET_NEWS_PATH, now: datetime | None = None
) -> dict:
    """The real live pull for the market-news section, called alongside
    `check_for_ticker_updates` by the page's background script -- folded
    into the same `/api/check-tickers` round trip rather than given its
    own route/cache lifecycle, since there's no evidence that news needs
    to refresh on a different cadence than prices.

    On failure, falls back to the last cached headlines if any exist --
    same silent-stale-fallback behavior as `check_for_ticker_updates`.
    If there's nothing cached either, returns an empty list -- degrade
    to an empty/muted section, never take down the rest of the page.
    """
    now = now or datetime.now(timezone.utc)
    try:
        headlines = fetch_news_fn()
        save_market_news_state({"headlines": headlines, "fetched_at": now.isoformat()}, path)
        return {"headlines": headlines, "pending": False}
    except Exception as e:
        logger.error("market news fetch failed error=%s", e)
        stored = load_market_news_state(path)
        return {"headlines": stored.get("headlines", []) if stored else [], "pending": False}
