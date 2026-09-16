# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this is

A single-user investment-monitoring tool, replacing a manual Fidelity-website
+ Google-Sheet workflow. Not a general product — there's one owner/user
(`docs/investment_dashboard_requirements.md` Section 2). v1 (shipped): a
scheduled email digest of 8 macro indicators with AI commentary. v2 (in
progress): a local Flask web dashboard mirroring that content, plus a
Ticker Dashboard sourced from Finnhub + Yahoo Finance, with a shared nav
linking the two pages. Full spec lives in `docs/`:
`investment_dashboard_requirements.md` (product requirements, both v1 and
v2), `v1_user_stories.md`/`v1_technical_design.md`/`v1_task_breakdown.md`
(v1), `v2_user_stories.md`/`v2_technical_design.md`/`v2_task_breakdown.md`
(v2).

## Commands

```
python3 -m unittest discover -s tests -v      # full suite
python3 -m unittest tests.test_page_template -v                                   # one file
python3 -m unittest tests.test_page_template.TestRenderIndicatorDigestPage.test_renders_table_rows  # one test
```

No lint/build/format tooling is configured — there's nothing else to run.

Use `python3`, not `python` (not on PATH in this environment).

```
python3 src/main.py       # v1: run ingestion + release-calendar refresh + (throttled) digest email — what the scheduled GitHub Action runs
python3 src/backfill.py   # one-time manual seed of sparse indicator history; not part of the scheduled run, safe to re-run
```

Run the v2 web dashboard locally:
```
set -a && source .env && set +a && python3 src/web/app.py
```
Then open `http://127.0.0.1:5000/` (binds to loopback only). If a previous
run is still holding port 5000, find and kill it before restarting —
`lsof -ti:5000 -sTCP:LISTEN | xargs -r kill` — the Flask dev server can be
left running in the background across sessions and silently serve stale code
otherwise.

## Environment / secrets

Read via `os.environ.get(...)` everywhere (`fetch_fred.py`, `interpret.py`,
`send_email.py`, `finnhub_client.py`) — no secrets-loading library is used,
and nothing auto-loads `.env`; export the vars yourself (or `set -a &&
source .env && set +a`) before running anything that needs them.
`yahoo_client.py` needs no key at all — it's an unauthenticated public endpoint.

| Var | Required for |
|---|---|
| `FRED_API_KEY` | any ingestion (Stories 1-3) |
| `GEMINI_API_KEY` | AI interpretation — optional; both the email and the web page degrade gracefully (no AI section) without it |
| `GMAIL_ADDRESS`, `GMAIL_APP_PASSWORD`, `RECIPIENT_EMAIL` | sending the digest email |
| `FINNHUB_API_KEY` | the Ticker Dashboard's per-ticker quote/52wk-range/market-cap/P-E fetch and the market-news feed — without it, the background check's live fetch fails for every ticker and for market news, each falling back to its own cached data (`data/tickers.json`/`data/market_news.json`) where a cache exists, or an error/unavailable state where none does; Story 2's config loading needs no API key |
| `DASHBOARD_USERNAME`, `DASHBOARD_PASSWORD` | HTTP Basic Auth in front of every `src/web/app.py` route (Story 8) — set on a hosted deployment; both unset (the local-dev default) leaves auth off entirely, unchanged from before Story 8 |
| `UPSTASH_REDIS_REST_URL`, `UPSTASH_REDIS_REST_TOKEN` | Redis-backed persistence for `config/tickers.json`/`data/tickers.json`/`data/market_news.json` (Story 9) and `data/indicators.json` (Story 11) on a hosted deployment — `UPSTASH_REDIS_REST_URL` unset (the local-dev default) leaves every one of those on the local JSON files, unchanged from before either story. Needed in **two separate places**: Render's env vars (the web app) and GitHub Actions' repo secrets (the scheduled workflow, `python3 src/main.py`) — as of Story 11 the workflow has no local file to fall back to when hosted the way it briefly did, so missing secrets there fail the whole run, not just degrade a page |

## Architecture

### One pipeline, two product surfaces
v1 (email) and v2 (web page) are built from the same modules — nothing is
duplicated between them:

```
src/
  fred/     fetch_fred.py (FRED API client), indicators_config.py (the 8 tracked
            indicators + their FRED series/release IDs — the source of truth for
            "what indicators exist")
  storage/  storage.py — persistence for data/indicators.json:
            load_state/save_state/query_history/trim_history.
            load_state/save_state are Redis-backed (via web/kv_store.py)
            when UPSTASH_REDIS_REST_URL is set, else the local JSON file
            — Story 11, same switch ticker_dashboard.py's storage
            functions already use. A Redis failure here propagates
            rather than degrading (indicator state is core data, not a
            cache)
  digest/   build_digest_content.py — SHARED table/countdown/AI-assembly logic,
            called by both the email and the web page (single source of truth
            for "what does the digest contain")
            post_release.py — refresh_ai_response_if_updated() (every
            ingestion cycle with new data, no throttle — Story 11) and
            maybe_send_digest_email() (the weekly-rollup send, gated on
            a content fingerprint + interval, never calls Gemini itself)
            interpret.py — the Gemini call; heuristics.py — Sahm Rule / yield-curve
            inversion streak, fed into the AI prompt
  mailer/   email_template.py, send_email.py, sparkline.py (matplotlib PNG —
            Gmail strips inline <svg>, so the email needs a raster image
            embedded via Content-ID; the web page instead renders sparklines
            as plain inline SVG, since browsers don't have that limitation)
  web/      app.py (Flask routes: GET "/", GET "/tickers", GET "/api/check",
            GET "/api/tickers/groups/<name>/check", GET "/api/market-news/check",
            POST "/api/tickers/add", POST "/api/tickers/remove";
            _require_auth() before_request hook gates every route behind HTTP Basic Auth when
            DASHBOARD_USERNAME/PASSWORD are both set, no-op otherwise
            — Story 8), live_pull.py (stored-only render +
            gated background live-check for the Indicator Digest Page),
            page_template.py (HTML string rendering for both pages,
            mirrors email_template.py's plain-string-building
            convention — no templating engine; also renders the shared
            _render_nav() linking the two pages, the click-to-sort
            ticker-table headers, and the inline ticker-editor controls),
            ticker_dashboard.py (load_ticker_config() reads
            config/tickers.json's groups as an open map in file order,
            skips malformed symbols; build_ticker_cards() does the
            per-ticker quote/52wk-range/market-cap/P-E/change fetch
            from Finnhub plus daily closes from Yahoo for the
            20d/50d/200d SMA and pct_off_high, with a per-ticker
            try/except so one bad
            symbol can't take down the rest; get_initial_ticker_page_data()
            /check_for_ticker_updates() and get_initial_market_news()/
            check_for_market_news() are the stored-render/live-check
            splits, backed by load_ticker_state()/save_ticker_state()
            (data/tickers.json) and load_market_news_state()/
            save_market_news_state() (data/market_news.json);
            check_for_ticker_updates() takes an optional `config` subset
            (defaults to every group) so app.py can call it once per
            group concurrently rather than fetching the whole watchlist
            in one request — its load-merge-save of the shared
            data/tickers.json cache is wrapped in `_ticker_state_lock`
            (held only around that merge/save, not the network fetch)
            so concurrent per-group calls can't clobber each other's
            freshly-fetched values;
            add_ticker_to_group()/remove_ticker_from_group()
            read-modify-write config/tickers.json for the in-app
            editor, tickers only — not group create/rename/remove),
            finnhub_client.py (quote/52wk-range+market-cap+P-E
            (fetch_stock_metrics)/general-news REST wrapper, raises
            FinnhubApiError per-call — NOT candles: see
            its docstring, Finnhub's free tier blocks `/stock/candle`
            outright), yahoo_client.py (daily closes
            from Yahoo's public chart endpoint, no API key — the only
            source for moving averages; raises YahooApiError per-call),
            kv_store.py (Upstash Redis REST wrapper -- get_json/set_json,
            raises KvStoreError per-call; is_configured() is the switch
            ticker_dashboard.py's config/cache load+save functions check
            to route through this instead of a local file — Story 9)
  main.py       v1 entrypoint: run_ingestion + update_release_calendar +
                refresh_ai_response_if_updated + maybe_send_digest_email
                — what the scheduled workflow calls (Story 11: the
                first three of those run every cycle; only the digest
                send is throttled)
  backfill.py   one-time manual seed of sparse history
```

### Data flow
1. `main.run_ingestion(state)` fetches each indicator from FRED and appends a
   new `history` entry **only if the observation date is strictly newer**
   than what's stored — dedup by date, history is append-only and never
   overwritten (Story 2's core invariant). `storage.trim_history` then drops
   anything older than a rolling 12-month window.
2. `main.update_release_calendar(state)` refreshes `next_release_date` per
   indicator (skipped for indicators with no `fred_release_id` — e.g. the
   yield curve spread and Fed Funds Rate, whose nominal FRED release doesn't
   reflect their own update cadence).
3. `digest/build_digest_content.py:build_digest_content()` is the single
   entry point both surfaces call: builds `indicators_context` (each
   indicator's 12-reading window + any precomputed heuristic), `table`
   (grouped `leading`/`coincident`/`lagging`, per `email_template.CATEGORY_ORDER`),
   `countdown`, and calls `interpret.interpret()` for the AI summary +
   directional read — persisting a successful result to
   `state["last_ai_response"]`, so the web page's initial render has
   something to show without making a live call.
4. Email path: `main.py` calls `post_release.refresh_ai_response_if_updated()`
   every scheduled run that found new data — this is what actually calls
   step 3 for the scheduled workflow, no throttle (Story 11). Separately,
   `post_release.maybe_send_digest_email()` decides whether to send —
   gated on a content fingerprint (every indicator's latest value/date +
   the AI's `directional_read`, hashed) differing from what was last
   emailed, AND `MIN_DIGEST_INTERVAL` (7 days) having elapsed. It never
   calls Gemini itself (no `interpret_fn` param exists on it) — only
   reuses whatever's currently in `state["last_ai_response"]`, however
   recently that was refreshed — then calls `send_email.send_email()`.
5. Web path: `web/live_pull.py` splits into `get_initial_page_data()`
   (stored-only, no network — instant render) and `check_for_updates()` (the
   real live pull via `main.run_ingestion`, gated: skips the calendar
   refresh/AI call/`save_state()` entirely unless at least one indicator's
   status is `"updated"` — so the common "nothing new" case costs a FRED call
   but never a Gemini call). The page's own inline `<script>` calls
   `/api/check` right after load and patches `#table-section`/
   `#countdown-section`/`#ai-section` in place only if `data_updated` is true.
   This path's own `interpret()` call is deliberately left as-is (Story 11)
   even after step 4 above started refreshing the AI response independently
   — a live visitor can still see a take fresher than the last scheduled
   cycle. As of Story 11, its `save_state()` call lands in the same
   Redis-backed state the scheduled workflow uses (when configured), so
   that result is no longer thrown away on a hosted deployment's next
   restart the way it used to be.
6. Ticker path: `web/ticker_dashboard.py` splits the same way —
   `get_initial_ticker_page_data()` (stored-only, reads `data/tickers.json`)
   and `check_for_ticker_updates()` (the real live pull via
   `build_ticker_cards()`, always re-fetches every ticker — no
   "nothing changed" gate, since there's no expensive AI call to
   protect here). A ticker whose live fetch fails resolves to its last
   cached snapshot silently if one exists, or that ticker's error state
   if not; every success is persisted back to `data/tickers.json`. Unlike
   the indicator path's single combined `/api/check`, the ticker page's
   own inline `<script>` fires one `/api/tickers/groups/<name>/check`
   per group plus one `/api/market-news/check`, all concurrently, each
   patching only its own `.category-block`/`#market-news` in place as
   it resolves — a group with fewer tickers repaints before a slower
   one finishes, instead of the whole page waiting on one combined
   request (which had occasionally needed gunicorn's `--timeout 120`
   to avoid a bare 500 on the full ~36-ticker watchlist).

### Storage model
Three separate JSON blobs — not a database, and not the same file. Local dev keeps all three as plain files under `data/`; a hosted deployment (`UPSTASH_REDIS_REST_URL` set) moves all three to Redis instead (Story 9 for the two ticker-related ones, Story 11 for indicators) — see `web/kv_store.py`.

- **`data/indicators.json`** (local file; Redis-backed on a hosted deployment, key `indicator_state`) — the v1 historical record, and (Story 11) the shared state both the scheduled GitHub Actions workflow and any hosted web app read/write directly, rather than two independent copies drifting apart. Shape:
  `{"indicators": {key: {name, category, fred_series_id, fred_release_id,
  history: [{date, value, fetched_at}], next_release_date}}, "last_digest_sent_at",
  "last_digest_content_fingerprint", "last_ai_response": {summary, directional_read, generated_at}}`.
  Locally, running the web dashboard and triggering a live update (via `/api/check`
  finding new data) writes to the local file, leaving it dirty in your working tree
  until committed or discarded — expected and harmless, since ingestion is idempotent
  (dedup by date never double-counts or corrupts history). **No longer git-committed
  by the scheduled workflow** (that step was removed in Story 11 along with the
  `contents: write` permission it needed) — indicator history also no longer has a
  git-diffable audit trail as a result, a deliberate tradeoff matching Story 9's for
  ticker data. A Redis failure loading/saving this one propagates rather than
  degrading, unlike the two caches below — it's core data, not a mere cache.
- **`data/tickers.json`** (gitignored) — a pure local cache, one
  snapshot per ticker: `{symbol: {price, change, change_percent, week52_low,
  week52_high, pct_off_high, ma20, ma50, ma200, fetched_at}}`. Never committed
  and never scheduled — it's written only when you run the Flask app locally
  and one of the `/api/tickers/groups/<name>/check` requests fires, purely
  so the *next* local page load has something better than a blank "Loading…"
  row to show instantly. Losing it is harmless (everything just shows as
  pending again until the next live fetch).
- **`data/market_news.json`** (gitignored) — same idea as `data/tickers.json`,
  one cached snapshot for the whole market-news feed instead of one per
  ticker: `{"headlines": [...], "fetched_at": ...}`. Also written by
  `/api/market-news/check`, also harmless to lose.

### Testing conventions
There are no package `__init__.py` files — every module (in `src/` and in
`tests/`) manually inserts the relevant `src/<subdir>` directories onto
`sys.path` and imports by bare module name (e.g. `from build_digest_content
import build_table`), matching the pattern already at the top of each
`src/**/*.py` file. Follow that same `sys.path.insert` pattern for any new
module or test file rather than introducing relative/package imports. No
network calls in tests — `fetch_fred.requests.get`, `finnhub_client.requests.get`,
`kv_store.requests.get`/`.post`, the Gemini client, and `smtplib.SMTP` are all
mocked; `run_ingestion`, `refresh_ai_response_if_updated`,
`ticker_dashboard.build_ticker_cards`, etc. all take injectable
`fetch_fn`/`interpret_fn`/`send_fn`/`fetch_quote_fn`-style callables for this.
`maybe_send_digest_email` is the one exception with no such callable — it
structurally cannot call Gemini, only `send_fn`.

### Comment conventions
Comments and docstrings describe the current state of the code, not its
history. Don't reference story/task numbers, dates, "added on ...",
"previously X, now Y", "replaces the earlier design", "confirmed live
on ...", or otherwise narrate what changed and when — that belongs in
commit messages and PR descriptions, not in the source, and it rots as
the codebase moves on. Only write a comment when the WHY isn't obvious
from the code itself (a hidden constraint, an external API's quirk, a
non-obvious tradeoff), and state it as a plain fact about how things
work now rather than as a change-log entry.

## Status / where things stand

- The **Indicator Digest Page** (`src/web/`, `/`) is built: AI section, table
  (with a small inline-SVG trend sparkline per indicator row), countdown, and
  a "Checking for updates..." indicator shown for the duration of the
  background check. There is deliberately no persistent Live/Saved freshness
  badge or timestamp — found distracting in practice. Don't re-add either
  without the user explicitly asking.
- The **Ticker Dashboard** (`/tickers`) is built end to end: `config/tickers.json`
  + `ticker_dashboard.load_ticker_config()` (open group map read in file
  order, malformed symbols skipped and logged), and `finnhub_client.py` +
  `yahoo_client.py` + `ticker_dashboard.build_ticker_cards()` +
  `page_template.render_ticker_dashboard_page()` (per-ticker
  price/52wk-range/market-cap/P-E from Finnhub, 20d/50d/200d SMA from
  Yahoo daily closes, grouped under headers title-cased from the
  config keys, one row's fetch failure — from either provider —
  rendered as that row's own error state without affecting the rest of
  the page).
  **Data-source note:** Finnhub's free tier 403s `/stock/candle`
  unconditionally, so `/stock/metric` (`finnhub_client.fetch_stock_metrics`)
  covers the 52-week range, market cap, and trailing P/E in one call, but
  moving averages need daily closes from Yahoo Finance's public,
  unauthenticated chart endpoint instead, via a plain `requests` call
  (`yahoo_client.py`) rather than the `yfinance` library, to avoid its
  much heavier dependency tree. stooq.io was tried and rejected — its
  requests require solving a client-side JS proof-of-work challenge.
- Rendering is one `<table>` per group (not per-ticker cards), with no
  per-ticker news column — both were tried and dropped as harder to scan /
  low-value. Don't re-add either without the user explicitly asking. Columns
  include a 50-day moving average alongside 20d/200d, market cap and
  trailing P/E (either "n/a" when Finnhub has no value for that symbol), a
  green→amber→red gradient bar showing where price sits in its 52-week
  range, and a colored arrow+percentage on each MA showing how far price is
  above/below it (same palette as the AI directional badges/sparklines) —
  both encodings deliberately avoid color-alone. A trailing, unlabeled
  column holds each row's remove button (Story 7), placed there rather
  than beside the ticker symbol so it doesn't crowd the column read
  first. Both pages share a nav (`page_template._render_nav`) linking
  to the other.
  `finnhub_client.fetch_company_news` (a per-ticker news column, tried and
  dropped) was removed rather than left as dead code.
- `/tickers` renders instantly from the `data/tickers.json` snapshot cache (a
  ticker with no cached snapshot renders "Loading…"), then the page's script
  fires one `/api/tickers/groups/<name>/check` per group plus one
  `/api/market-news/check`, all concurrently, in the background (each
  patches only its own `.category-block`/`#market-news`, mirroring
  `/api/check`'s `#checking-indicator` markup/CSS for the page-level
  "Checking for updates..." indicator, which now clears once every one of
  those requests has settled via `Promise.allSettled`). A live-fetch
  failure falls back silently to the last cached snapshot unless there's
  none to fall back to. Unlike the indicator pipeline's background check,
  this one has no "skip if nothing changed" gate — every check re-fetches
  every ticker live, since there's no expensive AI call to protect.
  **Per-group split (2026-09-16):** originally one combined
  `/api/check-tickers` request fetched and re-rendered the entire ~36-ticker
  watchlist at once, occasionally taking 30+ seconds and needing gunicorn's
  `--timeout 120` to avoid a bare 500 on Render. Splitting into one request
  per group (`check_for_ticker_updates(config={group: symbols})`, already
  merge-safe against the shared cache) lets a smaller group repaint well
  before a larger one finishes, instead of an all-or-nothing wait. Because
  every group's check now genuinely runs concurrently in local dev
  (`app.py`'s `app.run(..., threaded=True)`),
  `check_for_ticker_updates`'s load-merge-save of the shared
  `data/tickers.json`/Redis cache is wrapped in
  `ticker_dashboard._ticker_state_lock` (held only around that in-memory
  merge and the final write, never around the network fetch) so two
  groups finishing close together can't silently overwrite each other's
  freshly-fetched values — a real race that concurrent per-group requests
  made far more likely to actually trigger than it was with a single
  combined request. Full per-ticker progressive/streaming updates (each row
  resolving independently) remain deliberately not built — per-group
  granularity plus concurrent fetching within a group already deliver most
  of the same UX gain for far less complexity.
  **Render gap, found live:** the split alone doesn't help on Render —
  gunicorn's start command has no `--workers`/`--threads` flag, so it
  defaults to one sync worker handling exactly one request at a time.
  The 6 concurrent per-page-load requests (5 groups + market news) just
  queue there, so the slowest one still waits behind every request ahead
  of it (~35s observed, versus each group's own fetch taking a few
  seconds in isolation). Fix: add `--worker-class gthread --threads 8` to
  Render's start command — threads, not `--workers N`, since
  `_ticker_state_lock` is a plain `threading.Lock` that only protects
  within one process; separate worker processes wouldn't share it and
  would reopen the exact race the lock exists to close. This is a
  Render-dashboard-only change (same as `--timeout 120`), not committed
  to any file — pending as of this writing, see
  `docs/v2_technical_design.md` Section 11.5/11.8.
- `ticker_dashboard.build_ticker_cards()` fetches every ticker concurrently
  via `ThreadPoolExecutor` (`max_workers=5` — deliberately modest, since
  maxing out Finnhub's free-tier rate limit risks trading slow-but-successful
  fetches for fast 429s). `main.run_ingestion()`/`update_release_calendar()`
  use the same pattern, one thread per indicator. Only the fetch calls run
  concurrently; state mutation and result-building still run
  single-threaded afterward, and `executor.map`'s output-order guarantee
  keeps everything grouped/ordered exactly as a sequential version would,
  regardless of which fetch resolves first — covered by tests that force
  out-of-order completion via `time.sleep` and assert the order didn't
  scramble.
- Two more table columns: `pct_off_high` (`(week52_high - price) /
  week52_high * 100`, computed client-side, no new fetch) and
  `change`/`change_percent` (from Finnhub's `/quote` `d`/`dp` fields, no new
  endpoint) — plus a US-stock-market-news feed
  (`finnhub_client.fetch_market_news()`, `/news?category=general` filtered
  to Finnhub's own `"top news"` tag, since the raw feed is a broad wire, not
  market-specific) shown once at the top of `/tickers`, above the grouped
  tables — a page-level feed, not one per row. Market news has its own
  gitignored cache, `data/market_news.json`, and its own
  `get_initial_market_news()`/`check_for_market_news()` pair mirroring the
  ticker-card split at whole-section granularity, with its own
  `/api/market-news/check` route (JSON response carries a `news_html`
  field) fetched independently of any ticker group's own check.
- Each group's table can be sorted by clicking the Ticker or % Off High
  header (ascending, then descending on a second click) — pure client-side
  DOM reordering (`render_ticker_dashboard_page`'s inline `<script>`, event-
  delegated on `#ticker-groups`), driven by `data-symbol`/`data-pct-off-high`
  attributes `_render_ticker_row` puts on each `<tr>` and `data-sort-key` on
  the two `<th>`s. Pending/errored rows (empty `data-pct-off-high`) always
  sort last regardless of direction. Sorting is per table/group and resets
  when that group's own `/api/tickers/groups/<name>/check` refresh lands,
  since that swaps just that group's `.category-block` wholesale — other
  groups' sort state is untouched. The earlier top-discount row highlight
  (Story 3) was removed in favor of this — don't re-add it without the
  user explicitly asking.
- Market Cap and trailing P/E: `finnhub_client.fetch_stock_metrics()` (the
  successor to the old `fetch_52_week_range()` — same `/stock/metric` call,
  now also pulling `marketCapitalization` and `peTTM` with fallback through
  `peBasicExclExtraTTM`/`peNormalizedAnnual`) so there's no new fetch per
  ticker. `page_template._format_market_cap()` renders the raw
  millions-of-USD figure as `$T`/`$B`/`$M`; either column renders "n/a"
  (not an error) when Finnhub has no value for that symbol. At 11
  columns, the ticker table needed tighter styling than the Indicator
  Digest table to fit without horizontal scroll: `dashboard.css`'s
  `.ticker-table` rule trims cell padding and (for data cells only)
  font-size below `.indicator-table`'s defaults, and deliberately
  leaves `<th>` out of the nowrap rule so a long one-line header (e.g.
  "Market Cap") can wrap to two lines rather than forcing its narrow
  data column wide. `RANGE_BAR_WIDTH` (`page_template.py`) was also
  trimmed 100→90 to match.
- In-app ticker editing (Story 7): `ticker_dashboard.add_ticker_to_group`/
  `remove_ticker_from_group` read-modify-write `config/tickers.json`
  directly (or Redis when configured, Story 9); `/api/tickers/add`/`/remove`
  (`app.py`) wrap them, 400 on `TickerConfigError`. Each row has a remove
  button, each group an add-ticker field, event-delegated on
  `#ticker-groups`. Tickers only — adding, renaming, or removing a whole
  group is still a hand-edit of the file.
  **Remove is optimistic** (added 2026-09-16): the row is deleted from
  the DOM immediately on confirm, no page reload on success — a failure
  re-inserts the row at its original position and alerts. Replaced the
  original reload-on-success design, which made removing one ticker pay
  the cost of a full watchlist live refresh just to reflect one row
  disappearing. **Add still reloads the page** on
  success — not worth the complexity of constructing a client-side
  pending-row fragment for a much less frequent action; revisit if it
  starts feeling as slow as remove did.
  **Caution:** reassigning `ticker_dashboard.CONFIG_PATH` after import does
  *not* redirect a call using the default arg (Python binds defaults at
  def-time) — always pass `path=`/`state_path=` explicitly when testing
  against a throwaway file, as the test suite already does.
- Auth gate (Story 8, app-code half only — see `docs/v2_technical_design.md`
  Section 11.2): `app.py`'s `_require_auth` `before_request` hook requires
  HTTP Basic Auth matching `DASHBOARD_USERNAME`/`DASHBOARD_PASSWORD` on
  every route, including the `/api/*` ones, using `secrets.compare_digest`
  for a timing-safe comparison. It's a no-op unless *both* env vars are
  set, so local dev (where neither is set) is unaffected — this is the
  intentional interpretation of "if set" in Story 8's AC for the
  partially-configured case (only one of the two set), to avoid an
  accidental lockout from a typo'd env var name. Covered by
  `tests/test_app.py`. Deployed and confirmed live on Render: the
  password prompt appears over HTTPS before any content renders.
- Redis-backed persistence (Story 9, `docs/v2_technical_design.md`
  Section 11.3/11.4): `kv_store.py` wraps Upstash's REST API;
  `ticker_dashboard.py`'s `_load_raw_config`/`_save_raw_config` (the
  watchlist), `load_ticker_state`/`save_ticker_state` (the ticker
  cache), and `load_market_news_state`/`save_market_news_state` (the
  news cache) each check `kv_store.is_configured()` and route through
  it instead of the local file when true — `app.py`'s routes call these
  with default args and don't know or care which backend is active. A
  cache failure degrades to the same empty/pending state a missing
  local file would; a config-load failure propagates (fails loudly,
  per Story 9's AC). On first Redis-backed read with no `ticker_config`
  key yet, seeds from the repo's committed `config/tickers.json`.
  Covered by `tests/test_kv_store.py` and the `TestRedisBacked*` classes
  in `tests/test_ticker_dashboard.py`; the full pre-existing suite
  passes unmodified with no Redis env vars set (the regression case).
  **Confirmed against a real Upstash instance**: the wire format
  (`GET {url}/get/{key}`, `POST {url}/set/{key}` with the raw JSON
  body) round-trips correctly, verified with a standalone script
  hitting `kv_store.get_json`/`set_json` directly. `UPSTASH_REDIS_REST_URL`/
  `TOKEN` are live on Render and a hosted ticker removal correctly
  updates `ticker_config` in Upstash.
  **Two Render gotchas hit along the way**, both in
  `docs/v2_technical_design.md` Section 11.5: (1) env var edits in
  Render's dashboard don't take effect until you explicitly hit "Save
  and Redeploy" — without it, the service silently keeps running on
  its old environment, no error or warning, which made
  `/api/tickers/remove` return a real `{"ok": true}` while writing to
  the container's ephemeral local file instead of Redis (since
  `is_configured()` was still reading the stale, Redis-less
  environment). (2) After that redeploy, a value pasted into Render's
  env var field *with* surrounding quotes (`"https://...upstash.io"`)
  keeps those quotes as part of the literal string — Render's fields
  aren't shell-parsed — producing a `requests.exceptions.InvalidSchema`
  500 on every page load. `kv_store.py`'s `_clean_env_value()` now
  strips one matching pair of surrounding `"`/`'` (plus whitespace)
  from both `UPSTASH_REDIS_REST_URL` and `UPSTASH_REDIS_REST_TOKEN`
  before use, so this self-heals rather than crashing next time.
  Always check Render's Events tab for an actual redeploy timestamp
  after an env var change, not just that the form saved.
- `/api/check-tickers`'s gunicorn-timeout fix (confirmed on the first
  live Render deploy, `docs/v2_technical_design.md` Section 11.5):
  fetching all 36 tickers in one request occasionally exceeded
  gunicorn's default 30s sync-worker timeout, which kills the worker
  mid-request (`SystemExit: 1` from `handle_abort`) rather than raising
  a catchable exception — surfaces to the browser as a bare 500 with no
  body. Originally fixed by adding `--timeout 120` to the start command
  rather than restructuring the request, with a real scaling limit
  left underneath (one request growing with the watchlist size) — a
  full React frontend remained backlogged for this
  (`docs/investment_dashboard_requirements.md` Section 5) as a bigger,
  not-currently-scheduled rewrite. **Superseded (2026-09-16):** the
  interim the backlog note anticipated ("without needing bespoke
  per-group routes... in the meantime") was built instead of deferred
  further — `/api/check-tickers` was replaced by one
  `/api/tickers/groups/<name>/check` route per group plus
  `/api/market-news/check`, on the existing string-templating
  approach, with no new frontend framework. This resolves the actual
  timeout problem directly; the React port stays backlogged for if a
  fuller componentized frontend is ever wanted for its own sake.
- A local `.env` value containing an unescaped shell-special character
  (e.g. `|`) silently truncates at that character under `source .env`
  — bash executes each line as a command, not a proper `.env` parser.
  Quote such values (`KEY='value'`) to fix; confirmed this cost a
  working `DASHBOARD_PASSWORD` locally until caught and fixed.
- Indicator state moves to Redis too (Story 11, `docs/v2_technical_design.md`
  Section 11.7): `storage.py`'s `load_state`/`save_state` route through
  `kv_store.py` when configured, mirroring `ticker_dashboard.py`'s
  pattern exactly — `storage.py` adds `web/` to its own `sys.path`
  rather than moving `kv_store.py`, to avoid touching Story 9's
  already-working code. This replaced an earlier design (the original
  Story 10, now superseded) where `data/indicators.json` stayed
  git-committed by the scheduled workflow — that design had a real
  gap: the AI response only ever refreshed when an email was also due
  (weekly), so a live visitor's background check could compute a
  fresher take that then got silently discarded on the next Render
  restart. `post_release.py` also split in two:
  `refresh_ai_response_if_updated` (every cycle with new data, no
  throttle) and `maybe_send_digest_email` (the weekly send, gated on a
  content fingerprint — a hash of every indicator's latest value/date
  plus the AI's `directional_read`, deliberately excluding the
  free-text summary since Gemini can reword an unchanged situation
  differently between calls — plus the existing 7-day interval floor).
  `maybe_send_digest_email` has no `interpret_fn` parameter at all; it
  structurally cannot call Gemini, only reuse whatever's already
  persisted, so the two functions can never double-call it in the same
  cycle. `indicator-check.yml` no longer commits/pushes
  `data/indicators.json` (that step and the `contents: write`
  permission it needed are both gone) — it passes
  `UPSTASH_REDIS_REST_URL`/`TOKEN` (GitHub Actions secrets, separate
  from Render's env vars, added and confirmed working) to
  `python3 src/main.py` instead, which writes straight to Redis.
  Verified against the real Upstash instance via a throwaway key (same
  approach used to verify `kv_store.py` for Story 9), and confirmed
  fully live: a manually-triggered `workflow_dispatch` run completed
  against real Redis/FRED/Gmail and sent a real digest email. The full
  pre-existing test suite passes unmodified with no Redis env vars set
  (the regression case).
  **Real incident, fixed same day:** the first version shipped with no
  seeding step for indicator state (unlike the ticker config's
  `_load_raw_config`) — Render already had the Upstash env vars
  configured (from Story 9) by the time this code deployed, so the
  first live visit found `indicator_state` empty and reset every
  indicator to a single fresh FRED reading, discarding months of
  history; sparklines went flat and the AI response went missing.
  Recovered by hand (`python3 src/backfill.py` to repopulate history,
  a manual `refresh_ai_response_if_updated` call once a concurrent
  Gemini `503` outage cleared), then actually fixed: `load_state()` now
  seeds from the local `data/indicators.json` file the first time the
  Redis key is empty, exactly mirroring the ticker config's pattern —
  see `docs/v2_technical_design.md` Section 11.7's incident note and
  `tests/test_storage.py`'s seeding tests.
- When behavior actually changes, keep these in sync (all checkbox/prose
  acceptance-criteria style, not auto-generated): `docs/investment_dashboard_requirements.md`,
  `docs/v2_user_stories.md`, `docs/v2_technical_design.md`,
  `docs/v2_task_breakdown.md`, and the relevant `README.md` section.
