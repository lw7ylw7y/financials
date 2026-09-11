# V1 User Stories & Acceptance Criteria — Macroeconomic Indicators Backend

**Companion to:** investment_dashboard_requirements.md
**Scope:** Section 3 of the requirements doc (Post-Release AI Email, Indicator Table, Next-Indicator Preview)

**Note on Stories 4-6:** v1's only product surface is a single email — there is no webpage or dashboard. Stories 4 (AI interpretation), 5 (indicator table), and 6 (next-release preview) describe three pieces of *content*, all delivered together in one digest email whenever at least one indicator updates, not three separately-shipped features.

---

## Epic: Macroeconomic Indicators Backend

### Story 1 — Indicator Data Ingestion (foundational)
**As** the app owner, **I want** the system to automatically pull the 8 v1 indicators from FRED on a schedule, **so that** I don't have to manually check or enter values.

**Indicators covered:** initial jobless claims, yield curve spread (10yr–2yr), building permits, nonfarm payrolls, industrial production, Fed funds rate, CPI, unemployment rate.

**Acceptance Criteria**
- [x] System fetches current values for all 8 indicators from the FRED API on a recurring schedule
- [x] Each indicator is tagged with its category (leading / coincident / lagging)
- [x] A failed fetch for one indicator does not block ingestion of the others
- [x] Fetch failures are logged with enough detail to debug (indicator, timestamp, error)
- [x] A fetched value is only treated as new — and only then persisted — if its release date is strictly newer than the already-stored latest date; a value with the same or an older date (e.g. a stale/cached API response, or a same-date revision) is a no-op and is logged as such rather than appended

---

### Story 2 — Historical Storage
**As** the app owner, **I want** every fetched indicator value stored with its date, **so that** I can see trends over time instead of just the latest number.

**Acceptance Criteria**
- [x] Every ingested value is persisted with: indicator name, category, value, and the date it applies to (not just the date it was fetched)
- [x] Historical values are never overwritten — each new release adds a new record
- [x] Data is queryable by indicator and by date range (needed for Story 5's table and Story 4's "compare to prior reading")
- [x] Storage survives app/server restarts (persistent, not in-memory only)
- [x] History is retained for a rolling 12-month window; entries older than 12 months are pruned automatically so the store doesn't grow unbounded with readings too old to be useful for a trend view

---

### Story 3 — Release Calendar Tracking
**As** the app owner, **I want** the system to know the scheduled release date for each indicator, **so that** it can show what's coming next.

**Acceptance Criteria**
- [x] System retrieves scheduled release dates for all 8 indicators from FRED's release calendar
- [ ] Calendar data refreshes regularly enough to catch date changes/postponements
- [x] Each indicator's next scheduled release date is queryable (needed for Story 6)

---

### Story 4 — Digest Email with Holistic AI Interpretation
**As** the investor, **I want** a weekly-at-most email when indicators publish new values, with a plain-English explanation reasoning across all 8 indicators together and one overall directional read, **so that** I understand the macro picture without having to interpret raw data myself or getting emailed every few hours for daily-updating series.

**Acceptance Criteria**
- [x] Given at least one indicator has a new value since the last digest was sent, and at least a week has passed since then, one digest email is sent — not one email per updated indicator, and not more than weekly even for indicators (e.g. the yield curve spread) that update daily
- [x] Ingestion itself still runs on its normal schedule (every 6 hours) regardless of the email throttle, so stored data stays current even between digests
- [x] An update that happens between digests is still reported once the weekly gate opens — not dropped just because it didn't happen in the specific run that crossed the interval
- [x] The AI summary reasons across all 8 indicators' recent history together (not just the one(s) that changed), so it can connect indicators to each other rather than commenting on each in isolation
- [x] Email includes an AI-generated plain-English summary of what changed and why it matters
- [x] Email includes **one overall** AI-generated directional read: bullish / bearish / neutral
- [x] Email visibly labels the AI content as informational commentary, not personalized financial advice
- [x] If the AI generation step fails, the email still sends with the table + countdown (Stories 5/6) (graceful degradation — a broken AI call should never block you from getting the numbers)

---

### Story 5 — Indicator Table (in the digest email)
**As** the investor, **I want** the digest email to include a table of all 8 indicators' current values and recent history, grouped by category, **so that** I have the full macro picture in the same place as the AI commentary.

**Acceptance Criteria**
- [x] Table displays all 8 indicators grouped under Leading / Coincident / Lagging headers
- [x] Each row shows at minimum: indicator name, latest value, latest release date, and prior value
- [x] Table is backed by the historical store (Story 2), not just the latest cached value
- [x] Table is built fresh from current data at send time — no separate "refresh" step, since it's pushed to the inbox rather than pulled from a page
- [x] No separate account or dashboard login is needed to see it — it arrives directly in the inbox (per v1 scope)

---

### Story 6 — Next-Indicator Preview (in the digest email)
**As** the investor, **I want** to see what's coming next and when, **so that** I know what to expect without checking a separate calendar.

**Acceptance Criteria**
- [x] The digest email's table (Story 5) shows, for each indicator, the number of days until its next scheduled release (e.g. "CPI releases in 3 days")
- [x] The single next upcoming release (across all 8 indicators) is easy to identify at a glance, not buried in the table
- [x] Preview data is sourced from the same release calendar as Story 3, so the countdown is always consistent with the calendar

---

## Cross-Cutting Non-Functional Criteria (apply to all stories above)
- [ ] All ingestion and email sending run via a hosted background job — not dependent on any device being on or a browser being open
- [x] System handles a FRED API outage or rate-limit response without crashing (retry or skip-and-log)
- [x] No user authentication required anywhere in v1
