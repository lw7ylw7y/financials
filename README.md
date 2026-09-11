# Investment Dashboard

See `investment_dashboard_requirements.md`, `v1_user_stories.md`, `v1_technical_design.md`, and `v1_task_breakdown.md` for the full spec.

## Story 1 — Indicator Data Ingestion (prototype)

`src/main.py` fetches the latest value for all 8 v1 indicators from FRED,
tags each with its category, skips values already seen, and logs
(without halting) any per-indicator fetch failure. Results are persisted
to `data/indicators.json`.

## Story 2 — Historical Storage

`src/storage.py` persists ingestion results to `data/indicators.json` and
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
  grouped by Leading/Coincident/Lagging (`post_release.build_table`).
- **Story 6 — countdown:** days until each indicator's next release
  (Story 3's `next_release_date`), with the single soonest release
  called out distinctly (`post_release.build_countdown`).

Sent via Gmail SMTP (`send_email.py`). Requires `GMAIL_ADDRESS`,
`GMAIL_APP_PASSWORD`, `RECIPIENT_EMAIL`, and `GEMINI_API_KEY` env vars to
actually send.

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
