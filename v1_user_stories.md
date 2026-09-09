# V1 User Stories & Acceptance Criteria — Macroeconomic Indicators Backend

**Companion to:** investment_dashboard_requirements.md
**Scope:** Section 3 of the requirements doc (Post-Release AI Email, Indicator Table, Next-Indicator Preview)

---

## Epic: Macroeconomic Indicators Backend

### Story 1 — Indicator Data Ingestion (foundational)
**As** the app owner, **I want** the system to automatically pull the 8 v1 indicators from FRED on a schedule, **so that** I don't have to manually check or enter values.

**Indicators covered:** initial jobless claims, yield curve spread (10yr–2yr), building permits, nonfarm payrolls, industrial production, Fed funds rate, CPI, unemployment rate.

**Acceptance Criteria**
- [ ] System fetches current values for all 8 indicators from the FRED API on a recurring schedule
- [ ] Each indicator is tagged with its category (leading / coincident / lagging)
- [ ] A failed fetch for one indicator does not block ingestion of the others
- [ ] Fetch failures are logged with enough detail to debug (indicator, timestamp, error)
- [ ] Newly fetched values that match the already-stored latest value do not trigger duplicate processing (no-op if unchanged)

---

### Story 2 — Historical Storage
**As** the app owner, **I want** every fetched indicator value stored with its date, **so that** I can see trends over time instead of just the latest number.

**Acceptance Criteria**
- [ ] Every ingested value is persisted with: indicator name, category, value, and the date it applies to (not just the date it was fetched)
- [ ] Historical values are never overwritten — each new release adds a new record
- [ ] Data is queryable by indicator and by date range (needed for Story 5's table view and Story 4's "compare to prior reading")
- [ ] Storage survives app/server restarts (persistent, not in-memory only)

---

### Story 3 — Release Calendar Tracking
**As** the app owner, **I want** the system to know the scheduled release date for each indicator, **so that** it can show what's coming next.

**Acceptance Criteria**
- [ ] System retrieves scheduled release dates for all 8 indicators from FRED's release calendar
- [ ] Calendar data refreshes regularly enough to catch date changes/postponements
- [ ] Each indicator's next scheduled release date is queryable (needed for Story 6)

---

### Story 4 — Post-Release Email with AI Interpretation
**As** the investor, **I want** an email when a new indicator value is published, with a plain-English explanation and a directional read, **so that** I understand what changed without having to interpret raw data myself.

**Acceptance Criteria**
- [ ] Given a new indicator value is ingested (Story 1) that differs from the last stored value, when ingestion completes, then a post-release email is sent
- [ ] Email includes: indicator name, category, new value, prior value, and change (absolute and/or %)
- [ ] Email includes an AI-generated plain-English summary of what changed and why it matters
- [ ] Email includes an AI-generated directional read: bullish / bearish / neutral
- [ ] Email visibly labels the AI content as informational commentary, not personalized financial advice
- [ ] If the AI generation step fails, the email still sends with the raw data (graceful degradation — a broken AI call should never block you from getting the number)

---

### Story 5 — Indicator Table View
**As** the investor, **I want** a table showing all 8 indicators' current values and recent history, grouped by category, **so that** I have one place to see the full macro picture.

**Acceptance Criteria**
- [ ] Table displays all 8 indicators grouped under Leading / Coincident / Lagging headers
- [ ] Each row shows at minimum: indicator name, latest value, latest release date, and prior value
- [ ] Table is backed by the historical store (Story 2), not just the latest cached value
- [ ] Table reflects newly ingested data without requiring a manual refresh step beyond reloading the page
- [ ] No login required to view the table (per v1 scope)

---

### Story 6 — Next-Indicator Preview
**As** the investor, **I want** to see what's coming next and when, **so that** I know what to expect without checking a separate calendar.

**Acceptance Criteria**
- [ ] Table view (Story 5) shows, for each indicator, the number of days until its next scheduled release (e.g. "CPI releases in 3 days")
- [ ] The single next upcoming release (across all 8 indicators) is easy to identify at a glance, not buried in the table
- [ ] Preview data is sourced from the same release calendar as Story 3, so the countdown is always consistent with the calendar

---

## Cross-Cutting Non-Functional Criteria (apply to all stories above)
- [ ] All email sending and scheduled checks run via a hosted background job — not dependent on the dashboard being open in a browser
- [ ] System handles a FRED API outage or rate-limit response without crashing (retry or skip-and-log)
- [ ] No user authentication required anywhere in v1
