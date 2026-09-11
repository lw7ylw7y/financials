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

## Story 4 — Post-Release Email with AI Interpretation

For every indicator `run_ingestion` marks `"updated"`, `post_release.run_post_release`
builds a value diff (new/prior value, date, absolute and % change), asks
Gemini (`gemini-3.8-flash`, a free-tier model — chosen since this is a
short, low-volume commentary task well within the free tier's limits) for
a plain-English summary + bullish/bearish/neutral directional read
(`interpret.py`, using a 12-reading history window plus a pre-computed
heuristic — Sahm Rule for unemployment, inversion streak for the yield
curve spread; both in `heuristics.py`), and sends the result via Gmail
SMTP (`send_email.py`). If the AI call fails, the email still sends with
just the raw data — the AI section (and its disclaimer line) is simply
omitted. A failed send for one indicator is logged and doesn't block the
others. Requires `GMAIL_ADDRESS`, `GMAIL_APP_PASSWORD`, `RECIPIENT_EMAIL`,
and `GEMINI_API_KEY` env vars to actually send.

### Run it

```
pip install -r requirements.txt
export FRED_API_KEY=your_key_here          # https://fred.stlouisfed.org/docs/api/api_key.html
export GEMINI_API_KEY=your_key_here        # https://ai.google.dev/gemini-api/docs/api-key (free tier)
export GMAIL_ADDRESS=you@gmail.com         # for Story 4's post-release email
export GMAIL_APP_PASSWORD=your_app_password
export RECIPIENT_EMAIL=you@gmail.com
python3 src/main.py
```

Only `FRED_API_KEY` is required for ingestion (Stories 1-3) to run; the
`GEMINI_API_KEY`/`GMAIL_*`/`RECIPIENT_EMAIL` vars are only needed to
actually send post-release emails (Story 4) — a missing one raises a
logged, per-indicator error rather than crashing the run.

### Test it

```
python3 -m unittest discover -s tests -v
```

No network calls in tests — `fetch_fred.requests.get`, the Gemini API
client, and `smtplib.SMTP` are all mocked, and `run_ingestion` is
exercised with a fake `fetch_fn`.
