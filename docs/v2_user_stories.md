# V2 User Stories & Acceptance Criteria — Web Dashboard

**Companion to:** investment_dashboard_requirements.md
**Scope:** Section 4 of the requirements doc (Indicator Digest Page, Ticker Dashboard)

v2 is two web pages: a read-only Indicator Digest Page (mirrors the v1 email) and the Ticker Dashboard. Ticker Email Alerts and Discount-Buy Thresholds are backlog items (Section 5 of the requirements doc), not covered here.

---

## Epic: Indicator Digest Page

### Story 1 — On-Demand Indicator Page
**As** the investor, **I want** to open a web page and see the same macro-indicator content the digest email already sends me, **so that** I can check the current picture whenever I want instead of waiting for the next triggering email.

**Acceptance Criteria**
- [x] Page runs locally (e.g. `localhost`) — no public hosting, no domain, no login needed (hosted/non-local is a backlog item)
- [x] Page displays the same three content pieces as the digest email: the holistic AI interpretation + directional read, the indicator table grouped by category, and the next-release countdown
- [x] AI-generated content is labeled as informational commentary, not personalized financial advice
- [x] If the AI interpretation is missing or failed on the most recent ingestion/live-pull run, the page still renders the table and countdown
- [x] The email digest continues to fire on its existing trigger, unchanged by the page's existence

### Story 1a — Background Live Check with In-Place Updates
**As** the investor, **I want** the page to load instantly from the last stored data and check for anything new in the background, updating only what's actually changed, **so that** I'm not staring at a spinner every time I open the page, and the AI isn't re-run for no reason when nothing's changed.

**Acceptance Criteria**
- [x] The page's initial load is built entirely from stored data — no live fetch blocks the response
- [x] After the initial render, the page checks for updates on its own — a live pull from FRED
- [x] If the check finds at least one indicator with a genuinely new value, the affected parts of the page (table, countdown, AI section) update in place, and the AI interpretation is re-run and shown
- [x] If the check finds nothing new, the page is left exactly as it was — no re-render, and **no AI call is made**
- [x] A check that finds new data writes it back to the shared historical data store, so the page and email stay consistent
- [x] If the background check fails outright, the page simply stays on the last stored data
- [x] The fallback/initial state includes the last successful AI summary/directional read, not just the indicator table — requires persisting the most recent AI response (text + directional read + generated-at timestamp) to the data store
- [x] While the background check is in flight, the page shows a visible "checking for updates" indicator; it disappears once the check settles, regardless of outcome

---

## Epic: Ticker Dashboard

### Story 2 — Ticker Watchlist Configuration
**As** the investor, **I want** to maintain my ticker watchlist — and the groups it's organized into — in a simple config file, **so that** I can add, remove, or regroup tickers without touching application code.

**Acceptance Criteria**
- [x] Tickers are defined in a local JSON config file (Section 7 of the requirements doc), grouped under group names defined by the file itself — not a fixed list hardcoded in the app
- [x] Initial watchlist matches the config draft: SPY, IVW, DGRO (stocks); VGIT, VGLT (bonds); VIGI, VYMI, EMB (international); FTEC + other sector ETFs (sector); MSFT, RELY + other trusted individual stocks (individual)
- [x] Adding or removing a ticker requires only editing the config file — no code change
- [x] Adding, removing, or renaming an entire group requires only editing the config file — no code change
- [x] An invalid or unrecognized ticker symbol in the config is skipped with a logged warning rather than breaking the whole dashboard

---

### Story 3 — Ticker Dashboard Page
**As** the investor, **I want** a web page showing my ticker watchlist grouped by asset type, **so that** I can review prices and trends across all my holdings in one place without logging into Fidelity.

**Acceptance Criteria**
- [x] Page runs locally (e.g. `localhost`) — no public hosting, no domain, no login needed
- [x] Tickers are displayed grouped under headers matching the group names in the config file exactly
- [x] Each ticker row shows: current price, 52-week range, 20-day moving average, 50-day moving average, and 200-day moving average
- [x] The 52-week range is shown as a green (near the low)→amber→red (near the high) gradient with a marker for the current price, plus the low/high as text, so the read doesn't depend on color alone
- [x] Each moving average shows both a color (green when price is above it, red when below — same convention as the AI directional badges) and a signed arrow+percentage, again not color-only
- [x] Price and moving-average data is sourced from Finnhub and Yahoo Finance (Section 6 of the requirements doc); the free-tier ~20-minute delay is acceptable and does not need to be surfaced as an error state
- [x] A ticker whose data fails to load, and has never been successfully fetched before, shows a visible per-row error state rather than breaking the rest of the dashboard
- [x] The page's initial paint shows the last cached snapshot instantly, with a background check re-fetching live moments later (Story 5)
- [x] **Percent off 52-week high** — its own column, computed from price + the existing 52-week range, no new data source
- [x] **Change since last close** — its own column, current session's absolute and % move versus the previous close, colored with the same green-up/red-down convention as the moving-average deltas
- [x] **Sortable columns** — the Ticker and % Off High column headers are clickable and sort that group's table (ascending, then descending on a second click); pending/errored rows always sort last regardless of direction; sorting is independent per group table
- [x] **Market Cap** and **P/E (trailing)** — their own columns, sourced from the same Finnhub call already used for the 52-week range (no new fetch); either renders "n/a" rather than erroring the row when Finnhub has no value for that symbol

---

### Story 4 — Cross-Page Navigation
**As** the investor, **I want** to get from one v2 page to the other by clicking rather than typing a URL, **so that** the two pages feel like one dashboard rather than two disconnected tools.

**Acceptance Criteria**
- [x] Both the Indicator Digest Page and the Ticker Dashboard show a small nav linking to the other page
- [x] The nav visibly marks which page is currently active

---

### Story 5 — Ticker Dashboard: Instant Load with Background Refresh
**As** the investor, **I want** the Ticker Dashboard to load instantly from the last known prices and refresh live in the background, **so that** I'm not staring at a blank page while dozens of tickers' worth of Finnhub and Yahoo calls complete one by one.

**Acceptance Criteria**
- [x] The page's initial load is built entirely from a local snapshot cache (`data/tickers.json`, one entry per ticker) — no live fetch blocks the response, same pattern as the Indicator Digest Page
- [x] A ticker with no cached snapshot yet renders as a "Loading…" placeholder row, not an error
- [x] After the initial render, the page checks for live data on its own; unlike the Indicator Digest Page there's no "skip if nothing changed" gate — every check re-fetches every ticker live
- [x] A successful live fetch for a ticker is persisted to the snapshot cache
- [x] A ticker whose live fetch fails falls back to its last cached snapshot silently; only a ticker with no cached snapshot *and* a failed live fetch shows the error state
- [x] While the background check is in flight, the page shows the same visible "checking for updates" indicator as the Indicator Digest Page

---

### Story 6 — US Stock Market News
**As** the investor, **I want** to see general market headlines at the top of the Ticker Dashboard, **so that** I know what's moving the market before I look at individual ticker prices.

**Acceptance Criteria**
- [x] A short feed of general US stock market news is shown once, at the top of the page, above the grouped ticker tables — not per-ticker
- [x] Sourced from Finnhub's general-news endpoint (Section 6 of the requirements doc), filtered to Finnhub's own `"top news"` category tag
- [x] Follows the same instant-load-then-background-refresh pattern as the rest of the page (Story 5): rides along in the same `/api/check-tickers` round trip, with its own cache file (`data/market_news.json`)
- [x] A failure to load market news degrades gracefully (the section is empty or shows a muted "unavailable" state) rather than breaking the rest of the page

---

### Story 7 — In-App Ticker Editing
**As** the investor, **I want** to add or remove a ticker from within an existing group right on the Ticker Dashboard, **so that** I don't have to open the config file for a routine watchlist change.

**Acceptance Criteria**
- [x] Each ticker row has a remove control, placed as the row's trailing column rather than beside the ticker symbol; each group has an add-ticker field. Both write straight to `config/tickers.json`
- [x] Adding or removing a whole group is still a hand-edit of the file — out of scope here
- [x] An invalid symbol or unknown group is rejected with an error, not silently accepted
- [x] Neither page requires user authentication

---

## Epic: Hosted Live Dashboard (v2.1)

### Story 8 — Password-Protected Public Hosting
**As** the investor, **I want** both dashboard pages reachable from anywhere behind a password, **so that** I can check them without needing my own laptop running, while keeping them private to me.

**Acceptance Criteria**
- [ ] Both pages are served from a single hosted web service reachable over the public internet — no VPN, tunnel, or laptop required (pending Render deployment, task H.6)
- [x] Every route requires a username + password before rendering any content; there is no page reachable without authenticating
- [x] Credentials are configured via environment variables on the host, never hardcoded or committed to the repo
- [ ] Traffic is served over HTTPS (provided by the host), so credentials are never sent in plaintext (pending Render deployment, task H.6)
- [x] Local development is unaffected — running `src/web/app.py` locally with no auth env vars set behaves exactly as it does today, with no password prompt

---

### Story 9 — Durable Ticker Config & Caches on a Host With No Persistent Disk
**As** the investor, **I want** my watchlist edits and cached prices to survive a restart of the hosted app, **so that** the in-app ticker editor and the instant-load caches keep working the same way they do when run locally.

**Acceptance Criteria**
- [x] When a Redis connection is configured (hosted deployment), `config/tickers.json`'s content, `data/tickers.json`'s cache, and `data/market_news.json`'s cache are all read from and written to Redis instead of local files
- [x] When no Redis connection is configured (local development), behavior is unchanged — the same local JSON files are used as today (verified: the full pre-existing test suite passes unmodified with no Redis env vars set)
- [x] On first read with nothing yet in Redis, the ticker config is seeded from the repo's committed `config/tickers.json`, so a fresh deploy starts with the existing watchlist rather than an empty one
- [ ] Adding or removing a ticker through the in-app editor on the hosted deployment persists in Redis and survives a container restart (code path implemented and unit-tested; not yet verified against a live Render+Upstash deployment — see `docs/v2_technical_design.md` Section 11.3's wire-format caveat)
- [x] A Redis outage degrades gracefully: the ticker/news caches fall back to their existing "no cache yet" pending/error states rather than crashing the page; a failed ticker-config load fails loudly with a clear error rather than silently rendering an empty watchlist

---

### Story 10 — Indicator Data Stays Git-Sourced When Hosted
**As** the investor, **I want** the hosted Indicator Digest Page to keep reading from the same committed history the email pipeline uses, **so that** I don't need a second data store just for indicators.

**Acceptance Criteria**
- [ ] The hosted deployment reads `data/indicators.json` from its own git checkout, same as local — no Redis involvement for indicator history or the AI response cache
- [ ] The host's auto-deploy-on-push means a GitHub Actions ingestion commit automatically refreshes the hosted page's stored data on its own schedule, with no manual redeploy step
- [ ] A live pull triggered by a page visit (`/api/check`) still fetches and displays fresh data for that visit even though the write to disk won't survive a restart; the next scheduled Actions commit is what makes it durable

---
## Cross-Cutting Non-Functional Criteria (apply to all stories above)
- [x] Neither page requires user authentication
- [x] Both pages are usable on a desktop/web browser (no mobile app)
- [x] A data-source outage (FRED, Finnhub, Yahoo) or missing data degrades gracefully (visible error/empty state) rather than crashing the page
