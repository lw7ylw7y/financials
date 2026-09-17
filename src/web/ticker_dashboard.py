"""Ticker Dashboard: config loading, per-ticker card assembly, and a
stored-snapshot fast-render + background-refresh split.

Redis-backed, unconditionally -- there is no local-file fallback.
`UPSTASH_REDIS_REST_URL`/`UPSTASH_REDIS_REST_TOKEN` must be set
wherever this module runs (local dev included); `kv_store.py` raises a
clear `KvStoreError` if they aren't, rather than this module silently
falling back to something else. The watchlist (`ticker_config`) and
both caches (`ticker_cache`, `market_news_cache`) live only in Redis:
a wiped or brand-new key comes back empty (an empty watchlist, or a
"nothing cached yet" cache), with no automatic reseeding. Recovering a
wiped watchlist means re-adding tickers through the in-app editor;
there is no local `config/tickers.json` this module reads from
anymore.

Config loading -- `load_ticker_config()` reads `ticker_config`'s
`groups` map -- group names are never hardcoded here or in
`page_template.py`, the dashboard renders whatever group keys are
present, in the order the config itself defines, so adding, renaming,
or removing a group is a config-only edit. For each ticker,
`build_ticker_cards` independently fetches a quote + 52-week
range/market cap/P/E from Finnhub; a failure for one ticker
(bad symbol, rate limit, request error) is
caught locally and turned into that ticker's error state rather than
aborting the rest of the dashboard -- same per-item isolation pattern
as v1's `run_ingestion`. Finnhub never has a P/E for a fund (only for
individual companies), so `_EQUITY_ETF_GROUPS` (`stocks`,
`international`, `sector` -- the fund groups, as opposed to `bonds` or
`individual`) additionally try `yahoo_client.fetch_etf_pe_ratio` as a
fallback when Finnhub's own comes back empty; a fallback failure is
just as harmless as a missing Finnhub value -- both mean the row shows
"n/a", never an error, since Yahoo's endpoint is an undocumented,
unofficial one Finnhub isn't (see yahoo_client.py's module docstring).

Beyond price/range/P/E, each individual-company ticker (any group not
in `_EQUITY_ETF_GROUPS` or `bonds` -- see `_NON_COMPANY_GROUPS`) also
gets a handful of growth/quality stats straight from the same
`fetch_stock_metrics` call (revenue growth, EPS growth, ROE, net
margin, debt/equity, dividend yield -- see
`finnhub_client.fetch_stock_metrics`'s docstring), plus a sector-peer
P/E benchmark: `_sector_benchmark` looks up the ticker's industry
(`finnhub_client.fetch_company_industry`, a new Finnhub call), maps it
to one of the configured sector-ETF tickers via
`_SECTOR_ETF_BY_INDUSTRY`, and reads that ETF's own already-cached
`pe_ratio` straight out of `ticker_cache` -- no new Yahoo/Finnhub call
for the benchmark value itself, since the sector groups already
compute it. None of this feeds the rendered table (Section 11.13's
"data only" scope) -- it exists so a future AI valuation feature has
real comparison points (peer P/E, growth, quality, leverage) instead
of judging a raw P/E number in isolation.

`get_initial_ticker_page_data`/`check_for_ticker_updates` mirror
`live_pull.py`'s split for the Indicator Digest Page: the initial page
render reads only the `ticker_cache` snapshot (one entry per ticker)
so it paints instantly regardless of how long a live fetch would take;
a ticker with no snapshot yet renders as a pending/loading placeholder.
The background check then does the real fetch and persists every
success, so the *next* load has fresher stale data to show. Unlike the
indicator pipeline, there's no "skip if nothing changed" gate here --
there's no expensive AI call to protect, so the background check
always re-fetches live rather than just replaying a stale snapshot as
if it were current. A ticker whose live fetch fails falls back to its
last stored snapshot silently (no visible stale/live distinction,
matching the Indicator Digest Page's dropped Live/Saved badge -- see
CLAUDE.md); only a ticker that has *never* been successfully fetched
renders as a genuine error.

`get_initial_market_news`/`check_for_market_news` are the same split
applied to one more thing: a page-level feed of general market
headlines, cached separately (`market_news_cache`) since it's a single
item, not one per symbol. Has its own route, checked independently of
any ticker group's own check.

`get_initial_ticker_valuation`/`check_for_ticker_valuation` are the
same split again, for a page-level AI valuation section (one Gemini
call reasoning across the whole watchlist at once --
`ticker_valuation.py` -- rather than per ticker): a discount/fair/
overpriced read per ETF group plus one per individual stock, cached
under `ticker_valuation_cache`. Unlike every other background check
here, this one is also throttled by time (`MIN_VALUATION_INTERVAL`),
not just "does it exist yet" -- Gemini's free tier cap makes refreshing
this on every page load unworkable. A throttle-skip or an outright AI
failure (including a quota 429) both fall back to whatever was last
successfully cached, the same silent-stale-fallback pattern
`check_for_ticker_updates` uses for a single ticker's price.

`add_ticker_to_group`/`remove_ticker_from_group` let the /tickers page
itself edit the watchlist -- adding or removing a ticker within an
existing group, not creating or renaming groups (that's still an
in-Redis edit nobody's built a UI for yet). Each mutates only its own
group's hash field (see `_load_raw_config`'s docstring for why the
config is shaped as a hash, not a single blob).
"""

import logging
import re
import threading
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone

from finnhub_client import (
    FinnhubApiError,
    fetch_company_industry,
    fetch_market_news,
    fetch_quote,
    fetch_stock_metrics,
)
from kv_store import KvStoreError, get_json, hdel_json, hget_json, hgetall_json, hset_json, set_json
from ticker_valuation import TickerValuationError, interpret_ticker_valuation
from yahoo_client import YahooApiError, fetch_etf_pe_ratio

_TICKER_RE = re.compile(r"^[A-Za-z0-9]+$")
_SNAPSHOT_FIELDS = (
    "price", "change", "change_percent", "week52_low", "week52_high",
    "pct_off_high", "market_cap", "pe_ratio", "peg_ratio",
    "revenue_growth", "eps_growth", "roe", "net_margin", "debt_to_equity",
    "dividend_yield", "sector_pe_ratio", "sector_symbol",
)

_TICKER_CONFIG_KEY = "ticker_config"
_TICKER_CACHE_KEY = "ticker_cache"
_MARKET_NEWS_CACHE_KEY = "market_news_cache"
_TICKER_VALUATION_CACHE_KEY = "ticker_valuation_cache"

# Gemini's free tier caps gemini-3.8-flash at 20 requests/day total
# (confirmed live via a 429 RESOURCE_EXHAUSTED during development) --
# shared with the indicator digest's own calls on the same model, so
# refreshing the valuation on every page load or background check
# (the way ticker prices themselves refresh) would burn through it
# fast. Verdicts also aren't intraday-sensitive -- fundamentals don't
# meaningfully change within a few hours -- so a coarse time-based
# throttle is enough; unlike MIN_DIGEST_INTERVAL (which only gates
# *sending* an email, reusing whatever AI response already exists),
# this one gates the AI call itself.
MIN_VALUATION_INTERVAL = timedelta(hours=6)

# The fund groups -- as opposed to `bonds` (fixed income, no equity
# P/E to speak of) or `individual` (already gets a real per-company P/E
# from Finnhub directly). Deliberately hardcoded by name, unlike every
# other group-name reference in this module (which just reads whatever
# groups the config defines): this is a fact about which groups hold
# equity funds, not a rendering detail, so a newly added fund group
# needs adding here too.
_EQUITY_ETF_GROUPS = frozenset({"stocks", "international", "sector"})

# Groups that aren't individual companies at all -- the fund groups
# above, plus `bonds` (fixed income, no industry/sector-peer notion).
# A ticker in any other group is assumed to be an individual company
# and gets a sector-peer P/E lookup attempted (`_sector_benchmark`);
# this is deliberately the inverse of an allowlist (unlike
# `_EQUITY_ETF_GROUPS`) so a newly added individual-stock group works
# without a code change, at the cost of a wasted (harmless) Finnhub
# profile lookup if a future non-equity, non-bond group ever appears.
_NON_COMPANY_GROUPS = _EQUITY_ETF_GROUPS | {"bonds"}

# Maps a Finnhub `finnhubIndustry` string (its own proprietary
# taxonomy, not a GICS sector name -- see `finnhub_client.fetch_company_industry`)
# to the ticker of a configured Fidelity MSCI sector ETF covering the
# same GICS sector, for a peer-P/E comparison. Deliberately partial: an
# industry with no entry here (or a GICS sector this watchlist doesn't
# track a fund for, e.g. Energy/Industrials/Materials) just means no
# sector benchmark is available for that ticker -- not an error, and
# not worth failing loudly over, since this table is meant to grow
# incrementally as new industries are observed in a real watchlist
# rather than trying to enumerate Finnhub's full taxonomy upfront.
_SECTOR_ETF_BY_INDUSTRY = {
    "Technology": "FTEC",
    "Semiconductors": "FTEC",
    "Software": "FTEC",
    "Computer Hardware": "FTEC",
    "IT Services": "FTEC",
    "Media": "FCOM",
    "Communications": "FCOM",
    "Telecommunications Equipment": "FCOM",
    "Retail": "FDIS",
    "Automobiles": "FDIS",
    "Leisure Products": "FDIS",
    "Hotels, Restaurants & Leisure": "FDIS",
    "Food Products": "FSTA",
    "Beverages": "FSTA",
    "Household Products": "FSTA",
    "Packaged Foods": "FSTA",
    "Healthcare": "FHLC",
    "Biotechnology": "FHLC",
    "Pharmaceuticals": "FHLC",
    "Medical Devices & Instruments": "FHLC",
    "Financial Services": "FNCL",
    "Banking": "FNCL",
    "Insurance": "FNCL",
    "Capital Markets": "FNCL",
    "Real Estate": "FREL",
    "REIT": "FREL",
    "Utilities": "FUTY",
}

logger = logging.getLogger(__name__)

# Caps how many tickers' quote/metrics fetches run at once
# GLOBALLY, across every concurrent call to build_ticker_cards, not
# just within one -- build_ticker_cards's own max_workers only bounds
# concurrency *inside a single call*, so without this, the page firing
# one call per group concurrently could otherwise reach
# group_count * max_workers simultaneous Finnhub fetches instead
# of staying capped at a known ceiling.
#
# Set well above what any single page load actually needs (today's 5
# config groups sum to at most 3+3+5+5+5=21 concurrent fetches if every
# group's own pool were maxed out at once) rather than matched tightly
# to it, after confirming empirically that the tight cap (5) was itself
# the bottleneck: 36 real tickers fetched at
# max_workers=20 against the live APIs completed in ~2s with zero
# errors -- Finnhub's free tier tolerates this level of concurrency
# fine, so throttling this hard was solving a problem that measurement
# didn't actually confirm existed at the API level. Revisit only if a
# real 429 (not just latency) shows up in logs, or the watchlist grows
# enough groups that the natural per-group sum starts approaching this.
_fetch_concurrency_limit = threading.Semaphore(25)


def _is_valid_ticker(symbol) -> bool:
    return isinstance(symbol, str) and bool(_TICKER_RE.match(symbol))


def load_ticker_config() -> dict[str, list[str]]:
    """Return `{group_name: [symbols]}` in config order.

    A malformed symbol (empty, non-alphanumeric) is skipped and logged
    rather than raising, before it ever reaches the Finnhub client --
    well-formed symbols in the same group still load.
    """
    raw = _load_raw_config()

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
    from the malformed-entry-in-the-config case in `load_ticker_config`
    (logged and skipped, not raised), since this path is driven by live
    user input from a form, where the right response is telling the
    user what's wrong, not silently dropping their edit."""


def _load_raw_config() -> dict:
    """The full config dict (not just `groups`), shared by
    `load_ticker_config` and the in-app editor. A Redis failure here
    propagates -- see the module docstring; a broken watchlist load is
    worse than a broken page.

    `ticker_config` is a Redis *hash* -- one field per group, each
    `{"symbols": [...], "order": i}` -- not a single JSON-blob string,
    so `add_ticker_to_group`/`remove_ticker_from_group` can mutate one
    group's field atomically without reading or rewriting any other
    group's. Redis hash fields don't preserve insertion order on read
    (confirmed live: HGETALL came back alphabetized, not in the order
    fields were written), which would otherwise break "groups render
    in a stable order" -- the embedded `order` index is what actually
    restores it here, by explicit sort rather than relying on Redis's
    own field ordering.
    """
    hash_value = hgetall_json(_TICKER_CONFIG_KEY)
    ordered = sorted(hash_value.items(), key=lambda item: item[1]["order"])
    return {"groups": {group_name: value["symbols"] for group_name, value in ordered}}


def add_ticker_to_group(symbol: str, group_name: str) -> None:
    """Append `symbol` to `group_name`'s ticker list -- the in-app
    alternative to editing the watchlist directly in Redis. No-op if
    `symbol` is already in that group. Only adds to an existing group
    -- creating a new group is out of scope for this editor.

    Reads and writes only `group_name`'s own hash field
    (`hget_json`/`hset_json`) -- never every other group's data, so
    two edits to different groups (or the same group, from two tabs)
    can't clobber each other's unrelated fields the way loading the
    whole config, mutating it, and saving it all back would.
    """
    symbol = symbol.strip().upper()
    if not _is_valid_ticker(symbol):
        raise TickerConfigError(f"{symbol!r} isn't a valid ticker symbol")

    group = hget_json(_TICKER_CONFIG_KEY, group_name)
    if group is None:
        raise TickerConfigError(f"unknown group: {group_name!r}")

    if symbol not in group["symbols"]:
        group["symbols"].append(symbol)
        hset_json(_TICKER_CONFIG_KEY, group_name, group)


def remove_ticker_from_group(symbol: str, group_name: str) -> None:
    """Remove `symbol` from `group_name`'s ticker list. No-op if
    `symbol` isn't in that group. Scoped to `group_name`'s own hash
    field only -- see `add_ticker_to_group`.

    Once removed from this group, also deletes `symbol`'s cached
    snapshot (`delete_ticker_snapshot`) -- but only if it isn't still
    used by some *other* group (the same symbol can legitimately
    appear in more than one), checked via a fresh `load_ticker_config`
    read after the removal. Without this, a removed ticker's stale
    price data would linger in the cache forever: it'd never be shown
    again (nothing in the config references it), but it'd keep taking
    up space and never get cleaned up on its own.
    """
    group = hget_json(_TICKER_CONFIG_KEY, group_name)
    if group is None:
        raise TickerConfigError(f"unknown group: {group_name!r}")

    if symbol in group["symbols"]:
        group["symbols"] = [s for s in group["symbols"] if s != symbol]
        hset_json(_TICKER_CONFIG_KEY, group_name, group)
        if not _symbol_in_any_group(symbol, load_ticker_config()):
            delete_ticker_snapshot(symbol)


def _symbol_in_any_group(symbol: str, config: dict[str, list[str]]) -> bool:
    return any(symbol in symbols for symbols in config.values())


def _fallback_etf_pe_ratio(symbol: str, group_name: str, fetch_etf_pe_fn) -> float | None:
    """Best-effort only: Yahoo's undocumented crumb gate can fail or
    change shape at any time, and that must never take down a card
    whose price/range already loaded fine from Finnhub -- so a failure
    here just means the row keeps showing "n/a" for P/E, same as if
    Finnhub itself had nothing.
    """
    if group_name not in _EQUITY_ETF_GROUPS:
        return None
    try:
        return fetch_etf_pe_fn(symbol)
    except YahooApiError as e:
        logger.warning("ETF aggregate P/E fetch failed symbol=%s error=%s", symbol, e)
        return None


def _sector_benchmark(symbol: str, group_name: str, fetch_industry_fn) -> tuple[float | None, str | None]:
    """A peer-comparison P/E for `symbol`, if it's plausibly an
    individual company (`group_name` not in `_NON_COMPANY_GROUPS`) and
    its industry maps to one of the sector ETFs this watchlist already
    tracks. Returns `(sector_pe_ratio, sector_symbol)`, both `None` if
    no benchmark is available -- an ETF/bond ticker, an industry
    `_SECTOR_ETF_BY_INDUSTRY` doesn't recognize, or a genuine failure
    (Finnhub or Redis) fetching either piece. Never raises: this is
    extra context for a future AI feature, not core card data, so it
    must never take down a card whose price/range already succeeded.

    Deliberately reads the sector ETF's `pe_ratio` straight out of
    `ticker_cache` (whatever was last fetched for it, possibly stale)
    rather than fetching it fresh here -- the sector groups already
    compute this value on their own schedule, so re-fetching it again
    per individual stock would be redundant work for no real freshness
    gain, and would need its own Yahoo-fallback logic duplicated here.
    """
    if group_name in _NON_COMPANY_GROUPS:
        return None, None
    try:
        industry = fetch_industry_fn(symbol)
        sector_symbol = _SECTOR_ETF_BY_INDUSTRY.get(industry)
        if sector_symbol is None:
            return None, None
        sector_snapshot = hget_json(_TICKER_CACHE_KEY, sector_symbol)
        sector_pe_ratio = sector_snapshot.get("pe_ratio") if sector_snapshot else None
        return sector_pe_ratio, sector_symbol
    except (FinnhubApiError, KvStoreError) as e:
        logger.warning("sector benchmark lookup failed symbol=%s error=%s", symbol, e)
        return None, None


def _build_card(
    symbol: str,
    group_name: str,
    fetch_quote_fn,
    fetch_metrics_fn,
    fetch_etf_pe_fn,
    fetch_industry_fn,
) -> dict:
    with _fetch_concurrency_limit:
        try:
            quote = fetch_quote_fn(symbol)
            price = quote["price"]
            metrics = fetch_metrics_fn(symbol)
            week52_high = metrics["high"]
            pct_off_high = (week52_high - price) / week52_high * 100 if week52_high else None
            pe_ratio = metrics.get("pe_ratio")
            if pe_ratio is None:
                pe_ratio = _fallback_etf_pe_ratio(symbol, group_name, fetch_etf_pe_fn)
            sector_pe_ratio, sector_symbol = _sector_benchmark(symbol, group_name, fetch_industry_fn)
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
                "pe_ratio": pe_ratio,
                "peg_ratio": metrics.get("peg_ratio"),
                "revenue_growth": metrics.get("revenue_growth"),
                "eps_growth": metrics.get("eps_growth"),
                "roe": metrics.get("roe"),
                "net_margin": metrics.get("net_margin"),
                "debt_to_equity": metrics.get("debt_to_equity"),
                "dividend_yield": metrics.get("dividend_yield"),
                "sector_pe_ratio": sector_pe_ratio,
                "sector_symbol": sector_symbol,
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
                "peg_ratio": None,
                "revenue_growth": None,
                "eps_growth": None,
                "roe": None,
                "net_margin": None,
                "debt_to_equity": None,
                "dividend_yield": None,
                "sector_pe_ratio": None,
                "sector_symbol": None,
                "error": str(e),
                "pending": False,
            }


def build_ticker_cards(
    config: dict[str, list[str]] | None = None,
    fetch_quote_fn=fetch_quote,
    fetch_metrics_fn=fetch_stock_metrics,
    fetch_etf_pe_fn=fetch_etf_pe_ratio,
    fetch_industry_fn=fetch_company_industry,
    max_workers: int = 5,
) -> dict[str, list[dict]]:
    """Return `{group_name: [card, ...]}` in config order, one card per
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
    week52_low, week52_high, pct_off_high, market_cap, pe_ratio,
    peg_ratio, revenue_growth, eps_growth, roe, net_margin,
    debt_to_equity, dividend_yield, sector_pe_ratio, sector_symbol,
    error, pending}` -- `error` is `None` on success, or a message with
    every other field left as `None` if that ticker's fetch failed.
    `market_cap`/`pe_ratio`/`peg_ratio` can independently be `None`
    even on an otherwise-successful card (Finnhub doesn't
    always carry them -- see `finnhub_client.fetch_stock_metrics`, and
    never carries any of the three for an ETF); for a ticker in
    `_EQUITY_ETF_GROUPS`, a `None` Finnhub `pe_ratio` additionally tries
    `fetch_etf_pe_fn` (Yahoo's aggregate holdings P/E) before settling
    on `None` for real -- see `_fallback_etf_pe_ratio`. There is no
    equivalent fallback for `peg_ratio`: Yahoo's own aggregate-holdings
    module has no PEG field for a fund, only P/E, P/B, P/S, and P/CF,
    so an ETF's PEG is always `None`.

    `revenue_growth`/`eps_growth`/`roe`/`net_margin`/`debt_to_equity`/
    `dividend_yield` are the same growth/quality fields
    `fetch_stock_metrics` returns -- no new fetch, same degrade-to-`None`
    behavior. `sector_pe_ratio`/`sector_symbol` come from
    `_sector_benchmark` (Finnhub's `fetch_industry_fn`, mapped to a
    configured sector ETF, whose own cached `pe_ratio` is read from
    `ticker_cache`) -- both `None` for any ticker in
    `_NON_COMPANY_GROUPS`, an unmapped industry, or a lookup failure.
    None of these eight fields are rendered anywhere yet (see
    `page_template.py`) -- they exist as inputs for a future AI
    valuation feature, not the current table.

    `pending` is always `False` here (this function only
    ever returns the result of an attempted fetch); see
    `get_initial_ticker_page_data` for the stored-only, not-yet-fetched
    case. One ticker's failure never affects the others.
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
            [fetch_etf_pe_fn] * n,
            [fetch_industry_fn] * n,
        )
        for (group_name, _symbol), card in zip(tasks, cards):
            grouped_cards[group_name].append(card)

    return grouped_cards


def load_ticker_state() -> dict:
    """The snapshot cache: `{symbol: {price, week52_low, week52_high,
    market_cap, pe_ratio, peg_ratio, revenue_growth, eps_growth, roe,
    net_margin, debt_to_equity, dividend_yield, sector_pe_ratio,
    sector_symbol, fetched_at}}`. `{}` if
    there's nothing cached yet or Redis itself is unreachable -- this
    cache degrades gracefully rather than failing loudly the way
    `_load_raw_config` does, since losing it just means every row
    shows "Loading..." again, not an empty watchlist.

    Reads the whole `ticker_cache` hash (one field per symbol, see
    `save_ticker_snapshot`) in a single HGETALL -- a read never
    conflicts with anything, so no lock is involved.
    """
    try:
        return hgetall_json(_TICKER_CACHE_KEY)
    except KvStoreError as e:
        logger.error("ticker cache read failed, degrading to empty: %s", e)
        return {}


def save_ticker_state(state: dict) -> None:
    """Bulk-write every symbol in `state` as its own hash field --
    useful for seeding/tests, not the normal per-ticker write path.
    Prefer `save_ticker_snapshot` for persisting the result of one
    fresh fetch: unlike this function, it never has to touch every
    other symbol's data just to write one. Fans out into one HSET per
    symbol so the resulting hash stays consistent with
    `save_ticker_snapshot`'s per-field writes -- not a single atomic
    operation across the whole dict, which is fine here since nothing
    calls this concurrently with itself.
    """
    for symbol, snapshot in state.items():
        try:
            hset_json(_TICKER_CACHE_KEY, symbol, snapshot)
        except KvStoreError as e:
            logger.error("ticker cache write failed symbol=%s: %s", symbol, e)


def save_ticker_snapshot(symbol: str, snapshot: dict) -> None:
    """Persists exactly one ticker's fresh snapshot. This is what
    `check_for_ticker_updates` calls per successfully-fetched ticker,
    instead of loading the *entire* cache, merging every group's
    results into it in memory, and writing the whole thing back --
    that raced badly once the ticker page started firing one
    concurrent live-check per group (Story 12): two groups' checks
    could both load the cache before either saved, and the second save
    would silently wipe out the first group's fresh values. Worse, that
    race isn't limited to one process -- any number of concurrent users
    hitting a hosted deployment hit the same shared cache, so a lock
    (which only ever protects one process's own memory) could never
    actually fix it.

    Each symbol is its own hash field (`HSET`) -- an atomic per-field
    write that never reads or touches any other field, so concurrent
    writes to *different* symbols (any number of groups, any number of
    users, any number of gunicorn worker processes) can never clobber
    each other's data, and even two writes to the *same* symbol just
    leave whichever landed last, never a torn mix of two updates. No
    lock needed at all.
    """
    try:
        hset_json(_TICKER_CACHE_KEY, symbol, snapshot)
    except KvStoreError as e:
        logger.error("ticker snapshot write failed symbol=%s: %s", symbol, e)


def delete_ticker_snapshot(symbol: str) -> None:
    """Removes one ticker's cached snapshot entirely. Called by
    `remove_ticker_from_group` once a symbol is no longer in *any*
    watchlist group, so a removed ticker's stale price data doesn't
    linger in the cache forever -- it would never be displayed again
    (nothing in the config would reference it), but it'd sit there
    taking up space indefinitely otherwise. A no-op if the symbol has
    no cached snapshot to begin with.

    One atomic `HDEL` on the symbol's own hash field -- doesn't touch
    any other symbol's data, same reasoning as `save_ticker_snapshot`.
    """
    try:
        hdel_json(_TICKER_CACHE_KEY, symbol)
    except KvStoreError as e:
        logger.error("ticker snapshot delete failed symbol=%s: %s", symbol, e)


def _pending_card(symbol: str, group_name: str) -> dict:
    card = {field: None for field in _SNAPSHOT_FIELDS}
    card.update(symbol=symbol, group=group_name, error=None, pending=True)
    return card


def _card_from_snapshot(symbol: str, group_name: str, snapshot: dict) -> dict:
    card = {field: snapshot.get(field) for field in _SNAPSHOT_FIELDS}
    card.update(symbol=symbol, group=group_name, error=None, pending=False)
    return card


def get_initial_ticker_page_data(config: dict[str, list[str]] | None = None) -> dict[str, list[dict]]:
    """What "/tickers" renders -- instantly, from the snapshot cache
    only, no network calls. A ticker with no cached snapshot yet
    (first-ever run, or just added to the config) renders as a pending
    placeholder rather than an error -- it hasn't failed, it just
    hasn't been fetched yet; the page's own script then calls each
    group's own /api/tickers/groups/<name>/check to fetch for real.
    """
    config = config if config is not None else load_ticker_config()
    stored = load_ticker_state()

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
    fetch_etf_pe_fn=fetch_etf_pe_ratio,
    fetch_industry_fn=fetch_company_industry,
    now: datetime | None = None,
) -> dict[str, list[dict]]:
    """The real live pull, called by the page's own background script
    after the instant stored-only render. Always re-fetches every
    ticker live -- reloading re-fetches rather than replaying a stale
    snapshot -- and persists every success so the *next* instant
    render has fresher stale data to fall back on.

    A ticker whose live fetch fails is quietly replaced with its last
    stored snapshot if one exists -- no visible stale/live distinction
    (same call as the Indicator Digest Page's dropped Live/Saved
    badge). Only a ticker with no stored snapshot *and* a failed live
    fetch renders as a genuine error.

    The page's background script calls this once per group
    concurrently (see app.py's /api/tickers/groups/<name>/check).
    Every successfully-fetched ticker is persisted immediately via
    `save_ticker_snapshot` -- one independent write per symbol, not a
    load-the-whole-cache-then-save-it-all-back cycle -- so concurrent
    groups (or concurrent users, on a hosted deployment) can never
    clobber each other's fresh data no matter how many are running at
    once. The stored cache is only *read* here, once, and only if some
    ticker's live fetch failed and needs a fallback value -- a read
    never conflicts with anything, so no locking is involved either.
    """
    now = now or datetime.now(timezone.utc)
    config = config if config is not None else load_ticker_config()

    live_cards = build_ticker_cards(config, fetch_quote_fn, fetch_metrics_fn, fetch_etf_pe_fn, fetch_industry_fn)

    stored = None  # lazily loaded only if a fallback lookup is actually needed
    grouped_cards = {}
    for group_name, cards in live_cards.items():
        resolved = []
        for card in cards:
            if card["error"] is None:
                snapshot = {
                    **{field: card[field] for field in _SNAPSHOT_FIELDS},
                    "fetched_at": now.isoformat(),
                }
                save_ticker_snapshot(card["symbol"], snapshot)
                resolved.append(card)
            else:
                if stored is None:
                    stored = load_ticker_state()
                if card["symbol"] in stored:
                    resolved.append(_card_from_snapshot(card["symbol"], group_name, stored[card["symbol"]]))
                else:
                    resolved.append(card)
        grouped_cards[group_name] = resolved

    return grouped_cards


def load_market_news_state() -> dict | None:
    """`{"headlines": [...], "fetched_at": ...}`, or `None` if there's
    nothing cached yet or Redis itself is unreachable -- `None`
    distinguished from `{}` deliberately, so callers can tell "never
    fetched" apart from "fetched, turned out empty". Same
    graceful-degradation behavior as `load_ticker_state`."""
    try:
        return get_json(_MARKET_NEWS_CACHE_KEY)
    except KvStoreError as e:
        logger.error("market news cache read failed, degrading to no-cache-yet: %s", e)
        return None


def save_market_news_state(state: dict) -> None:
    try:
        set_json(_MARKET_NEWS_CACHE_KEY, state)
    except KvStoreError as e:
        logger.error("market news cache write failed: %s", e)


def get_initial_market_news() -> dict:
    """What "/tickers" renders for the market-news section -- instantly,
    from the cache only, no network call. A single page-level feed,
    not per-ticker, so unlike ticker cards there's only one
    pending/not-pending state for the whole section, not one per row.
    Returns `{"headlines": [...], "pending": bool}`.
    """
    stored = load_market_news_state()
    if stored is None:
        return {"headlines": [], "pending": True}
    return {"headlines": stored.get("headlines", []), "pending": False}


def check_for_market_news(fetch_news_fn=fetch_market_news, now: datetime | None = None) -> dict:
    """The real live pull for the market-news section, called by its own
    route (/api/market-news/check) independently of any ticker group's
    own check, since there's no evidence that news needs to refresh on
    a different cadence than prices -- it's just not worth coupling
    them together.

    On failure, falls back to the last cached headlines if any exist --
    same silent-stale-fallback behavior as `check_for_ticker_updates`.
    If there's nothing cached either, returns an empty list -- degrade
    to an empty/muted section, never take down the rest of the page.
    """
    now = now or datetime.now(timezone.utc)
    try:
        headlines = fetch_news_fn()
        save_market_news_state({"headlines": headlines, "fetched_at": now.isoformat()})
        return {"headlines": headlines, "pending": False}
    except Exception as e:
        logger.error("market news fetch failed error=%s", e)
        stored = load_market_news_state()
        return {"headlines": stored.get("headlines", []) if stored else [], "pending": False}


def load_ticker_valuation() -> dict | None:
    """The cached AI valuation: `{"overview", "groups",
    "individual_by_verdict", "generated_at"}`, or `None` if nothing's
    ever been generated, or Redis itself is unreachable -- degrades
    the same way `load_market_news_state` does, since losing this just
    means the section shows as pending again, not an error.
    """
    try:
        return get_json(_TICKER_VALUATION_CACHE_KEY)
    except KvStoreError as e:
        logger.error("ticker valuation cache read failed, degrading to no-cache-yet: %s", e)
        return None


def save_ticker_valuation(data: dict) -> None:
    try:
        set_json(_TICKER_VALUATION_CACHE_KEY, data)
    except KvStoreError as e:
        logger.error("ticker valuation cache write failed: %s", e)


def _build_valuation_cards(config: dict[str, list[str]], stored: dict[str, dict]) -> dict[str, list[dict]]:
    """Reshapes `ticker_cache` snapshots into the `{group: [card, ...]}`
    shape `ticker_valuation.py` expects: one dict per symbol with
    `symbol` attached (a snapshot in `stored` is keyed by symbol, not
    carrying it as its own field) plus whatever `_SNAPSHOT_FIELDS` it
    already has. A symbol with no snapshot yet is skipped entirely --
    there's nothing useful to tell the AI about it, unlike a pending
    table row which still needs a placeholder to render.
    """
    return {
        group_name: [{"symbol": symbol, **stored[symbol]} for symbol in symbols if symbol in stored]
        for group_name, symbols in config.items()
    }


def get_initial_ticker_valuation() -> dict:
    """What "/tickers" renders for the AI valuation section --
    instantly, from the cache only, no network or Gemini call. Returns
    the cached blob plus `pending: False`, or a pending placeholder if
    nothing's ever been generated yet.
    """
    stored = load_ticker_valuation()
    if stored is None:
        return {"overview": None, "groups": [], "individual_by_verdict": {}, "pending": True}
    return {**stored, "pending": False}


def check_for_ticker_valuation(
    now: datetime | None = None,
    interpret_fn=interpret_ticker_valuation,
    config: dict[str, list[str]] | None = None,
) -> dict:
    """The real AI valuation call, throttled by `MIN_VALUATION_INTERVAL`
    rather than re-run on every page load/background check the way
    ticker prices themselves are -- see that constant's docstring for
    why. Within the throttle window, returns the cached valuation
    unchanged without calling Gemini at all.

    Built from the already-cached `ticker_cache` snapshots
    (`load_ticker_state`), not a fresh live fetch -- a valuation
    doesn't need millisecond-fresh prices, and re-fetching every
    ticker again here would double the Finnhub/Yahoo traffic a page
    load already costs, for no real benefit.

    On any failure -- including a Gemini quota/429, the free tier's
    real failure mode in practice (confirmed live during development)
    -- falls back to the last cached valuation, exactly like
    `check_for_ticker_updates` falls back to a ticker's last snapshot:
    the page keeps showing a stale-but-valid AI read rather than an
    error or a blank section. If nothing has ever been generated
    successfully, degrades to the same pending placeholder
    `get_initial_ticker_valuation` returns.
    """
    now = now or datetime.now(timezone.utc)
    cached = load_ticker_valuation()

    if cached is not None:
        generated_at = datetime.fromisoformat(cached["generated_at"])
        if now - generated_at < MIN_VALUATION_INTERVAL:
            return {**cached, "pending": False}

    try:
        config = config if config is not None else load_ticker_config()
        cards_by_group = _build_valuation_cards(config, load_ticker_state())
        result = interpret_fn(cards_by_group)
        result["generated_at"] = now.isoformat()
        save_ticker_valuation(result)
        return {**result, "pending": False}
    except TickerValuationError as e:
        logger.error("ticker valuation failed error=%s", e)
        if cached is not None:
            return {**cached, "pending": False}
        return {"overview": None, "groups": [], "individual_by_verdict": {}, "pending": True}
