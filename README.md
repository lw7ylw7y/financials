# Investment Dashboard

See `docs/investment_dashboard_requirements.md` for the full spec, plus
`docs/v1_user_stories.md`/`docs/v1_technical_design.md`/`docs/v1_task_breakdown.md`
(v1, the digest email) and `docs/v2_user_stories.md`/`docs/v2_technical_design.md`/
`docs/v2_task_breakdown.md` (v2, the web dashboard).

## Story 1 — Indicator Data Ingestion (prototype)

`src/main.py` fetches the latest value for all 8 v1 indicators from FRED,
tags each with its category, skips values already seen, and logs
(without halting) any per-indicator fetch failure. Results are persisted
to `data/indicators.json`.

## Story 2 — Historical Storage

`src/storage/storage.py` persists ingestion results to `data/indicators.json` and
provides:

- `load_state()` / `save_state()` — read/write the JSON store, tolerating
  a missing or corrupted file by starting from an empty state
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
hours) regardless, keeping `data/indicators.json` fresh, but the digest
email itself is throttled to a **weekly rollup**
(`post_release.run_post_release`): sent only when at least one indicator
has a new value *since the last digest* (tracked via
`last_digest_sent_at`, persisted alongside `indicators` in
`data/indicators.json`) **and** at least 7 days have passed since then.
Several indicators (e.g. the yield curve spread) update daily and would
otherwise trigger near-constant emails; an update that lands between
digests is still included once the weekly gate opens, not dropped for
having happened outside the specific run that crossed the interval. The
digest contains:

- **Story 4 — AI summary:** one holistic Gemini call (`interpret.py`,
  `gemini-3.8-flash` — a free-tier model, chosen since this is a
  short, low-volume commentary task well within the free tier's limits)
  reasoning across *all 8* indicators' 12-reading history windows
  together, not one call per updated indicator — so it can connect
  indicators to each other (e.g. "unemployment ticked up while CPI
  cooled") rather than commenting on each in isolation. Uses a
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
Dashboard**, a Finnhub + Yahoo Finance–backed watchlist grouped by
asset type, with moving averages, 52-week range, and general market
news.

- `src/digest/build_digest_content.py` — the table/countdown/AI-assembly
  logic, shared by `post_release.py` (the weekly email) and
  `live_pull.py` (the page), so both build identical content from
  identical code. A successful AI call is persisted to
  `data/indicators.json`'s `last_ai_response` field.
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
- `src/web/ticker_dashboard.py` — reads `config/tickers.json`'s groups,
  fetches quote/52-week-range from Finnhub and daily closes from Yahoo
  per ticker (concurrently, `ThreadPoolExecutor`), computes moving
  averages and percent-off-high, and persists a snapshot cache
  (`data/tickers.json`) so `/tickers` renders instantly and refreshes
  live in the background.
- `src/web/app.py` — the Flask app: `GET /` and `GET /tickers` render
  instantly from stored data; `GET /api/check` and
  `GET /api/check-tickers` are what each page's inline `<script>` calls
  in the background, returning HTML fragments as JSON. Bound explicitly
  to `127.0.0.1` (never `0.0.0.0`) — no authentication layer, since the
  app is never network-reachable.

### Run it

```
pip install -r requirements.txt
set -a && source .env && set +a
python3 src/web/app.py
```

Then open `http://127.0.0.1:5000/`. Both pages render immediately from
stored data, then check for updates in the background.

**Known trade-off:** a background check that finds new indicator data
writes to the same `data/indicators.json` the GitHub Actions workflow
commits, leaving the file modified in your working tree until you
commit or discard it. Ingestion is idempotent (dedup by date), so this
is a working-tree diff, not a data-integrity issue.
