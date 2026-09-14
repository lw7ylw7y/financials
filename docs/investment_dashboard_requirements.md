# Investment Dashboard — Software Requirements

**Status:** v1 shipped; v2 shipped (local); v2.1 in planning (hosted)
**Owner:** You (customer) / Claude (PM)

## 1. Problem Statement
Replace the manual parts of a daily investment-monitoring workflow currently split across the Fidelity website (requires login) and a hand-updated Google Sheet. The goal is not to change the investment strategy, but to remove manual data entry and the login requirement, and to encode personalized alert logic that Fidelity's built-in alerts don't support.

## 2. User & Usage Pattern
- Single user (you), single device to start (desktop/web browser)
- Active review: Mondays (buy day)
- Passive monitoring: daily glances for major news / discount opportunities
- Rare sell-side activity: long-term hold strategy, sells only near suspected market cycle tops

## 3. Scope for v1 — Macroeconomic Indicators (Backend-First)

Indicator set, organized into categories:

**Leading indicators**
- Initial jobless claims
- Yield curve spread (10-yr minus 2-yr Treasury)
- Building permits

**Coincident indicators**
- Nonfarm payrolls
- Industrial production

**Lagging indicators**
- Fed funds rate
- CPI (inflation)
- Unemployment rate

All of the above are available via FRED, so v1 runs on a single free data source with no scraping or paid vendor needed.

v1's entire product surface is a single digest email — there is no webpage/dashboard/visual layer in v1. The three items below (3.1-3.3) are content sections of that one email, not separate features:

### 3.1 Digest Email with Holistic AI Interpretation (Priority 1)
- Sent whenever at least one indicator publishes a new value — one email per triggering run, not one per indicator
- AI interpretation reasons across all 8 indicators' recent history together (not just the one(s) that changed), so it can connect indicators to each other
- Includes: a plain-English explanation of what changed and why it matters, and one overall directional opinion (bullish / bearish / neutral)
- **Guardrail:** framed as informational commentary based on indicator trends, not personalized financial advice — labeled as such in the email

### 3.2 Indicator Table (Priority 2, in the same email)
- A table showing each indicator's current value and recent history, grouped by leading/coincident/lagging
- Backed by a running historical store per indicator (a rolling 12-month window of values) — older readings are pruned

### 3.3 Next-Indicator Preview (Priority 3, in the same email)
- Shows what's coming next and when (e.g. "CPI releases in 3 days"), pulled from an economic release calendar (FRED release calendar or BLS release schedule)
- Surfaced in the digest email's table — no standalone pre-release email in v1

## 4. Scope for v2 — Web Dashboard

### 4.1 Indicator Digest Page
- A web page rendering of the same content already delivered in the v1 digest email (Section 3.1–3.3): the holistic AI interpretation, the indicator table, and the next-indicator preview
- **Hosting: local-only.** Runs on your own machine (e.g. `localhost`), started when you want to check it — not deployed to a public host. Avoids both a domain purchase and exposing the page publicly; static hosting (e.g. GitHub Pages) is ruled out since it can't run the server-side live pull below, or keep API keys server-side
- No login required
- **Loads instantly from stored data, then checks for updates in the background.** The initial render never waits on a live pull — it shows the last stored snapshot immediately, then checks for new data on its own; if it finds at least one indicator with a genuinely new value, it updates just the affected parts of the page (table, countdown, AI section) in place. If nothing's new, or the check fails, the page is left exactly as it was
- While the background check runs, the page shows a visible "checking for updates" indicator that disappears once the check settles either way
- The indicator table includes a small trend sparkline per indicator (inline SVG)
- Backed by the same historical data store the v1 email pipeline writes to, so the email and the page stay consistent
- The store also persists the most recent successful AI response (summary + directional read + timestamp), so the fallback path has something meaningful to show without a live AI call
- Complements rather than replaces the digest email; the email still fires on its existing trigger (Section 3.1), the page is for on-demand lookup

### 4.2 Ticker Dashboard
- Web app, no login required
- Tickers grouped by asset type; group names come entirely from a config file, not a fixed list — add, rename, split, or remove groups just by editing the file (see Section 7)
- Initial watchlist (from config): SPY, IVW, DGRO (stocks) · VGIT, VGLT (bonds) · VIGI, VYMI, EMB (international) · FTEC + other Fidelity sector ETFs (sector) · MSFT, RELY + other trusted individual stocks (individual)
- **One table per group** (not per-ticker cards). Columns: Ticker, Price, Change, 52-Week Range, % Off High, Market Cap, P/E, 20-day MA, 50-day MA, 200-day MA
- **Market Cap** and **P/E (trailing)** — both from the same Finnhub `/stock/metric` call already used for the 52-week range, so no new fetch. Market cap formats to $T/B/M; either renders "n/a" (not an error) when Finnhub has no value for that symbol
- **52-week range** rendered as a green (near the low)→amber→red (near the high) gradient bar with a marker at the current price's position, plus the low/high printed as text — not color-alone
- **Each moving average** shows the value plus how far the current price sits above/below it, as both a color (green above, red below — same convention as the AI directional badges) and a signed arrow+percentage
- **Percent off 52-week high** — its own column, the exact number behind the range bar's visual read; drives the buy decision directly
- **Change since last close** — its own column, current session's move versus the previous close (absolute and %), colored green-up/red-down
- **Top-discount row highlight** — within each group, roughly the top quarter of tickers (rounded up, minimum 1) by percent off their 52-week high get a faint green row background. Ranked per group, not across the whole page
- No recent-news column
- **US stock market news**, shown once at the top of the page, above the grouped ticker tables — a short feed of general market headlines
- **Loads instantly from a local snapshot cache, then refreshes live in the background** — same pattern as the Indicator Digest Page. A ticker with no cached data yet renders as a loading placeholder; a ticker whose live fetch fails falls back silently to its last cached values, with an error state reserved for a ticker that's never been fetched successfully. Unlike the indicator pipeline, this background check always re-fetches every ticker live — there's no AI call to gate around
- **In-app editing**: each group has a remove button per ticker (the row's trailing column, out of the way of the data readers scan first) and an add-ticker field, writing straight to `config/tickers.json`. Adding, renaming, or removing a whole *group* still needs a hand-edit (backlog, Section 5)

### 4.3 Cross-page navigation
- Both v2 pages show a small nav linking to the other, so you can move between the Indicator Digest Page and the Ticker Dashboard by clicking

### 4.4 Hosted Live Dashboard (v2.1)
- Both v2 pages move from local-only `localhost` to a single free hosted web service, reachable from anywhere without your laptop running or a server started by hand
- **Password-protected**, not public: every route requires a username/password before rendering anything. No user accounts, no signup — just you
- `data/indicators.json` stays git-committed, updated by the existing GitHub Actions workflow exactly as today; the host auto-deploys on every push to `main`, so a scheduled ingestion commit also refreshes the hosted page automatically
- The ticker watchlist (`config/tickers.json`) and the two local snapshot caches (`data/tickers.json`, `data/market_news.json`) move to a small free external key-value store when hosted, since a free host's filesystem doesn't persist across restarts — without this, an in-app ticker edit or a cached snapshot would silently vanish the next time the app restarts. Local development keeps using the plain JSON files as today
- A fresh deploy seeds the hosted ticker config from the repo's committed `config/tickers.json`; after that, in-app edits on the hosted deployment update the external store only — the repo file stops being the hosted deployment's live source of truth (it remains authoritative for local dev)

## 5. Backlog (not yet scheduled)
- ISM Manufacturing New Orders — no free open data feed; add once a paid vendor or workaround is chosen
- Shiller P/E ratio — no clean free API; add via scraping or manual periodic entry
- User accounts / authentication
- Multi-device sync (currently single-device, config-file based)
- In-app group management (add/rename/remove a whole group) — ticker-level add/remove within existing groups is built (Section 4.2)
- Cycle-change / "market top" composite indicator (combining macro + sector signals) to support rare sell decisions
- **Ticker Email Alerts** — email delivery, mirroring current Fidelity behavior, via a background job that checks prices independent of whether the dashboard is open; trigger conditions: price crosses a set threshold, price crosses the 20-day or 200-day moving average, price moves a set % above 52-week low or below 52-week high
- **Discount-Buy Thresholds** — alert when a ticker is a configurable % off its 52-week high, with a global default and per-ticker override; reuses the Ticker Email Alerts pipeline above

## 6. Data Sources
| Need | Source | Notes |
|---|---|---|
| Macro indicators (all v1 indicators) | FRED | Free, official, no rate-limit concerns |
| Economic release calendar (next-release countdown) | FRED release calendar | Needed for CPI/jobs report/FOMC dates |
| AI interpretation of indicators | Gemini API (free tier) | Plain-English summary + directional read; framed as informational commentary, not advice |
| *(v2, ticker dashboard)* Price, 52-wk range | Finnhub | Free tier has ~20 min delay; acceptable given Monday-cadence buying. 52-wk range uses `/stock/metric` (`/stock/candle` is paid-tier-only) |
| *(v2, ticker dashboard)* Moving averages (20d/50d/200d) | Yahoo Finance (public chart endpoint) | Finnhub's free tier has no daily-close source; Yahoo's chart endpoint is free, unauthenticated, and unlike stooq.io doesn't gate requests behind a bot challenge |
| *(v2, ticker dashboard)* Percent off 52-week high | *(computed, no new source)* | `(week52_high - price) / week52_high` |
| *(v2, ticker dashboard)* Change since last close | Finnhub | Returned by the existing quote call (`d`/`dp` fields) |
| *(v2, ticker dashboard)* US stock market news | Finnhub | `/news?category=general`, filtered to Finnhub's `"top news"` tag |
| *(v2.1, hosted dashboard)* Persistent ticker config + caches when hosted | Upstash Redis (REST API) | Free tier, no auto-pause; stores `config/tickers.json`'s content plus the two local snapshot caches as JSON blobs, since the host has no persistent disk |
| *(backlog)* Shiller P/E | multpl.com or similar | No single clean free API; may need light scraping or manual entry |
| *(backlog)* ISM Manufacturing New Orders | Paid vendor or workaround TBD | No free open feed available |

## 7. Config File (v2 ticker list) — Format
```json
{
  "groups": {
    "stocks": ["SPY", "IVW", "DGRO"],
    "bonds": ["VGIT", "VGLT"],
    "international": ["VIGI", "VYMI", "EMB"],
    "sector": ["FTEC"],
    "individual": ["MSFT", "RELY"]
  }
}
```
`groups` is an open map, not a fixed set of keys — the dashboard renders whatever group names and tickers are in this file, in the order they appear. Add a group, rename one, or move a ticker between groups just by editing the file; no code change needed.

## 8. Open Questions / Risks
- The Indicator Digest Page's live-pull-on-reload requirement (Section 4.1) means v2 needs a server that can run the fetch/AI-interpretation logic on demand, not just a static page reading committed JSON — resolved by running that server locally, and (Section 4.4) on a hosted free web service
- A background check happens on every page visit, so FRED calls happen per-visit rather than only on the fixed ingestion schedule — worth checking this stays within free-tier rate limits. Gemini calls only happen when the check actually finds new data
- Local-only hosting means the Indicator Digest Page and Ticker Dashboard are only reachable when you've started the server on your own machine — unlike the v1 email, which arrives regardless of whether your laptop is on. Section 4.4's hosted deployment removes this limitation, at the cost of a cold-start delay after idle periods on the free tier
- Release calendar dates occasionally shift — pre-release timing should tolerate last-minute date changes
- Free-tier data APIs (v2 ticker dashboard) carry rate limits and/or ~20 min delay; acceptable given usage pattern, flagged as a future constraint if needs change
- Gmail requires generating an "app password" (not your regular password) to send via SMTP from a script
- Commit-based storage means each workflow run needs write access to push back to the repo

## 9. Explicitly Out of Scope (for now)
- Trading execution (this is a monitoring/alerting tool, not a brokerage integration)
- Short selling / options / individual stocks outside your trusted list
- Mobile app (web-only, per your device answer)

## 10. Chosen Stack (v1)
- **Scheduler + compute:** GitHub Actions scheduled workflow — runs the FRED fetch/ingest/email logic on GitHub's servers on a recurring schedule; free tier (2,000 min/mo) is far more than needed
- **Storage:** Commit-based data file (JSON) written back into the repo each run — no separate database to manage
- **Email:** Gmail SMTP with an app password
- **Data:** FRED API (all 8 v1 indicators + release calendar)
- **AI interpretation:** Gemini API (`gemini-3.8-flash`, free tier)

Fully free, and reliable regardless of whether your own laptop is on. Known limitation: GitHub's scheduled workflows aren't perfectly precise (can be delayed by minutes) and, under heavy platform load, can occasionally drop a scheduled run entirely — a low risk for a job that only needs to run every few hours for monthly-cadence indicators. If this becomes a problem in practice, revisit AWS EventBridge/Lambda for the scheduler.
