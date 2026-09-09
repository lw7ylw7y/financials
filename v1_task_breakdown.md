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
- Each returned indicator record carries the correct category tag

---

## Story 2 — Historical Storage

| Task | Estimate |
|---|---|
| 2.1 `load_state()` / `save_state()` for `data/indicators.json` | 1h |
| 2.2 Append-only history write (never overwrite existing entries) | 1h |
| 2.3 Query helper: get history by indicator + optional date range | 1h |
| 2.4 Tests (below) | 1.5h |
| **Subtotal** | **4.5h** |

**Tests**
- Write → reload from disk → data matches (persistence survives a fresh process)
- Writing a new value never mutates or removes prior history entries
- Query helper returns correct subset for a given date range
- Corrupted/missing JSON file on first run → initializes cleanly rather than crashing

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

## Story 4 — Post-Release Email with AI Interpretation

| Task | Estimate |
|---|---|
| 4.1 New-value diff detection (latest fetch vs. last `history` entry) | 1h |
| 4.2 `interpret.py` — Claude API call: prompt construction with 12-reading window | 2.5h |
| 4.3 Sahm Rule calculation (unemployment) | 1h |
| 4.4 Yield curve inversion streak calculation | 1h |
| 4.5 Email template (subject + body, per Section 7) | 1h |
| 4.6 `send_email.py` — Gmail SMTP wrapper | 1h |
| 4.7 Graceful degradation: catch AI failure, send raw-data-only email | 0.5h |
| 4.8 Tests (below) | 2.5h |
| **Subtotal** | **10.5h** |

**Tests**
- New value differs from last stored entry → email is triggered; unchanged value → no email
- Mocked Claude API success → summary + directional read appear correctly in email body
- Mocked Claude API failure/timeout → email still sends, AI section omitted, raw data present
- Disclaimer line is present in every AI-included email
- Sahm Rule value computed correctly against a known sample series
- Yield curve inversion streak counts consecutive negative readings correctly, resets on a positive reading

---

## Story 5 — Indicator Table View

| Task | Estimate |
|---|---|
| 5.1 `render_dashboard.py` — group indicators into Leading/Coincident/Lagging | 1h |
| 5.2 HTML/CSS template generation (static, no JS framework) | 2h |
| 5.3 Tests (below) | 1.5h |
| **Subtotal** | **4.5h** |

**Tests**
- Rendered HTML contains all 8 indicators under correct category headers
- Each row shows latest value, latest date, and prior value correctly pulled from `history`
- Re-running after a new value is ingested regenerates the table with updated numbers (no stale cache)
- Rendered page requires no login/auth to view (static file, no gating logic)

---

## Story 6 — Next-Indicator Preview

| Task | Estimate |
|---|---|
| 6.1 Days-until-release calculation from `next_release_date` | 0.5h |
| 6.2 Highlight single soonest upcoming release distinctly in the table | 0.5h |
| 6.3 Tests (below) | 1h |
| **Subtotal** | **2h** |

**Tests**
- Countdown math is correct for a known date (e.g. release in exactly 3 days → "in 3 days")
- Indicators with `next_release_date: null` are excluded from the countdown, not shown as errors
- The single nearest release across all 8 indicators is correctly identified when release dates are mixed

---

## Cross-Cutting / Integration

| Task | Estimate |
|---|---|
| Workflow YAML (`.github/workflows/indicator-check.yml`) — schedule trigger, checkout, run, commit-back | 1h |
| Secrets setup checklist walkthrough (Section 9/11 of tech design) | 0.5h |
| Git commit-and-push step from within the workflow | 1h |
| End-to-end dry run against real FRED + Gmail + Claude API (not mocks) | 1.5h |
| **Subtotal** | **4h** |

**Tests**
- Full workflow run on a manual trigger (`workflow_dispatch`) completes without error against live APIs
- Workflow correctly commits and pushes updated `indicators.json` and `docs/index.html`
- Scheduled trigger fires at the expected cron time (verified via Actions run history after 24h)

---

## Total Estimate

| Area | Hours |
|---|---|
| Story 1 — Ingestion | 6.5h |
| Story 2 — Storage | 4.5h |
| Story 3 — Release Calendar | 3h |
| Story 4 — Post-Release Email + AI | 10.5h |
| Story 5 — Table View | 4.5h |
| Story 6 — Next-Indicator Preview | 2h |
| Cross-Cutting / Integration | 4h |
| **Total** | **~35h** |

## Suggested Build Order
Dependency-driven, not just priority-driven — Stories 1-3 are prerequisites for everything else:
1. Story 1 (Ingestion) → 2. Story 2 (Storage) → 3. Story 3 (Release Calendar) → 4. Story 4 (Email + AI) → 5. Story 5 (Table) → 6. Story 6 (Countdown) → Cross-Cutting integration/workflow wiring last, once the underlying script works standalone
