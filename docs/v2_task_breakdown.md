# V2 Task Breakdown — Estimates & Test Plan

**Companion to:** investment_dashboard_requirements.md, v2_user_stories.md, v2_technical_design.md

---

## Cross-Cutting Foundation

| Task | Status |
|---|---|
| F.1 `requirements.txt` + venv: add `flask` | done |
| F.2 `src/web/app.py` — Flask app scaffold, route registration (`/`, `/tickers`), explicit `host="127.0.0.1"` binding | done |
| F.3 `run_web.sh` — convenience start script | done |
| F.4 `static/dashboard.css` — shared minimal styling for both pages | done |
| F.5 Verify the running app is unreachable from another device on the same network | done |

**Tests**
- Flask app starts and serves both routes without error against a fresh `data/indicators.json` / `config/tickers.json`
- A request from a non-loopback source is refused (manual verification, not unit-testable)

---

## Epic: Indicator Digest Page

### Extract `build_digest_content()` from `post_release.py`

| Task | Status |
|---|---|
| P.1 Extract table/countdown/AI-assembly logic into `digest/build_digest_content.py`, returning `{table, countdown, ai_result}` | done |
| P.2 Update `post_release.py` to call the extracted function; throttle + email-send logic unchanged | done |
| P.3 Regression tests — weekly digest email's content is byte-for-byte equivalent to pre-refactor output | done |

**Tests**
- Existing `test_post_release.py` suite still passes unmodified
- `build_digest_content()` called directly with a sample state produces the same table/countdown/AI dict shape `post_release.py` used to build inline

---

### Persist `last_ai_response`

| Task | Status |
|---|---|
| A.1 Add `last_ai_response` field to `data/indicators.json` schema — no migration needed, field is absent until first write | done |
| A.2 `build_digest_content.py` persists `{summary, directional_read, generated_at}` on every successful Gemini call — both email and live-pull paths | done |

**Tests**
- A successful Gemini call updates `last_ai_response` with the correct summary/directional_read/generated_at
- A failed Gemini call leaves the previous `last_ai_response` untouched
- Loading a pre-v2 `indicators.json` with no `last_ai_response` key doesn't crash

---

### Story 1 / 1a — Indicator Digest Page: Live Pull with Fallback

| Task | Status |
|---|---|
| 1.1 `live_pull.py` — split into `get_initial_page_data()` (stored-data-only) and `check_for_updates()` (gated live pull) | done |
| 1.2 Independent freshness per section: table/countdown can update while the AI section stays on the last `last_ai_response` if only the Gemini call fails | done |
| 1.3 `page_template.py` — AI section, table (grouped Leading/Coincident/Lagging, each row with an inline-SVG sparkline), countdown, disclaimer, "Checking for updates..." indicator | done |
| 1.4 `/` + `/api/check` route wiring in `app.py` | done |

**Tests**
- Initial `/` render is built entirely from stored data — never calls `run_ingestion`
- The background check finding at least one updated indicator refreshes the release calendar, re-runs the AI interpretation, and persists via `save_state()`
- The background check finding nothing new (or failing outright) reports no update — no calendar refresh, no AI call, no save
- FRED succeeds but Gemini fails after retries → table/countdown updates in place while the AI section keeps showing the last `last_ai_response`
- Brand-new install (`last_ai_response` absent) renders a placeholder without crashing
- AI content is labeled as informational commentary, not personalized financial advice
- Each table row renders a sparkline; a single-point history renders as a dot only
- The "Checking for updates" indicator is present on initial render and cleared once `/api/check` settles

---

## Epic: Ticker Dashboard

### Story 2 — Ticker Watchlist Configuration

| Task | Status |
|---|---|
| 2.1 `config/tickers.json` — `sector`/`individual` as separate groups | done |
| 2.2 Config loader in `ticker_dashboard.py` — reads `groups` as an open map, iterates in file order; no group name hardcoded | done |
| 2.3 Ticker symbol format validation — skip and log a warning for a malformed entry | done |

**Tests**
- Adding a ticker to an existing group, with no code change, appears on next reload
- Adding a new group key appears as a new section, with a header derived from the key
- Renaming a group key changes its displayed header, doesn't duplicate or drop tickers
- A malformed ticker entry is skipped with a logged warning; well-formed tickers in the same group still load

---

### Story 3 — Ticker Dashboard Page

| Task | Status |
|---|---|
| 3.1 `finnhub_client.py` — quote endpoint | done |
| 3.2 `finnhub_client.py` — 52-week range + market cap + P/E via `/stock/metric` (`fetch_stock_metrics`) | done |
| 3.3 20/50/200-day simple moving average calculation from Yahoo daily closes | done |
| 3.4 `ticker_dashboard.py` — per-ticker assembly with independent try/catch per ticker | done |
| 3.5 `page_template.py` — grouped tables, per-row error state | done |
| 3.6 `/tickers` route wiring in `app.py` | done |
| 3.7 `pct_off_high` computed from existing price/week52_high, no new fetch | done |
| 3.8 `finnhub_client.fetch_quote()` — parse `d`/`dp` alongside `c` | done |
| 3.9 Two new table columns (% off high, change) with the signed-value + green/red-arrow convention | done |
| 3.10 Market Cap + P/E table columns, "n/a" when Finnhub has no value | done |

**Tests**
- Mocked Finnhub/Yahoo responses → row shows correct price, 52-week range, both moving averages
- One ticker's mocked call raises an exception → that row shows an error state, all others still render correctly
- 52-week high/low, moving averages computed correctly from known sample data (including fewer than 200 closes available)
- Cards render grouped under the correct headers matching `config/tickers.json`'s group keys, in file order
- `pct_off_high` computed correctly from a known price/52-week-high pair
- Change-since-close renders with correct sign/color for an up day, a down day, and a flat day
- A ticker with no `d`/`dp` in the quote response degrades to "n/a" rather than crashing

---

### Story 4 — Cross-Page Navigation

| Task | Status |
|---|---|
| 4.1 Shared `_render_nav(active_path)` on both pages | done |

**Tests**
- Nav renders on both pages, marks the current page active

---

### Story 5 — Instant Load with Background Refresh

| Task | Status |
|---|---|
| 5.1 `data/tickers.json` snapshot cache; `get_initial_ticker_page_data()`/`check_for_ticker_updates()` split | done |
| 5.2 `/api/check-tickers` route | done |
| 5.3 Concurrent fetch via `ThreadPoolExecutor` (`max_workers=5`) | done |

**Tests**
- Initial `/tickers` render never blocks on a live fetch
- A ticker with no cached snapshot renders "Loading…", not an error
- A failed live fetch falls back to the last cached snapshot silently; only a never-fetched ticker shows the error state
- Concurrent fetch preserves group/row order regardless of which ticker's fetch resolves first

---

### Story 6 — US Stock Market News

| Task | Status |
|---|---|
| 6.1 `finnhub_client.fetch_market_news()` — general-news endpoint, filtered to `"top news"` | done |
| 6.2 Folded into `check_for_ticker_updates()`/`/api/check-tickers`, own cache file `data/market_news.json` | done |
| 6.3 `page_template.py` — market-news section at the top of the Ticker Dashboard | done |

**Tests**
- Mocked general-news response renders the expected headlines at the top of the page
- A failed news fetch renders an empty/muted state without breaking the ticker tables below it
- The market-news section appears once per page load, not once per ticker/group

---

### Story 7 — In-App Ticker Editing

| Task | Status |
|---|---|
| 7.1 `ticker_dashboard.py` — `add_ticker_to_group`/`remove_ticker_from_group`, read-modify-write `config/tickers.json` | done |
| 7.2 `app.py` — `/api/tickers/add`/`/remove` routes | done |
| 7.3 `page_template.py` — remove button per row (row's trailing cell), add-ticker form per group, event-delegated JS | done |

**Tests**
- Add/remove correctly mutates the right group, preserves other groups and order, is idempotent
- Rejects a malformed symbol or unknown group without writing anything
- Route returns 400 with an error message on rejection, 200 on success

---

## Cross-Cutting / Integration

| Task | Status |
|---|---|
| I.1 `FINNHUB_API_KEY` added to local `.env`, read via `os.environ.get` | done |
| I.2 Manual end-to-end dry run: `/` instant render, background check patches sections or clears the indicator | done |
| I.3 Manual end-to-end dry run: `/tickers` with the real watchlist, per-row error state confirmed with a broken symbol | done |
| I.4 `data/indicators.json` working-tree diff after a background check limited to expected fields | done |

## Suggested Build Order
Dependency-driven:
1. Cross-Cutting Foundation
2. Extract `build_digest_content()` + persist `last_ai_response`
3. Story 1/1a — Indicator Digest Page
4. Story 2 — Ticker Watchlist Configuration
5. Story 3 — Ticker Dashboard Page
6. Story 4/5/6/7 — nav, instant load, market news, in-app editing
7. Cross-Cutting / Integration dry runs

---

## Epic: Hosted Live Dashboard (v2.1)

| Task | Estimate | Status |
|---|---|---|
| H.1 Add `gunicorn` to `requirements.txt`; confirm it can import `app.py` given the project's `sys.path.insert` convention (add a thin entry-point shim if not) | 1h | done — no shim needed, `gunicorn --chdir src/web app:app` (Section 11.5) |
| H.2 `app.py` — Basic Auth `before_request` hook gated on `DASHBOARD_USERNAME`/`DASHBOARD_PASSWORD` being set | 1h | done |
| H.3 `src/web/kv_store.py` — Upstash REST wrapper (`get_json`/`set_json`) | 1h | not started |
| H.4 `ticker_dashboard.py` — branch config/cache load+save through `kv_store.py` when `UPSTASH_REDIS_REST_URL` is set, else local files (unchanged path) | 2h | not started |
| H.5 Seed-on-first-read: Redis-backed `load_ticker_config()` initializes from the repo's `config/tickers.json` when the Redis key is empty | 1h | not started |
| H.6 Render setup: create the web service, connect the GitHub repo, enable auto-deploy on push to `main`, set all required env vars | 0.5h | not started |
| H.7 Tests (below) | 2h | partial — auth tests done (`tests/test_app.py`); kv_store/ticker_dashboard Redis tests pending Story 9 |
| **Subtotal** | **8.5h** | |

**Tests**
- Auth: a request with no/invalid credentials gets 401 when `DASHBOARD_USERNAME`/`PASSWORD` are set; unauthenticated access works when they're unset (local-dev default) — done, `tests/test_app.py`
- `kv_store`: mocked Upstash REST responses → `get_json`/`set_json` round-trip correctly; a non-200 response is surfaced as an error, not silently swallowed
- `ticker_dashboard`: with a mocked Redis backend configured, config load/save and cache read/write go through `kv_store` instead of the filesystem
- `ticker_dashboard`: with no Redis env vars set, behavior is identical to the existing local-file tests (regression)
- Seeding: first Redis read with an empty `ticker_config` key returns (and persists) the repo file's contents; a second read doesn't re-seed
- A simulated Redis outage during a cache read/write degrades to the existing pending/error states rather than raising past the caller

### Manual verification
- [ ] Hosted `/` and `/tickers` both prompt for credentials before rendering anything; wrong credentials are rejected
- [ ] An in-app ticker add/remove on the hosted deployment survives a manual restart of the Render service
- [ ] A push to `main` (e.g. a GitHub Actions ingestion commit) triggers an auto-redeploy and the hosted Indicator Digest Page reflects the new data
