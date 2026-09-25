# Investment Dashboard

See `docs/investment_dashboard_requirements.md` for the full spec, plus
`docs/v1_user_stories.md`/`docs/v1_technical_design.md`/`docs/v1_task_breakdown.md`
(v1, the digest email) and `docs/v2_user_stories.md`/`docs/v2_technical_design.md`/
`docs/v2_task_breakdown.md` (v2, the web dashboard).

## Story 1 — Indicator Data Ingestion (prototype)

`src/main.py` fetches the latest value for all 8 v1 indicators from FRED,
tags each with its category, skips values already seen, and logs
(without halting) any per-indicator fetch failure. Results are persisted
to Redis (the `indicator_state` key).

## Story 2 — Historical Storage

`src/storage/storage.py` persists ingestion results to Redis and
provides:

- `load_state()` / `save_state()` — read/write the store via `src/web/kv_store.py`
  (Upstash's REST API), tolerating a missing key by starting from an
  empty state. Redis-backed unconditionally — `UPSTASH_REDIS_REST_URL`/
  `TOKEN` must be set wherever this runs, local dev included; there is
  no local-file fallback (removed 2026-09-16 once it became clear local
  dev and any hosted deployment always share the same live Redis in
  practice anyway)
- `query_history(state, key, start_date=None, end_date=None)` — an
  indicator's history, optionally filtered to an inclusive date range
- `trim_history(history)` — drops entries older than a rolling 12-month
  window; called on every append in `main.run_ingestion` so the store
  doesn't grow unbounded

History is append-only — a new reading is always added, never overwrites
a prior entry.

## Story 3 — Release Calendar Tracking

`fetch_fred.fetch_next_release_date(release_id)` calls FRED's
release/dates endpoint and returns the earliest scheduled date on or
after today for a given release. `main.update_release_calendar(state)`
refreshes `next_release_date` for every indicator that has a
`fred_release_id` (continuously-updated series like the yield curve
spread don't have one and are skipped); it's called from `main()`
alongside ingestion, overwriting the stored value rather than
appending — it's a single current value, not a history.

## Story 4/5/6 — The Digest Email (AI Interpretation, Table, Countdown)

v1's only product surface is one email — there is no webpage/dashboard.
Ingestion (`run_ingestion`) runs on every scheduled check (every 6
hours) regardless, keeping indicator state fresh in Redis. As of v2.1
(Story 11), the AI response is refreshed on that same cadence too
(`post_release.refresh_ai_response_if_updated`) — no throttle — while
the digest email itself stays throttled to a **weekly rollup**
(`post_release.maybe_send_digest_email`): sent only when the digest's
actual content has meaningfully changed since the last send (a
fingerprint of every indicator's latest value/date plus the AI's
directional read, deliberately ignoring the free-text summary's
wording) **and** at least 7 days have passed since then.
`maybe_send_digest_email` never calls Gemini itself — it only reuses
whatever the refresh step most recently persisted, so the two can't
double-call it in the same cycle. Several indicators (e.g. the yield
curve spread) update daily and would otherwise trigger near-constant
emails; an update that lands between digests is still named in the
email's subject once the weekly gate opens
(`post_release.indicators_updated_since`), not dropped for having
happened outside the specific run that crossed the interval. The
digest contains:

- **Story 4 — AI summary:** one holistic Gemini call (`interpret.py`,
  `gemini-3.8-flash` — a free-tier model, chosen since this is a
  short, low-volume commentary task well within the free tier's limits)
  reasoning across *all 8* indicators' 12-reading history windows
  together, not one call per updated indicator — so it can connect
  indicators to each other (e.g. "unemployment ticked up while CPI
  cooled") rather than commenting on each in isolation. If the Gemini
  call fails, the same prompt is retried on a second Gemini model
  (`GEMINI_FALLBACK_MODEL`), before the digest
  falls back to no AI section. Uses a
  pre-computed heuristic where applicable — Sahm Rule for unemployment,
  inversion streak for the yield curve spread (`heuristics.py`) — and
  retries up to 3 times (via the SDK's built-in `HttpRetryOptions`) on
  transient failures like a `503`. If the AI call still fails, the email
  sends anyway without the AI section (and its disclaimer line).
- **Story 5 — table:** every indicator's latest/prior value and date,
  grouped by Leading/Coincident/Lagging (`post_release.build_table`),
  each row including a small trend sparkline (`sparkline.py`, rendered
  as a PNG via matplotlib — Gmail strips inline `<svg>` from HTML
  email, so a raster image embedded via `Content-ID` is the reliable
  option).
- **Story 6 — countdown:** days until each indicator's next release
  (Story 3's `next_release_date`), with the single soonest release
  called out distinctly (`post_release.build_countdown`). Indicators
  whose FRED release doesn't actually reflect their own update cadence
  (Fed Funds Rate's mapped release, H.15, publishes near-daily — not
  specific to the monthly series we track) have no `fred_release_id`
  and are excluded, same as the continuously-updating yield curve
  spread.

Sent as `multipart/alternative` via Gmail SMTP (`send_email.py`) — a
styled HTML body (`email_template.py`) most clients render, plus a
plain-text fallback. Requires `GMAIL_ADDRESS`, `GMAIL_APP_PASSWORD`,
`RECIPIENT_EMAIL`, and `GEMINI_API_KEY` env vars to actually send.

### Run it

```
pip install -r requirements.txt
export FRED_API_KEY=your_key_here          # https://fred.stlouisfed.org/docs/api/api_key.html
export GEMINI_API_KEY=your_key_here        # https://ai.google.dev/gemini-api/docs/api-key (free tier)
export GMAIL_ADDRESS=you@gmail.com         # for the digest email
export GMAIL_APP_PASSWORD=your_app_password
export RECIPIENT_EMAIL=you@gmail.com
python3 src/main.py
```

Only `FRED_API_KEY` is required for ingestion (Stories 1-3) to run; the
`GEMINI_API_KEY`/`GMAIL_*`/`RECIPIENT_EMAIL` vars are only needed to
actually send the digest email — a missing one raises a logged error
rather than crashing the run.

### Backfill (one-time, not part of the scheduled run)

```
python3 src/backfill.py
```

Seeds each indicator's `history` with FRED's last ~12 real observations,
for when the local store is too sparse (e.g. right after this project
started) for the AI to read a real trend from. Safe to re-run — only
adds observations for dates not already on file, never overwrites or
duplicates existing entries.

### Test it

```
python3 -m unittest discover -s tests -v
```

No network calls in tests — `fetch_fred.requests.get`, the Gemini API
client, and `smtplib.SMTP` are all mocked, and `run_ingestion` is
exercised with a fake `fetch_fn`.

## V2 — Web Dashboard

See `docs/investment_dashboard_requirements.md` (Section 4),
`docs/v2_user_stories.md`, and `docs/v2_technical_design.md` for the
full spec. Two local-only web pages (no domain, no login, never
reachable outside your machine): the **Indicator Digest Page**, which
shows the same content as the digest email — holistic AI
interpretation, indicator table, next-release countdown — refreshable
on demand instead of waiting for the next email; and the **Ticker
Dashboard**, a Finnhub-backed watchlist grouped by
asset type, with 52-week range and general market
news.

- `src/digest/build_digest_content.py` — the table/countdown/AI-assembly
  logic, shared by `post_release.py` (the weekly email) and
  `live_pull.py` (the page), so both build identical content from
  identical code. A successful AI call is persisted to the
  `indicator_state` Redis key's `last_ai_response` field.
- `src/web/live_pull.py` — `get_initial_page_data()` builds the
  Indicator Digest Page entirely from stored data (no network calls);
  `check_for_updates()`, called by the page's own background script,
  does the real FRED pull. Nothing new (or a failed check) costs a FRED
  call but never a Gemini call; only a genuinely new value triggers a
  release-calendar refresh, a fresh AI interpretation, and a save. The
  table and the AI section carry independent freshness.
- `src/web/page_template.py` — HTML rendering for both pages (plain
  string-building, matching `mailer/email_template.py`'s convention).
  Each Indicator Digest Page row gets an inline-SVG trend sparkline. A
  "Checking for updates..." indicator shows for the duration of each
  page's background check.
- `src/web/ticker_dashboard.py` — reads the `ticker_config` Redis hash's
  groups, fetches quote/52-week-range/market-cap/P-E/PEG from Finnhub
  per ticker (concurrently, `ThreadPoolExecutor`), computes
  percent-off-high. Finnhub has no fund-level P/E/PEG/market cap, so
  those are always "n/a" for an ETF group (a Yahoo-based P/E fallback
  was tried and removed as unreliable). Also
  gathers a sector-peer P/E benchmark and growth/quality stats per
  individual-stock ticker, feeding `src/web/ticker_valuation.py`'s AI
  valuation section — one batched Gemini call per refresh (not one per
  ticker, given the free tier's 20-requests/day cap) judging every ETF
  group and individual stock as discount/fair/overpriced, shown at the
  top of `/tickers`, cached and throttled (`MIN_VALUATION_INTERVAL`)
  and falling back to the last cached read on any AI failure. Persists
  a snapshot cache (the `ticker_cache` Redis hash) so `/tickers`
  renders instantly and refreshes live in the background. The
  watchlist and both caches read/write
  through `src/web/kv_store.py` (Upstash Redis) unconditionally — there
  is no local-file fallback; `UPSTASH_REDIS_REST_URL`/`TOKEN` must be
  set wherever this runs, local dev included.
- `src/web/app.py` — the Flask app: `GET /` and `GET /tickers` render
  instantly from stored data; `GET /api/check` is what the Indicator
  Digest Page's inline `<script>` calls in the background. The Ticker
  Dashboard's script instead calls one `GET /api/tickers/groups/<name>/check`
  per group plus `GET /api/market-news/check`, all concurrently, so a
  smaller group repaints before a larger one finishes instead of the
  whole page waiting on one combined request. Every one of these
  returns an HTML fragment as JSON. Bound explicitly
  to `127.0.0.1` (never `0.0.0.0`) for local dev. Every route (including
  the `/api/*` ones) sits behind an HTTP Basic Auth gate when
  `DASHBOARD_USERNAME`/`DASHBOARD_PASSWORD` are both set (for a hosted
  deployment); with neither set, as in local dev, auth is a no-op.

### Run it

```
pip install -r requirements.txt
set -a && source .env && set +a
python3 src/web/app.py
```

Then open `http://127.0.0.1:5000/`. Both pages render immediately from
stored data, then check for updates in the background.

Indicator state, the ticker watchlist, and both ticker/news caches all
live in Redis only (`UPSTASH_REDIS_REST_URL`/`TOKEN` in your `.env`) —
there's no local file for any of them, so a background check that finds
new data just writes straight to the same Redis instance both your
local run and any hosted deployment share (see
`docs/v2_technical_design.md` Section 11.10). Ingestion is idempotent
(dedup by date either way).
