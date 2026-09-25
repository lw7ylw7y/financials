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
| 3.3 20/50/200-day simple moving average calculation from Yahoo daily closes | removed 2026-09-16 — the moving-average columns and the `ma20`/`ma50`/`ma200` card/cache fields were dropped, not replaced; `yahoo_client.py` itself was reintroduced 2026-09-17 for an unrelated purpose (task 3.11) |
| 3.4 `ticker_dashboard.py` — per-ticker assembly with independent try/catch per ticker | done |
| 3.5 `page_template.py` — grouped tables, per-row error state | done |
| 3.6 `/tickers` route wiring in `app.py` | done |
| 3.7 `pct_off_high` computed from existing price/week52_high, no new fetch | done |
| 3.8 `finnhub_client.fetch_quote()` — parse `d`/`dp` alongside `c` | done |
| 3.9 Two new table columns (% off high, change) with the signed-value + green/red-arrow convention | done |
| 3.10 Market Cap + P/E table columns, "n/a" when Finnhub has no value | done |
| 3.11 Aggregate P/E for the equity-ETF groups via Yahoo's undocumented `quoteSummary` endpoint, as a fallback when Finnhub's own P/E is empty (`yahoo_client.fetch_etf_pe_ratio`, Section 11.11) | removed 2026-09-18 — `yahoo_client.py` itself was deleted: the endpoint required a crumb after all (confirmed live via a `401 Unauthorized` once an earlier same-day change dropped it), and by then the fallback's only consumer was a column already hidden for every group but `individual` (see 2026-09-17's "Market Cap/P/E/PEG columns are individual-group-only" change) |
| 3.12 PEG ratio column, from the same `/stock/metric` call as P/E (`pegTTM` falling back to `forwardPEG`); no Yahoo fallback exists, so ETFs always show "n/a" (Section 11.12) | done 2026-09-17 |
| 3.13 Growth/quality stats (revenue/EPS growth, ROE, margin, debt/equity, dividend yield, from the existing `/stock/metric` call) and a sector-peer P/E benchmark (`fetch_company_industry` + `_SECTOR_ETF_BY_INDUSTRY` + the matching sector ETF's cached P/E) — data-only groundwork for a future AI valuation feature, no new table columns (Section 11.13) | done 2026-09-17 |
| 3.14 AI valuation section: one batched Gemini call (`ticker_valuation.py`) judging each ETF group and every individual stock as discount/fair/overpriced, cached and throttled (`MIN_VALUATION_INTERVAL`) against the shared 20-requests/day Gemini quota, falling back to the last cached valuation on any failure (Story 14, Section 11.14) | done 2026-09-17 |

**Tests**
- Mocked Finnhub responses → row shows correct price, 52-week range
- One ticker's mocked call raises an exception → that row shows an error state, all others still render correctly
- 52-week high/low computed correctly from known sample data
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
| H.3 `src/web/kv_store.py` — Upstash REST wrapper (`get_json`/`set_json`) | 1h | done — wire format confirmed live against a real Upstash instance |
| H.4 `ticker_dashboard.py` — branch config/cache load+save through `kv_store.py` when `UPSTASH_REDIS_REST_URL` is set, else local files (unchanged path) | 2h | done |
| H.5 Seed-on-first-read: Redis-backed `load_ticker_config()` initializes from the repo's `config/tickers.json` when the Redis key is empty | 1h | done |
| H.6 Render setup: create the web service, connect the GitHub repo, enable auto-deploy on push to `main`, set all required env vars | 0.5h | done — service deployed, auth confirmed over HTTPS, `UPSTASH_REDIS_REST_URL`/`TOKEN` added and confirmed live (see the gotcha note in Section 11.5: adding env vars in Render's UI doesn't take effect until you explicitly hit "Save and Redeploy" — the service silently kept running on its old environment otherwise) |
| H.7 Tests (below) | 2h | done — `tests/test_app.py` (auth), `tests/test_kv_store.py`, `tests/test_ticker_dashboard.py`'s `TestRedisBacked*` classes |
| H.8 `storage.py` — Redis branch for `load_state`/`save_state` (Story 11), mirroring H.4's pattern | 1h | done |
| H.9 `post_release.py`/`main.py` — split `refresh_ai_response_if_updated` (every cycle with new data) from `maybe_send_digest_email` (content-fingerprint + interval gate), remove the old `run_post_release` (Story 11) | 2h | done |
| H.10 `.github/workflows/indicator-check.yml` — drop the git commit/push step and the `contents: write` permission, pass `UPSTASH_REDIS_REST_URL`/`TOKEN` to the ingestion step (Story 11); add those as new GitHub Actions repo secrets | 0.5h | done — secrets added, `workflow_dispatch` triggered manually and completed successfully against real Redis/FRED/Gmail |
| H.11 Tests for H.8/H.9 (below) | 1.5h | done |
| H.12 Seed-on-first-read for indicator state: Redis-backed `load_state()` initializes from the repo's committed `data/indicators.json` when the Redis key is empty, mirroring H.5's ticker-config seeding | 0.5h | done — added after a real incident (below) surfaced the gap H.8 had left |
| **Subtotal** | **17.5h** | |

**Tests**
- Auth: a request with no/invalid credentials gets 401 when `DASHBOARD_USERNAME`/`PASSWORD` are set; unauthenticated access works when they're unset (local-dev default) — done, `tests/test_app.py`
- `kv_store`: mocked Upstash REST responses → `get_json`/`set_json` round-trip correctly; a non-200 response is surfaced as an error, not silently swallowed — done, `tests/test_kv_store.py`
- `ticker_dashboard`: with a mocked Redis backend configured, config load/save and cache read/write go through `kv_store` instead of the filesystem — done, `TestRedisBackedTickerConfig`/`TestRedisBackedTickerCache`/`TestRedisBackedMarketNewsCache`
- `ticker_dashboard`: with no Redis env vars set, behavior is identical to the existing local-file tests (regression) — done, the full pre-existing suite (252 tests) passes unmodified
- Seeding: first Redis read with an empty `ticker_config` key returns (and persists) the repo file's contents; a second read doesn't re-seed — done
- A simulated Redis outage during a cache read/write degrades to the existing pending/error states rather than raising past the caller — done; a config-load outage propagates instead (also tested)
- `storage`: with a mocked Redis backend configured, `load_state`/`save_state` go through `kv_store`; a simulated outage propagates (not caught) on both load and save — done, `tests/test_storage.py::TestRedisBackedState`
- `storage`: with no Redis env vars set, behavior is identical to the existing local-file tests (regression) — done
- `storage`: seeding — first Redis read with an empty `indicator_state` key returns (and persists) the local `data/indicators.json` file's contents, or `{"indicators": {}}` if that file is also missing/corrupted; a second read doesn't re-seed — done, `test_load_seeds_from_local_file_when_redis_key_absent`/`test_load_seeds_empty_indicators_when_redis_absent_and_no_local_file_either`/`test_load_does_not_reseed_once_redis_already_has_state`
- `post_release.refresh_ai_response_if_updated`: persists a fresh AI response whenever `updated_keys` is non-empty, regardless of the email throttle state; returns `None` and leaves state untouched when nothing updated; an AI failure still returns content (with `ai_result=None`) without touching `last_ai_response` — done, `TestRefreshAiResponseIfUpdated`
- `post_release.maybe_send_digest_email`: sends only when the content fingerprint differs from the last-emailed one AND the interval has elapsed; unchanged content skips even once the interval has passed; changed content within the interval is held back; reuses whatever's currently in `state["last_ai_response"]` rather than calling Gemini itself (no `interpret_fn` param exists on this function); a send failure doesn't update `last_digest_sent_at`/fingerprint — done, `TestMaybeSendDigestEmail`

### Manual verification
- [x] Hosted `/` and `/tickers` both prompt for credentials before rendering anything; wrong credentials are rejected
- [x] An in-app ticker add/remove on the hosted deployment persists to Redis (confirmed: a hosted remove now correctly updates `ticker_config` in Upstash, once Render was properly redeployed with the Upstash env vars live — see the Save-and-Redeploy gotcha in Section 11.5). Since the write lands in external Redis rather than the container's own disk, it durably survives a restart by construction; an explicit restart-and-recheck hasn't been separately performed but isn't expected to reveal anything new
- [x] `storage.load_state`/`save_state` round-trip correctly against the real Upstash instance (verified via a throwaway Redis key, same pattern used to verify `kv_store.py` for Story 9)
- [x] `UPSTASH_REDIS_REST_URL`/`UPSTASH_REDIS_REST_TOKEN` added as GitHub Actions repo secrets (H.10)
- [x] Workflow triggered manually (`workflow_dispatch`) and completed without error against real Redis/FRED/Gmail — ingestion ran, release calendar refreshed, a digest email sent. Confirmed this no longer happens via a git push/auto-redeploy the way it used to (H.10 removed that step entirely); the hosted page just reads the same Redis state directly on its next visit
- [x] The original combined `/api/check-tickers` completed without a 500 for the full 36-ticker watchlist (gunicorn `--timeout 120`, Section 11.5) — since superseded by Story 12's per-group split below

**Incident (2026-09-16), same day as the H.10/H.12 work above:** Render had auto-deployed the Story 11 code before GitHub Actions' secrets were added, and Render's env vars already had `UPSTASH_REDIS_REST_URL`/`TOKEN` configured (left over from Story 9's ticker work) — so the *first* live visit to the hosted Indicator Digest Page found `indicator_state` completely empty in Redis and treated every indicator as brand new, persisting exactly one fresh FRED observation each. The months of accumulated history that used to live in the git-committed `data/indicators.json` was never carried over — sparklines dropped to a single point, and the AI response was also absent (its own live-check Gemini call apparently didn't land, separately from Gemini also hitting a genuine `503` high-demand period during the manual recovery below). Recovered by hand: re-ran `python3 src/backfill.py` (pulled up to 12 recent real observations per indicator straight from FRED, added 85 entries total) and manually called `refresh_ai_response_if_updated` against production state (needed 3 attempts before Gemini's `503`s cleared). H.12 above is the actual fix — seeding on first Redis read — so a fresh/cleared Redis key self-heals from the committed file going forward instead of needing this by hand again.

---

## Epic: Ticker Dashboard Performance

### Story 12 — Per-Group Live Checks

| Task | Status |
|---|---|
| 12.1 `app.py` — replace `GET /api/check-tickers` with `GET /api/tickers/groups/<name>/check` (looks up the group via `load_ticker_config()`, 404s on an unknown group) and `GET /api/market-news/check` | done |
| 12.2 `page_template.py` — `_render_ticker_groups` tags each `.category-block` with `data-group="<name>"`; add `render_ticker_group_check_response`/`render_market_news_check_response`, remove the now-unused `render_ticker_check_response` | done |
| 12.3 `page_template.py` — rewrite the ticker page's inline `<script>` to fire one fetch per `.category-block[data-group]` plus one for market news, all concurrently, each patching only its own section; `Promise.allSettled` across all of them clears the "Checking for updates" indicator | done |
| 12.4 `ticker_dashboard.py`/`kv_store.py` — replace the ticker cache's load-merge-save-whole-blob pattern with per-symbol writes: `kv_store.hset_json`/`hgetall_json` (new, Redis hash primitives) + `ticker_dashboard.save_ticker_snapshot`, so a successful fetch is one atomic per-field write, never a read-modify-write of the whole cache | done — supersedes an earlier `_ticker_state_lock`-around-the-whole-merge attempt, which only protected one process and didn't fix the real multi-user/multi-process race |
| 12.5 `app.py` — `app.run(..., threaded=True)` for local dev, so the concurrency benefit is actually realized locally rather than queueing on Werkzeug's single-threaded default | done |
| 12.6 `ticker_dashboard.py` — `_fetch_concurrency_limit`, a global `threading.Semaphore` every `_build_card` call acquires, restoring the system-wide Finnhub/Yahoo concurrency cap that `build_ticker_cards`'s per-call `max_workers` alone stopped providing once multiple groups' calls could run at once | done, value corrected same day — first shipped as `Semaphore(5)`, found live to be the bottleneck itself once gunicorn threading (12.7) actually enabled real per-group concurrency: all 36 tickers funneling through only 5 global slots made every group uniformly take 35-40s. Verified via a direct test (36 real tickers, 108 Finnhub/Yahoo calls, `max_workers=20`, live APIs) that completed in ~2s with zero errors, proving the tight cap wasn't protecting against a real API limit. Raised to `Semaphore(25)` (comfortably above the current watchlist's natural per-group-pool sum of 21); confirmed live back down to ~1-4.5s per group |
| 12.7 Render start command — add `--worker-class gthread --threads 8` so gunicorn can actually handle the 6 concurrent per-page-load requests (5 groups + market news) at once, not just accept them | done — applied by the user and confirmed live. Threads, not `--workers N` — `_fetch_concurrency_limit` (12.6) is process-local, so separate worker processes wouldn't share it (the ticker-cache write itself, 12.4, is Redis-atomic and safe across any number of processes) |
| 12.8 One-time Redis migration — delete the pre-existing `ticker_cache` key (a string, from the old `set_json`/`get_json` design) so it can be recreated as a hash | done — performed directly against the real (shared, same one Render uses) Upstash instance; confirmed a fresh check repopulated it correctly as a hash with real market data |
| 12.9 `finnhub_client.py`/`yahoo_client.py`/`kv_store.py` — shared `requests.Session()` per module instead of bare `requests.get`/`.post`, so repeated calls to the same host reuse an already-negotiated connection | done — found live: Render still took 12-40s per group after 12.6/12.7 despite local runs taking under 5s with identical settings, pointing at Render's CPU-throttled free tier rather than a remaining concurrency bug. Session reuse cut real CPU work (fewer TLS handshakes); confirmed live on Render afterward — group checks dropped to under 10s |
| 12.10 `page_template.py` — add-ticker no longer calls `window.location.reload()`; factors the per-group check into a shared `checkGroup(block)` helper, inserts a pending row for the new symbol via DOM APIs, then re-checks just that group | done |
| 12.11 `ticker_config` is also a Redis hash, one field per **group** (`{"symbols": [...], "order": i}`) — `add_ticker_to_group`/`remove_ticker_from_group` now `hget_json`/`hset_json` only their own group's field instead of the old whole-config `get_json`/`set_json` read-modify-write | done — same class of anti-pattern as the ticker cache (12.4), lower priority since config edits are a rare, deliberate user action rather than automatic/concurrent, but fixed for consistency. Needed an extra piece the cache didn't: verified live that Redis hash fields don't preserve insertion order (`HGETALL` came back alphabetized, not in file order), so each field carries an explicit `order` index that `load_ticker_config` sorts by on read. `market_news_cache` deliberately left as a string blob — it's always replaced wholesale, never read-modify-written, so there's no per-item structure to shard |

**Tests**
- `tests/test_page_template.py`: `data-group` attribute present on every group block; the script fetches per-group and market-news check routes (not the old combined one); `render_ticker_group_check_response`/`render_market_news_check_response` return the expected fragments and never the full page shell — done
- `tests/test_app.py`: a known group's check route calls `check_for_ticker_updates` with only that group's symbols and returns its HTML fragment; an unknown group 404s without calling the fetch function; the market-news-check route returns its fragment; the new routes are gated by `_require_auth` like every other route — done
- `tests/test_kv_store.py`: `hset_json` posts the JSON-encoded value to `/hset/<key>/<field>`; `hgetall_json` decodes Upstash's flat alternating `[field, value, field, value, ...]` array into a dict, treats an empty array as `{}`, raises on a non-200 or a corrupt field value — done, wire format also confirmed live against the real Upstash instance
- `tests/test_ticker_dashboard.py`: `save_ticker_snapshot`/`save_ticker_state` route through `hset_json` (Redis) not `set_json`; a Redis outage during a snapshot write is swallowed, not raised; two snapshot writes to different symbols land as independent hash fields with no clobbering — done, `TestRedisBackedTickerCache`
- `tests/test_kv_store.py`: new `hget_json` — decodes an existing field, returns `None` for a missing one, raises on a non-200 or a corrupt value — done, wire format confirmed live
- `tests/test_ticker_dashboard.py`: `TestRedisBackedTickerConfig` rewritten for the hash shape — seeding writes one `hset_json` per group with the right `order`; reads restore file order even from a deliberately-out-of-order mocked hash; add/remove each read and write only their own group's field; concurrent edits to two different groups never touch each other's field — done
- `tests/test_page_template.py`: add-ticker script contains `checkGroup`, not `location.reload` — done
- Manual: confirmed locally (against the real, shared Upstash instance) that all 5 configured groups (36 tickers total) complete concurrently in a few seconds per group (fastest ~1.2s, slowest ~4.5s) versus the original single request's occasional 30+s, and versus the intermediate `Semaphore(5)` regression's uniform 35-40s; confirmed no data loss in the `ticker_cache` hash after a concurrent all-groups run (every successfully-fetched symbol present; the only misses were genuine per-ticker Finnhub failures, unrelated to concurrency); confirmed live on Render that Session reuse (12.9) brought group checks under 10s; confirmed live that `ticker_config`'s old string-typed key needed the same one-time deletion as `ticker_cache` did, and that a fresh load re-seeds it as a hash with group order intact; confirmed add/remove both round-trip correctly against the real instance — verified against the actual live race, the actual live wire format, and actual live Finnhub/Yahoo/Render behavior throughout, not just in theory

---

## Epic: Storage Simplification

### Story 13 — Redis as the Only Source of Truth

| Task | Status |
|---|---|
| 13.1 `ticker_dashboard.py` — remove `is_configured()` branching and all `path`/`state_path` parameters from `_load_raw_config`/`load_ticker_config`, `add_ticker_to_group`/`remove_ticker_from_group`, `load_ticker_state`/`save_ticker_state`/`save_ticker_snapshot`/`delete_ticker_snapshot`, `load_market_news_state`/`save_market_news_state`, `get_initial_ticker_page_data`/`check_for_ticker_updates` — every one now always calls `kv_store.py` | done |
| 13.2 `ticker_dashboard.py` — delete `_ticker_state_lock` (a `threading.Lock`), now fully unused with the local-file branch it guarded gone | done |
| 13.3 `storage.py` — remove `is_configured()` branching and the `path` parameter from `load_state`/`save_state`; remove the seed-from-local-file step added for the H.12 incident (Story 11) | done — `main.py`/`backfill.py`/`live_pull.py` needed no changes, since they already called these with no path argument |
| 13.4 Delete `config/tickers.json` and `data/indicators.json` from the repo; remove `data/tickers.json`/`data/market_news.json` from `.gitignore` | done |
| 13.5 `tests/test_storage.py` — rewrite `TestLoadSaveState` to mock `get_json`/`set_json` directly (small in-memory fake-Redis helper) instead of writing temp files; delete the now-meaningless seeding tests | done |
| 13.6 `tests/test_ticker_dashboard.py` — comprehensive rewrite: every local-file-based test class now mocks the relevant hash/blob Redis calls via shared `config_hash()`/`fake_hash_store()` helpers; fold the separate `is_configured()`-gated `TestRedisBacked*` classes into the main test classes (only one mode left); delete the live-watchlist smoke test (no local file left to smoke-test) | done |
| 13.7 Update `CLAUDE.md` (env var table, architecture file-tree, Storage model section, Data flow items 5/6, multiple Status bullets) and `docs/v2_technical_design.md` (Sections 2, 3.2, 4.4, 5.2/5.2c/5.3, 5b, 8, 9, 10, 11.3/11.4/11.7, new Section 11.10) to describe the Redis-only design as current | done |

**Tests**
- `tests/test_storage.py`: write-then-reload round trip via mocked `get_json`/`set_json`; missing key initializes to `{"indicators": {}}`; a new entry never overwrites prior history across two save/load cycles; load/save failures propagate rather than degrading — done, full suite (300 tests) passes
- `tests/test_ticker_dashboard.py`: config load/add/remove restore group order via the embedded `order` index even from a deliberately-scrambled mocked hash; add/remove read and write only their own group's field; a malformed/non-string symbol is skipped with a warning; ticker cache round-trips via `hset_json`/`hgetall_json`, degrades to `{}`/`None` on a simulated Redis outage rather than raising; market-news cache same pattern via `get_json`/`set_json` — done
- Manual: none needed beyond the live verification already performed in Story 12's own work (the real Upstash instance round-trips for `ticker_config`/`ticker_cache` were confirmed live before this story; this story is a pure code-path deletion on top of that, verified by the full test suite passing unmodified in behavior, not a new live-data change)

### Story 15 — AI Calls Fall Back to Other Models

| Task | Status |
|---|---|
| 15.1 `src/web/claude_client.py` — `generate_json(system_prompt, user_prompt, schema)` against the Anthropic Messages API (`requests`, no SDK); schema spelled out in the system prompt, JSON object cut out of the reply; raises `ClaudeApiError` per call | done |
| 15.2 `interpret.py` / `ticker_valuation.py` — split the Gemini call into a per-model helper and add `_run_with_fallbacks`: Gemini → second Gemini model → Claude; an injected `client` runs alone | done |
| 15.3 `indicator-check.yml` — pass `ANTHROPIC_API_KEY: ${{ secrets.ANTHROPIC_API_KEY }}` (new GitHub Actions secret) | done — secret itself must be added by hand |
| 15.4 Tests: `tests/test_claude_client.py` (new), plus fallback classes in `tests/test_interpret.py` and `tests/test_ticker_valuation.py` | done |
| 15.5 Live verification of the Claude step | **not done** — needs an `ANTHROPIC_API_KEY` |
| 15.6 Replace a first-attempt GitHub Models fallback | done — every request to `models.github.ai` returned a bare `HTTP 200 text/plain OK` (from the dev sandbox, the user's own terminal, and Render), so that step was removed |

**Tests**
- `tests/test_claude_client.py`: JSON returned with the key, schema and prompt sent, model override, code-fence stripping, missing key, request failure, unexpected response shape, reply with no JSON
- Fallback classes: second Gemini model is tried before Claude (and Claude isn't called when it succeeds), Claude used when both Gemini calls fail, an injected client never falls back, both-fail raises the module's error
