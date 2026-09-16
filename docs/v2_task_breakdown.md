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
| 12.4 `ticker_dashboard.py` — wrap `check_for_ticker_updates`'s load-merge-save of the shared ticker cache in a process-local `_ticker_state_lock`, held only around the merge/save (not the network fetch), so concurrent per-group calls can't clobber each other's freshly-fetched values | done |
| 12.5 `app.py` — `app.run(..., threaded=True)` for local dev, so the concurrency benefit is actually realized locally rather than queueing on Werkzeug's single-threaded default | done |
| 12.6 Render start command — add `--worker-class gthread --threads 8` so gunicorn can actually handle the 6 concurrent per-page-load requests (5 groups + market news) at once, not just accept them | **pending** — found live: without this, gunicorn's default single sync worker queues the requests and the slowest ends up waiting ~35s behind the others, negating the split's benefit on Render even though the app code and local dev are both correct. Threads, not `--workers N` — see Section 11.5/11.8's reasoning on `_ticker_state_lock` being process-local. Same "Save, rebuild, and deploy" gotcha as any other Render start-command/env-var change (Section 11.5) |

**Tests**
- `tests/test_page_template.py`: `data-group` attribute present on every group block; the script fetches per-group and market-news check routes (not the old combined one); `render_ticker_group_check_response`/`render_market_news_check_response` return the expected fragments and never the full page shell — done
- `tests/test_app.py`: a known group's check route calls `check_for_ticker_updates` with only that group's symbols and returns its HTML fragment; an unknown group 404s without calling the fetch function; the market-news-check route returns its fragment; the new routes are gated by `_require_auth` like every other route — done
- Manual: confirmed locally that all 5 configured groups (36 tickers total) complete concurrently in ~3s total (worst single group ~2.6s) versus the original single request's occasional 30+s; confirmed no data loss in `data/tickers.json` after a concurrent all-groups run (all 36 symbols present) — the lock fix verified against the actual race, not just in theory
