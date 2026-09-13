# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this is

A single-user investment-monitoring tool, replacing a manual Fidelity-website
+ Google-Sheet workflow. Not a general product — there's one owner/user
(`docs/investment_dashboard_requirements.md` Section 2). v1 (shipped): a
scheduled email digest of 8 macro indicators with AI commentary. v1.1 (in
progress): a local Flask web dashboard mirroring that content, plus a
Ticker Dashboard sourced from Finnhub + Yahoo Finance, with a shared nav
linking the two pages. Full spec lives in `docs/`:
`investment_dashboard_requirements.md` (product requirements, both v1 and
v1.1), `v1.1_user_stories.md` (acceptance criteria), `v1.1_technical_design.md`,
`v1.1_task_breakdown.md`.

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

Run the v1.1 web dashboard locally:
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
| `FINNHUB_API_KEY` | the Ticker Dashboard's per-ticker quote/52wk-range fetch — without it, the background check's live fetch fails for every ticker, falling back to `data/tickers.json`'s cached snapshot where one exists, or that ticker's error state where one doesn't; Story 2's config loading needs no API key |

## Architecture

### One pipeline, two product surfaces
v1 (email) and v1.1 (web page) are built from the same modules — nothing is
duplicated between them:

```
src/
  fred/     fetch_fred.py (FRED API client), indicators_config.py (the 8 tracked
            indicators + their FRED series/release IDs — the source of truth for
            "what indicators exist")
  storage/  storage.py — JSON-backed persistence (data/indicators.json):
            load_state/save_state/query_history/trim_history
  digest/   build_digest_content.py — SHARED table/countdown/AI-assembly logic,
            called by both the email and the web page (single source of truth
            for "what does the digest contain")
            post_release.py — email-specific: weekly-send throttle + send
            interpret.py — the Gemini call; heuristics.py — Sahm Rule / yield-curve
            inversion streak, fed into the AI prompt
  mailer/   email_template.py, send_email.py, sparkline.py (matplotlib PNG —
            Gmail strips inline <svg>, so the email needs a raster image
            embedded via Content-ID; the web page instead renders sparklines
            as plain inline SVG, since browsers don't have that limitation)
  web/      app.py (Flask routes: "/", "/tickers", "/api/check",
            "/api/check-tickers"), live_pull.py (stored-only render +
            gated background live-check for the Indicator Digest Page),
            page_template.py (HTML string rendering for both pages,
            mirrors email_template.py's plain-string-building
            convention — no templating engine; also renders the shared
            _render_nav() linking the two pages), ticker_dashboard.py
            (load_ticker_config() reads config/tickers.json's groups as
            an open map in file order, skips malformed symbols;
            build_ticker_cards() does the per-ticker quote + 52wk range
            fetch from Finnhub plus daily closes from Yahoo for the
            20d/50d/200d SMA, with a per-ticker try/except so one bad
            symbol can't take down the rest; get_initial_ticker_page_data()
            + check_for_ticker_updates() are the stored-render/live-check
            split, backed by load_ticker_state()/save_ticker_state()
            reading/writing data/tickers.json), finnhub_client.py
            (quote/52wk-range REST wrapper, raises FinnhubApiError
            per-call — NOT candles: see its docstring, Finnhub's free
            tier blocks `/stock/candle` outright; company-news was
            built and then removed, see Status below), yahoo_client.py
            (daily closes from Yahoo's public chart endpoint, no API
            key — the only source for moving averages; raises
            YahooApiError per-call)
  main.py       v1 entrypoint: run_ingestion + update_release_calendar +
                run_post_release — what the scheduled workflow calls
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
   `state["last_ai_response"]` (a v1.1 addition, so the web page's initial
   render has something to show without making a live call).
4. Email path: `post_release.run_post_release()` wraps step 3 with a weekly
   send-throttle (`last_digest_sent_at`) and calls `send_email.send_email()`.
5. Web path: `web/live_pull.py` splits into `get_initial_page_data()`
   (stored-only, no network — instant render) and `check_for_updates()` (the
   real live pull via `main.run_ingestion`, gated: skips the calendar
   refresh/AI call/`save_state()` entirely unless at least one indicator's
   status is `"updated"` — so the common "nothing new" case costs a FRED call
   but never a Gemini call). The page's own inline `<script>` calls
   `/api/check` right after load and patches `#table-section`/
   `#countdown-section`/`#ai-section` in place only if `data_updated` is true.
6. Ticker path: `web/ticker_dashboard.py` splits the same way —
   `get_initial_ticker_page_data()` (stored-only, reads `data/tickers.json`)
   and `check_for_ticker_updates()` (the real live pull via
   `build_ticker_cards()`, always re-fetches every ticker — no
   "nothing changed" gate, since there's no expensive AI call to
   protect here). A ticker whose live fetch fails resolves to its last
   cached snapshot silently if one exists, or that ticker's error state
   if not; every success is persisted back to `data/tickers.json`. The
   page's own inline `<script>` calls `/api/check-tickers` right after
   load and replaces `#ticker-groups` unconditionally (there's no
   `data_updated` gate to check, since the ticker check is never a
   no-op).

### Storage model
Two separate local JSON files — not a database, and not the same file:

- **`data/indicators.json`** (committed) — the v1 historical record. Shape:
  `{"indicators": {key: {name, category, fred_series_id, fred_release_id,
  history: [{date, value, fetched_at}], next_release_date}}, "last_digest_sent_at",
  "last_ai_response": {summary, directional_read, generated_at}}`. The scheduled
  GitHub Actions workflow (`.github/workflows/indicator-check.yml`) commits this
  file back to the repo after each run. Running the web dashboard locally and
  triggering a live update (via `/api/check` finding new data) writes to this
  same file, leaving it dirty in your local working tree until committed or
  discarded — expected and harmless, since ingestion is idempotent (dedup by
  date never double-counts or corrupts history).
- **`data/tickers.json`** (gitignored, v1.1 addition) — a pure local cache, one
  snapshot per ticker: `{symbol: {price, week52_low, week52_high, ma20, ma50,
  ma200, fetched_at}}`. Never committed and never scheduled — it's written only
  when you run the Flask app locally and `/api/check-tickers` fires, purely so
  the *next* local page load has something better than a blank "Loading…" row
  to show instantly. Losing it is harmless (everything just shows as pending
  again until the next live fetch).

### Testing conventions
There are no package `__init__.py` files — every module (in `src/` and in
`tests/`) manually inserts the relevant `src/<subdir>` directories onto
`sys.path` and imports by bare module name (e.g. `from build_digest_content
import build_table`), matching the pattern already at the top of each
`src/**/*.py` file. Follow that same `sys.path.insert` pattern for any new
module or test file rather than introducing relative/package imports. No
network calls in tests — `fetch_fred.requests.get`, `finnhub_client.requests.get`,
the Gemini client, and `smtplib.SMTP` are all mocked; `run_ingestion`,
`run_post_release`, `ticker_dashboard.build_ticker_cards`, etc. all take
injectable `fetch_fn`/`interpret_fn`/`send_fn`/`fetch_quote_fn`-style
callables for this.

## Status / where things stand

- v1.1's **Indicator Digest Page** (`src/web/`, `/`) is built: AI section, table
  (with a small inline-SVG trend sparkline per indicator row), countdown, and
  a "Checking for updates..." indicator shown for the duration of the
  background check. An earlier iteration also had a persistent Live/Saved
  freshness badge with a Pacific-time timestamp next to the values and AI
  sections — removed after using it live, since it was found distracting.
  Don't re-add either without the user explicitly asking.
- The **Ticker Dashboard** (`/tickers`) is built end to end and verified
  against live data: `config/tickers.json` + `ticker_dashboard.load_ticker_config()`
  (Story 2 — open group map read in file order, malformed symbols skipped
  and logged) and `finnhub_client.py` + `yahoo_client.py` +
  `ticker_dashboard.build_ticker_cards()` + `page_template.render_ticker_dashboard_page()`
  (Story 3 — per-ticker price/52wk-range from Finnhub, 20d/50d/200d SMA
  from Yahoo daily closes, grouped under headers title-cased straight from
  the config keys, one row's fetch failure — from either provider —
  rendered as that row's own error state without affecting the rest of
  the page).
  **Data-source pivot, worth knowing before touching this code:** the original
  plan was Finnhub `/stock/candle` for everything price-history-related.
  Confirmed live (2026-09-13) that Finnhub's free tier now 403s that endpoint
  unconditionally — `/stock/metric` still covers the 52-week range for free,
  but moving averages need daily closes from somewhere else. stooq.io was
  tried and rejected (every request now requires solving a client-side JS
  proof-of-work challenge — not something to build a bypass for). Settled on
  Yahoo Finance's public, unauthenticated chart endpoint via a plain
  `requests` call (`yahoo_client.py`) rather than the `yfinance` library, to
  avoid that library's much heavier dependency tree. See Section 5's
  deviation note in `docs/v1.1_technical_design.md` for the full account.
- **Redesigned 2026-09-13, after using it live:** the Ticker Dashboard
  originally rendered one card per ticker in a grid, with a news column.
  Both were dropped: the card grid was hard to scan, so it's now one
  `<table>` per group (same per-category-table pattern as the Indicator
  Digest Page), and news was cut entirely (cluttered the table without
  adding enough value) — `finnhub_client.fetch_company_news` was removed
  along with it, not left as dead code. Added: a 50-day moving average
  alongside 20d/200d, a green→amber→red gradient bar with a marker showing
  where the current price sits in its 52-week range, and a colored
  arrow+percentage on each MA showing how far price is above/below it
  (green above, red below — reusing the same palette as the AI directional
  badges/sparkline endpoints already used on the Indicator Digest Page,
  not a new one). Both encodings deliberately avoid color-alone: numbers
  and arrows carry the same information as the color. Both pages now also
  show a small nav (`page_template._render_nav`) linking to the other.
  Don't re-add cards or the news column without the user explicitly asking.
- **Story 5, added 2026-09-13:** the Ticker Dashboard originally blocked
  `/tickers` on every ticker's Finnhub+Yahoo fetch before rendering
  anything — explicitly ruled out having a persisted fallback at Story 3
  time, then added one after using the page live and finding the wait
  too long. `/tickers` now renders instantly from `data/tickers.json`
  (a ticker with no cached snapshot renders "Loading…"), the page's own
  script calls the new `/api/check-tickers` route in the background
  (mirrors `/api/check`'s pattern exactly, including reusing the same
  `#checking-indicator` markup/CSS), and a live-fetch failure falls back
  silently to the last cached snapshot rather than erroring, unless
  there's no snapshot to fall back to. Unlike the indicator pipeline's
  background check, this one has no "skip if nothing changed" gate —
  every check re-fetches every ticker live, since there's no expensive
  AI call here to protect. Deliberately *not* done: per-ticker
  progressive/streaming updates (each row resolving independently) and
  parallelizing the per-ticker fetches — both would be reasonable
  follow-ups if the background check's total wait is still noticeable,
  but weren't asked for and would add real complexity, so left out for
  now (see Section 5.3 of the tech design).
- When behavior actually changes, keep these in sync (all checkbox/prose
  acceptance-criteria style, not auto-generated): `docs/investment_dashboard_requirements.md`,
  `docs/v1.1_user_stories.md`, `docs/v1.1_technical_design.md`,
  `docs/v1.1_task_breakdown.md`, and the relevant `README.md` section.
