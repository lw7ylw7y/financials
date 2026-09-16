# V1 Task Breakdown — Estimates & Test Plan

**Companion to:** investment_dashboard_requirements.md, v1_user_stories.md, v1_technical_design.md

---

## Story 1 — Indicator Data Ingestion

| Task | Estimate |
|---|---|
| 1.1 Repo scaffold (folders per Section 2 of tech design, `requirements.txt`, `README.md`) | 0.5h |
| 1.2 `fetch_fred.py` — FRED series-observations client | 2h |
| 1.3 Indicator config/mapping (name → FRED series ID + category, per Section 4 table) | 0.5h |
| 1.4 Ingestion loop with per-indicator try/except + structured logging | 1.5h |
| 1.5 Unit tests (below) | 2h |
| **Subtotal** | **6.5h** |

**Tests**
- Mock FRED response → correct value/date parsed and returned
- One indicator's mocked call raises an exception → other 7 still process, error is logged with indicator name + timestamp
- Re-running with an unchanged value → no duplicate processing triggered (per Story 1 AC)
- An older-dated or same-date-but-revised value (simulating a stale/cached FRED response) is ignored, not appended, and logged as a warning — only a strictly newer date is treated as new
- Each returned indicator record carries the correct category tag

---

## Story 2 — Historical Storage

| Task | Estimate |
|---|---|
| 2.1 `load_state()` / `save_state()` for `data/indicators.json` — extracted into `storage.py` | 1h |
| 2.2 Append-only history write (never overwrite existing entries) | 1h |
| 2.3 Query helper: get history by indicator + optional date range | 1h |
| 2.4 `trim_history()` — prune entries older than a rolling 12-month window on every append | 1h |
| 2.5 Tests (below) | 2h |
| **Subtotal** | **6h** |

**Tests**
- Write → reload from disk → data matches (persistence survives a fresh process)
- Writing a new value never mutates or removes prior history entries
- Query helper returns correct subset for a given date range
- Corrupted/missing JSON file on first run → initializes cleanly rather than crashing
- `trim_history()` keeps entries within the 12-month window and drops entries older than it, with an inclusive cutoff boundary
- `trim_history()` does not mutate its input list

---

## Story 3 — Release Calendar Tracking

| Task | Estimate |
|---|---|
| 3.1 FRED Releases API client — fetch next release date by `fred_release_id` | 1.5h |
| 3.2 Update `next_release_date` in stored state | 0.5h |
| 3.3 Tests (below) | 1h |
| **Subtotal** | **3h** |

**Tests**
- Mocked release-calendar response → correct next date stored
- Indicator with `fred_release_id: null` (e.g. yield curve spread) is skipped without error
- A changed date on refresh correctly overwrites the stored value (not appended/duplicated)

---

## Story 4/5/6 — Digest Email (Holistic AI + Table + Countdown)

One email, one module (`post_release.py`) — not three separately-shipped
features. `interpret.py`'s Gemini call reasons holistically across all 8
indicators in one call per run, `post_release.py` builds the table
(Story 5) and countdown (Story 6), and the send is throttled to a
weekly rollup — sent only when something's updated since the last
digest AND at least a week has passed since then.

| Task | Status |
|---|---|
| 4.1 New-value diff detection across all indicators (which updated this run) | done |
| 4.2 `interpret.py` — holistic Gemini call across all 8 indicators' 12-reading windows | done |
| 4.3 Sahm Rule calculation (unemployment) | done |
| 4.4 Yield curve inversion streak calculation | done |
| 4.9 Weekly send throttle — `last_digest_sent_at` persisted in `data/indicators.json`; gate on updates-since-last-digest (by `fetched_at`, not just "this run") AND a 7-day minimum interval | done |
| 5.1 Table builder — group indicators into Leading/Coincident/Lagging, pull latest/prior value + date from `history` | done |
| 6.1 Days-until-release calculation from `next_release_date`, highlight the single soonest release | done |
| 4.5/7.x Digest email template (subject + body: AI summary → table → countdown, per Section 7 of tech design) | done |
| 4.6 `send_email.py` — Gmail SMTP wrapper | done |
| 4.7 Graceful degradation: catch AI failure, send table+countdown without the AI section | done |
| 4.8/5.3/6.3 Tests (below) | done |

**Tests**
- At least one updated indicator since the last digest, and ≥7 days elapsed → one digest email is sent; either condition failing → no email sent
- An update that happened several ingestion ticks before the 7-day gate opens is still included in the eventual digest, not dropped for not having updated in the specific run that crossed the interval
- The very first digest ever (no `last_digest_sent_at` on file) sends immediately, without waiting a week
- Sending a digest updates `last_digest_sent_at`
- Mocked Gemini success → holistic summary + one overall directional read appear correctly in the email body, informed by all 8 indicators' history, not just the updated one(s)
- Mocked Gemini failure (after retries) → email still sends, AI section omitted, table + countdown present
- Disclaimer line is present whenever the AI section is included
- Sahm Rule value computed correctly against a known sample series
- Yield curve inversion streak counts consecutive negative readings correctly, resets on a positive reading
- Email body contains all 8 indicators under correct category headers, each with latest value, latest date, and prior value pulled from `history`
- Countdown math is correct for a known date (e.g. release in exactly 3 days → "in 3 days"); indicators with `next_release_date: null` are excluded, not shown as errors
- The single nearest release across all 8 indicators is correctly identified when release dates are mixed

---

## Cross-Cutting / Integration

| Task | Status |
|---|---|
| Workflow YAML (`.github/workflows/indicator-check.yml`) — schedule trigger (every 6h), `workflow_dispatch`, checkout, run, commit-back | done, commit-back later removed (see note below) |
| Secrets set on the repo (`gh secret set --env-file`, from local `.env`) — `FRED_API_KEY`, `GEMINI_API_KEY`, `GMAIL_ADDRESS`, `GMAIL_APP_PASSWORD`, `RECIPIENT_EMAIL` | done — `UPSTASH_REDIS_REST_URL`/`TOKEN` added later, v2.1/Story 11 |
| ~~Git commit-and-push step from within the workflow, with explicit `permissions: contents: write` so it doesn't depend on the repo's default token permission setting~~ | done at the time; **removed in v2.1 (Story 11)** — `data/indicators.json` moved to Redis (`docs/v2_technical_design.md` Section 11.7), so the workflow no longer touches git or needs `contents: write` at all |

End-to-end dry run against real FRED + Gemini + Gmail (not mocks) is done.

**Tests**
- [x] Full workflow run on a manual trigger (`workflow_dispatch`) completes without error against live APIs — secrets correctly masked, a real Gemini `503` was retried and succeeded, digest email sent
- [x] ~~Workflow correctly commits and pushes updated `indicators.json`~~ — true at the time; no longer applicable post-Story 11
- [ ] Scheduled trigger fires at the expected cron time — not yet verified; needs ≥24h of real elapsed time to observe in Actions run history

---

## Total Estimate

| Area | Hours | Status |
|---|---|---|
| Story 1 — Ingestion | 6.5h | done |
| Story 2 — Storage | 6h | done |
| Story 3 — Release Calendar | 3h | done |
| Story 4/5/6 — Digest Email (AI + table + countdown) | 10.5h | done |
| Cross-Cutting / Integration | 2.5h | done (pending 24h cron-timing observation) |
| **Total** | **~36.5h** | v1 functionally complete |

## Suggested Build Order
Dependency-driven, not just priority-driven — Stories 1-3 are prerequisites for everything else:
1. Story 1 (Ingestion) → 2. Story 2 (Storage) → 3. Story 3 (Release Calendar) → 4. Story 4/5/6 (Digest email: holistic AI + table + countdown) → Cross-Cutting integration/workflow wiring last, once the underlying script works standalone
