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
- [x] Each ticker row shows: current price and 52-week range
- [x] The 52-week range is shown as a green (near the low)→amber→red (near the high) gradient with a marker for the current price, plus the low/high as text, so the read doesn't depend on color alone
- [x] Price data is sourced from Finnhub (Section 6 of the requirements doc); the free-tier ~20-minute delay is acceptable and does not need to be surfaced as an error state
- [x] A ticker whose data fails to load, and has never been successfully fetched before, shows a visible per-row error state rather than breaking the rest of the dashboard
- [x] The page's initial paint shows the last cached snapshot instantly, with a background check re-fetching live moments later (Story 5)
- [x] **Percent off 52-week high** — its own column, computed from price + the existing 52-week range, no new data source
- [x] **Change since last close** — its own column, current session's absolute and % move versus the previous close, colored green-up/red-down
- **Removed (2026-09-16):** the 20-day/50-day/200-day moving-average columns (and the Yahoo Finance daily-close fetch they depended on) were dropped from the table and from `ticker_cache`'s stored snapshot shape — not replaced by anything
- [x] **Sortable columns** — the Ticker and % Off High column headers are clickable and sort that group's table (ascending, then descending on a second click); pending/errored rows always sort last regardless of direction; sorting is independent per group table
- [x] **Market Cap** and **P/E (trailing)** — their own columns, sourced from the same Finnhub call already used for the 52-week range (no new fetch); either renders "n/a" rather than erroring the row when Finnhub has no value for that symbol
- **Added (2026-09-17):** Finnhub never has a P/E for a fund, so the equity-ETF groups (`stocks`, `international`, `sector`) additionally fall back to Yahoo's aggregate-holdings P/E when Finnhub's own is empty — best-effort against an undocumented, unofficial Yahoo endpoint; a failure there degrades to "n/a" like any other missing value, never an error
- [x] **PEG ratio** — its own column (2026-09-17), sourced from the same Finnhub call as P/E (`pegTTM`, falling back to `forwardPEG`); no Yahoo fallback exists for it, so it's only ever populated for individual stocks — every ETF's PEG renders "n/a"

---

### Story 4 — Cross-Page Navigation
**As** the investor, **I want** to get from one v2 page to the other by clicking rather than typing a URL, **so that** the two pages feel like one dashboard rather than two disconnected tools.

**Acceptance Criteria**
- [x] Both the Indicator Digest Page and the Ticker Dashboard show a small nav linking to the other page
- [x] The nav visibly marks which page is currently active

---

### Story 5 — Ticker Dashboard: Instant Load with Background Refresh
**As** the investor, **I want** the Ticker Dashboard to load instantly from the last known prices and refresh live in the background, **so that** I'm not staring at a blank page while dozens of tickers' worth of Finnhub calls complete one by one.

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

### Story 8 — Google Sign-In-Protected Public Hosting
**As** the investor, **I want** both dashboard pages reachable from anywhere behind my Google account, **so that** I can check them without needing my own laptop running, while keeping them private to me.

**Acceptance Criteria**
- [x] Both pages are served from a single hosted web service reachable over the public internet — no VPN, tunnel, or laptop required
- [x] Every route requires signing in with Google before rendering any content; there is no page reachable without authenticating. A logged-out page visit redirects to Google's sign-in; a logged-out `/api/*` call gets a 401
- [x] Only the one Google account named by `ALLOWED_EMAIL` (with a verified email) is let in; any other Google account gets a 403
- [x] Credentials (`GOOGLE_CLIENT_ID`/`SECRET`, `ALLOWED_EMAIL`, `SECRET_KEY`) are configured via environment variables on the host, never hardcoded or committed to the repo
- [x] The sign-in flow guards against forged callbacks (a per-request `state` value, single-use) and, once enabled, fails closed (503) if any required setting is missing
- [x] Traffic is served over HTTPS (provided by the host)
- [x] Local development is unaffected — running `src/web/app.py` locally with `GOOGLE_CLIENT_ID` unset behaves exactly as it does today, with no sign-in

---

### Story 9 — Durable Ticker Config & Caches on a Host With No Persistent Disk
**As** the investor, **I want** my watchlist edits and cached prices to survive a restart of the hosted app, **so that** the in-app ticker editor and the instant-load caches keep working the same way they do when run locally.

**Acceptance Criteria**
- [x] When a Redis connection is configured (hosted deployment), `config/tickers.json`'s content, `data/tickers.json`'s cache, and `data/market_news.json`'s cache are all read from and written to Redis instead of local files
- [x] When no Redis connection is configured (local development), behavior is unchanged — the same local JSON files are used as today (verified: the full pre-existing test suite passes unmodified with no Redis env vars set)
- [x] On first read with nothing yet in Redis, the ticker config is seeded from the repo's committed `config/tickers.json`, so a fresh deploy starts with the existing watchlist rather than an empty one
- [x] Adding or removing a ticker through the in-app editor on the hosted deployment persists in Redis and survives a container restart — verified live: a hosted removal now correctly updates the `ticker_config` key in Upstash
- [x] A Redis outage degrades gracefully: the ticker/news caches fall back to their existing "no cache yet" pending/error states rather than crashing the page; a failed ticker-config load fails loudly with a clear error rather than silently rendering an empty watchlist

---

### Story 10 — Indicator Data Stays Git-Sourced When Hosted (superseded by Story 11)
**As** the investor, **I want** the hosted Indicator Digest Page to keep reading from the same committed history the email pipeline uses, **so that** I don't need a second data store just for indicators.

**Superseded:** live usage surfaced a real gap this design didn't account for — see Story 11 below, which replaces it. `data/indicators.json` is no longer git-sourced on a hosted deployment; none of the ACs below were ever implemented before the design changed.

- [ ] ~~The hosted deployment reads `data/indicators.json` from its own git checkout, same as local — no Redis involvement for indicator history or the AI response cache~~
- [ ] ~~The host's auto-deploy-on-push means a GitHub Actions ingestion commit automatically refreshes the hosted page's stored data on its own schedule, with no manual redeploy step~~
- [ ] ~~A live pull triggered by a page visit (`/api/check`) still fetches and displays fresh data for that visit even though the write to disk won't survive a restart; the next scheduled Actions commit is what makes it durable~~

---

### Story 11 — Durable, Consistent Indicator Data on a Host With No Persistent Disk
**As** the investor, **I want** the hosted Indicator Digest Page and the scheduled email pipeline to share one always-current copy of indicator data and its AI take, **so that** I never see a stale AI response just because the emailed digest is throttled to a weekly cadence.

**Why this replaced Story 10:** the AI response was only ever regenerated when an email also happened to be due (throttled to a weekly rollup), so a live visitor's background check could compute a *fresher* AI take than what GitHub Actions had last committed — but that fresher result only ever landed on Render's own ephemeral disk, discarded on the next restart, while the git-committed (and therefore durable) version stayed stale until GitHub's own weekly-throttled cycle caught up. Moving indicator state to Redis, mirroring Story 9's ticker persistence, gives both the scheduled Action and any hosted visitor the same shared, durable state.

**Acceptance Criteria**
- [x] `data/indicators.json`'s content is read from and written to Redis (via `kv_store.py`) instead of the local file, whenever `UPSTASH_REDIS_REST_URL` is set; unset (local dev's default) behaves exactly as before
- [x] The AI response is regenerated every ingestion cycle that finds at least one genuinely new indicator value — no longer gated on whether the weekly digest email is also about to send
- [x] The weekly digest email's send decision is based on a content fingerprint (has the digest's actual conclusion changed since the last email) plus the existing minimum-interval floor, rather than a raw "changed since last email" timestamp scan — so a week passing with no real change doesn't trigger a repeat email
- [x] A hosted visitor's live background check (`/api/check`) writes to the same Redis-backed state the scheduled Action uses, so its result is no longer discarded on the next container restart
- [x] On first Redis-backed read with nothing yet in Redis, indicator state is seeded from the repo's committed `data/indicators.json`, so a fresh or cleared Redis key starts with the existing multi-month history rather than a single fresh reading per indicator — added after a real incident where this gap reset every indicator's sparkline to one point (see `docs/v2_task_breakdown.md`'s H.12 incident note)

---

### Story 12 — Ticker Dashboard: Per-Group Live Checks
**As** the investor, **I want** each ticker group (and market news) to refresh independently in the background, **so that** I'm not waiting on the entire ~36-ticker watchlist to finish before seeing anything update.

**Why:** the original single `/api/check-tickers` request fetched and re-rendered the whole watchlist at once, occasionally taking 30+ seconds and needing gunicorn's `--timeout 120` on Render just to avoid a bare 500. A full React componentization was considered (Section 5's backlog item) and explicitly rejected in favor of this smaller, direct fix on the existing string-templating approach.

**Acceptance Criteria**
- [x] The ticker page's background script fires one live-check request per group (`/api/tickers/groups/<name>/check`) plus one for market news (`/api/market-news/check`), all concurrently, instead of one combined request
- [x] Each group's table repaints as soon as its own request resolves, independent of every other group's — a group with fewer tickers finishes and repaints before a slower one does
- [x] A failed per-group or market-news check falls back silently to that section's last cached/pending state, same as before, without affecting any other group
- [x] The shared ticker snapshot cache (`data/tickers.json`, or Redis when hosted) is safe against concurrent per-group writes — one group's check can't silently overwrite another's freshly-fetched values when both finish close together, at any concurrency level (no lock needed on the Redis path — see below)
- [x] Sorting and remove-ticker behavior are unchanged from the single-request design
- [x] Adding a ticker shows it immediately as a new pending row in its group and re-checks just that group for real data, without reloading the whole page (superseding the original design's `window.location.reload()`)
- [x] `_require_auth` gates the new routes exactly as it does every other route
- [x] The ticker cache is genuinely safe under real concurrent multi-user/multi-process access, not just within one process — Redis-backed, it's a hash (one field per symbol) with atomic per-field writes, not a lock around a whole-cache read-modify-write
- [x] The ticker config (the watchlist) gets the same treatment for consistency — Redis-backed, a hash with one field per group, each carrying an explicit order index so group display order survives Redis not preserving hash field insertion order

---

### Story 13 — Redis as the Only Source of Truth (no local-file fallback)
**As** the investor, **I want** the app to always read and write the same live Redis state, on my own machine or hosted, **so that** there's never a question of which copy — a stale committed file, or Redis's current state — is actually authoritative.

**Why:** every storage function (ticker config, both ticker/news caches, indicator state) had a local-file branch intended for local development without a Redis account. In practice, local dev has always pointed at the same live Upstash instance Render uses, so that branch was never really exercised — its existence just made it easy to mistake Redis's current, possibly hand-edited state for something that should match a stale committed file. That confusion caused a real, if minor, incident during Story 12's own testing: a test script mistakenly deleted a real ticker (`IVW`), and separately the committed `config/tickers.json` no longer matched Redis at all (the user's own legitimate live-site edits) — initially misread as data corruption rather than the expected, already-documented result of hosted edits going to Redis only.

**Acceptance Criteria**
- [x] `UPSTASH_REDIS_REST_URL`/`UPSTASH_REDIS_REST_TOKEN` are required unconditionally, wherever the app runs — no local-file fallback exists anywhere for the watchlist, either cache, or indicator state
- [x] `config/tickers.json` and `data/indicators.json` are removed from the repo, since no code reads them anymore; `.gitignore`'s now-meaningless `data/tickers.json`/`data/market_news.json` entries are removed too
- [x] A wiped or brand-new Redis key comes back empty (an empty watchlist, or a "nothing cached/recorded yet" state) rather than crashing — recovering indicator history is `python3 src/backfill.py`'s job (already the real recovery path used during the Story 11/H.12 incident); recovering a wiped watchlist is re-adding tickers through the in-app editor. Neither is automatic, and that's an accepted tradeoff, not a gap
- [x] The now-unused process-local lock (`ticker_dashboard._ticker_state_lock`) is deleted along with the local-file code it existed to guard — every remaining write is either a single Redis key or an atomic per-field hash write, neither needing a lock

---

### Story 14 — Ticker Dashboard: AI Valuation Section
**As** the investor, **I want** an AI read on which of my tickers/groups look like a discount, fair value, or overpriced, **so that** I don't have to manually compare P/E, PEG, growth, and sector benchmarks myself for every row.

**Why:** the Market Cap/P/E/PEG columns (this doc's Section 4.2) and the sector-peer/growth-quality data gathered for it give the raw numbers, but reading them ticker-by-ticker to spot a value trap (a low P/E paired with shrinking revenue or high debt) is exactly the kind of synthesis an LLM is well-suited for, mirroring what `interpret.py` already does for the indicator digest.

**Acceptance Criteria**
- [x] One section at the top of `/tickers`, above market news: an overview paragraph plus a discount/fair/overpriced badge per ETF group, sorted most-attractive-first
- [x] Every ticker in the `individual` group gets its own discount/fair/overpriced verdict with a one-sentence reasoning, listed under three "Discount"/"Fair"/"Overpriced" headings (not one flat list) — an explicit requirement, not just whatever order the AI returns them in
- [x] One batched AI call reasons across the *entire* watchlist at once, not one call per ticker — confirmed live that gemini-3.8-flash's free tier caps at 20 requests/day total, shared with the indicator digest's own calls on the same model, making a per-ticker design unworkable
- [x] The AI is given the sector-peer P/E benchmark and growth/quality stats (revenue growth, EPS growth, ROE, margin, debt/equity) alongside P/E and PEG, and its system prompt explicitly instructs it to call out a low P/E backed by weak fundamentals as a value trap rather than a genuine discount — confirmed live it does this (e.g. flagged INTC and QCOM as value traps despite low P/Es)
- [x] The valuation is cached (`ticker_valuation_cache`) and refreshes on a multi-hour throttle, not on every page load or background check — protecting the shared Gemini quota
- [x] Any AI failure, including a quota/rate-limit error, falls back to the last successfully cached valuation shown as-is, never an error state — confirmed live against a real `429 RESOURCE_EXHAUSTED` response. With nothing ever cached, degrades to a muted "not yet available" placeholder instead
- [x] Has its own background-check route (`/api/tickers/valuation/check`), checked independently of any ticker group's or market news' own check, folded into the same "Checking for updates..." indicator

### Story 15 — AI Calls Fall Back Through Other Gemini Models
**As** the investor, **I want** the AI sections to keep working when the primary Gemini model is overloaded or out of quota, **so that** a single-model outage doesn't leave the digest and valuation sections empty.

**Why:** Gemini's free tier returned `503 UNAVAILABLE` almost continuously during a real incident, making both AI sections useless. Free-tier quota and serving capacity are tracked per model, and which models are overloaded shifts through the day (a newer model can be down while an older one answers), so a longer chain survives more spells.

**Acceptance Criteria**
- [x] When the primary Gemini call fails for any reason (API error, quota `429`, overload `503`, missing key, empty or unparseable response), the same prompt is retried on each fallback model in turn (`gemini-3.7-flash`, `gemini-3.6-flash`, `gemini-3.5-flash-lite`, `gemini-3.5-flash` by default; `GEMINI_FALLBACK_MODELS`, a comma-separated list, overrides it), using the same `GEMINI_API_KEY`
- [x] The first model to return a valid response wins; later models are never called
- [x] If every model fails, behavior is unchanged from before: the digest omits the AI section and the ticker valuation degrades to the last cached valuation. The error names each model and its failure
- [x] Each model is called at most once per request (no retries)
- [x] After every model has failed, the ticker valuation's AI call isn't retried for 15 minutes (`VALUATION_FAILURE_COOLDOWN`), so a page load during an outage doesn't spend one request per model on the shared quota

### Story 16 — A Failed AI Call Is Retried, Not Left Stale
**As** the investor, **I want** the indicator digest's AI take to be regenerated after a failed attempt, **so that** a Gemini outage at the moment new data arrived doesn't leave an outdated take on the page until the next release, weeks later.

**Why:** the AI call used to happen only in the same run that found new data. If every model failed then, the new values were saved, the old take stayed, and no later check had a reason to try again.

**Acceptance Criteria**
- [x] Each saved AI take records which reading of each indicator it covers (`as_of`); a take is stale when any indicator's latest date differs from it, or when it's missing or predates `as_of`
- [x] A stale take is retried by the next scheduled run and by the next page's background check, even if no indicator has a new value
- [x] After a failed attempt, no further attempt is made for 15 minutes (`AI_RETRY_COOLDOWN`), unless a genuinely new value arrives, so an outage doesn't cost one request per model on every page load
- [x] A successful attempt clears the failure record; the current take is never regenerated, so a "nothing new, take current" check still costs a FRED call and no Gemini call
- [x] A retry that fails again doesn't repaint the page; a successful one patches the AI section in place

### Story 17 — A 12-Month History for Every Indicator, and a Same-Day Fed Funds Rate
**As** the investor, **I want** every indicator's sparkline and AI context to span a full 12 months whether the series updates daily, weekly or monthly, and the Fed Funds Rate to reflect a rate change within a day, **so that** trends are comparable across indicators and a Fed decision doesn't stay invisible until the following month.

**Why:** history was cut to the last 12 *readings*, which is a year for a monthly series but 12 weeks for jobless claims and about two weeks for the daily yield curve spread. Separately, the Fed Funds indicator tracked the monthly-average series (`FEDFUNDS`), which publishes once a month is over and blends a rate change with the days before it, so a September hike showed 3.63% until October.

**Acceptance Criteria**
- [x] Each indicator's table sparkline and AI context cover every stored reading, i.e. the rolling 12-month window, not the last 12 entries
- [x] `backfill.py` seeds each indicator with every FRED observation from the start of that window (about 250 for a daily series, 52 weekly, 10–13 monthly), and stays safe to re-run (never overwrites or removes existing entries)
- [x] The AI prompt receives at most about one reading per week for a daily series, so it stays short; shorter series are sent in full
- [x] The Fed Funds Rate uses the daily effective rate (`DFF`), which reflects a change within about a day
- [x] Switching an indicator's FRED series discards the old series' readings (a monthly average isn't comparable to a daily rate), both in the scheduled/live ingestion and in `backfill.py`

### Story 18 — Ticker Valuation Covers Every Ticker and Knows the Macro Backdrop
**As** the investor, **I want** the discount/fair/overpriced columns to list ETFs as well as individual stocks, and the AI to weigh the economic backdrop, **so that** I can see both where to put money in general (the group cards) and which specific tickers, ETFs included, to put it in.

**Acceptance Criteria**
- [x] The per-group cards (bonds, stocks, international, sector, individual) are unchanged
- [x] The Discount/Fair/Overpriced columns list every ticker in every group, ETFs and individual stocks, each with a one-sentence reasoning and a small tag naming its group, in watchlist order within each column
- [x] An ETF's verdict is based on how far it sits below its 52-week high, its recent price returns (13-week, 26-week, year-to-date) and its peers (funds have no P/E), and the reasoning says so plainly rather than inventing a P/E-based read
- [x] Each ticker's cached snapshot carries those three returns (from the same Finnhub call already made), shown to the AI for ETFs and individual stocks alike but not as new table columns
- [x] The valuation isn't generated until at least half the cached snapshots carry the returns, so the first check after they were introduced doesn't cache a valuation built without them
- [x] The valuation call is given the indicator digest's saved summary and direction as background; the model is told to let each ticker's own numbers decide, and a missing or unreadable digest take doesn't stop the valuation
- [x] A valuation cached before this change is regenerated on the next check instead of being served for up to 6 hours, and still renders (individual stocks only) if the regeneration fails
- [x] A ticker the AI leaves out is simply absent from the columns, not an error

---
## Cross-Cutting Non-Functional Criteria (apply to all stories above)
- [x] Neither page requires user authentication
- [x] Both pages are usable on a desktop/web browser (no mobile app)
- [x] A data-source outage (FRED, Finnhub) or missing data degrades gracefully (visible error/empty state) rather than crashing the page
