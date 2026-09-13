# Investment Dashboard — Software Requirements

**Status:** v1 shipped; v1.1 in planning
**Owner:** You (customer) / Claude (PM)
**Last updated:** 2026-09-12

## 1. Problem Statement
Replace the manual parts of a daily investment-monitoring workflow currently split across the Fidelity website (requires login) and a hand-updated Google Sheet. The goal is not to change the investment strategy, but to remove manual data entry and the login requirement, and to encode personalized alert logic that Fidelity's built-in alerts don't support.

## 2. User & Usage Pattern
- Single user (you), single device to start (desktop/web browser)
- Active review: Mondays (buy day)
- Passive monitoring: daily glances for major news / discount opportunities
- Rare sell-side activity: long-term hold strategy, sells only near suspected market cycle tops

## 3. Scope for v1 (~2 weeks) — Macroeconomic Indicators (Backend-First)

Reprioritized: this is the workflow gap that doesn't exist anywhere today (unlike the ticker dashboard, which is partially covered by your existing Google Sheet). v1 is backend-focused — get the data pipeline and emails working reliably before investing in dashboard polish.

Indicator set (unchanged from our earlier discussion), organized into categories:

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

All of the above are available via FRED, so v1 can run on a single free data source with no scraping or paid vendor needed.

v1's entire product surface is a single digest email — there is no webpage/dashboard/visual layer in v1. The three items below (3.1-3.3) are content sections of that one email, not separate features:

### 3.1 Digest Email with Holistic AI Interpretation (Priority 1)
- Sent whenever at least one indicator publishes a new value — one email per triggering run, not one per indicator
- AI interpretation reasons across all 8 indicators' recent history together (not just the one(s) that changed), so it can connect indicators to each other
- Includes: a plain-English explanation of what changed and why it matters, and one overall directional opinion (bullish / bearish / neutral)
- **Guardrail:** framed as informational commentary based on indicator trends, not personalized financial advice — labeled as such in the email

### 3.2 Indicator Table (Priority 2, in the same email)
- A table (not full charts yet — that's a fast-follow polish item) showing each indicator's current value and recent history, grouped by leading/coincident/lagging/valuation
- Backed by a running historical store per indicator (a rolling 12-month window of values, not just the latest) — older readings are pruned since they're no longer useful for a trend view

### 3.3 Next-Indicator Preview (Priority 3, in the same email)
- Shows what's coming next and when (e.g. "CPI releases in 3 days"), pulled from an economic release calendar (FRED release calendar or BLS release schedule)
- Surfaced in the digest email's table — no standalone pre-release email in v1 (not needed for macro indicators; may revisit for ticker price alerts later, see the Ticker Email Alerts backlog item in Section 5)

## 4. Fast-Follow (v1.1, in planning) — Web Dashboard

### 4.1 Indicator Digest Page
- A web page rendering of the same content already delivered in the v1 digest email (Section 3.1–3.3): the holistic AI interpretation, the indicator table, and the next-indicator preview
- **Hosting (v1.1): local-only.** Runs on your own machine (e.g. `localhost`), started when you want to check it — not deployed to a public host. Chosen to avoid both a domain purchase and exposing the page publicly; GitHub Pages (the free, no-domain option) was considered but ruled out since it's static-only and can't run the server-side live pull below (which also needs to keep API keys server-side, off any public static page). Hosting this somewhere reachable without running it locally is deferred — see Section 5 Backlog
- No login required (moot while local-only, since it's never exposed to the network)
- **Loads instantly from stored data, then checks for updates in the background.** The initial page render never waits on a live pull — it shows the last stored snapshot immediately. The page then checks for new data on its own; if it finds at least one indicator with a genuinely new value, it updates just the affected parts of the page (the table, the countdown, the AI section) in place, without a full reload. If nothing's new, the page is left exactly as it was — there's no reason to touch it, or to spend an AI call re-interpreting data that hasn't changed
- Fallback: if the background check fails outright (source API down, rate-limited, etc.) or simply finds nothing new, the page just stays on the last stored data — same outcome either way from the reader's perspective
- While that background check is running, the page shows a visible "checking for updates" indicator so it's never ambiguous whether a check is actually happening; it disappears once the check settles either way. (An earlier draft of this requirement also called for a persistent Live/Saved freshness label with a timestamp; both were dropped after initial use — found distracting in practice, and the in-place content updates plus the checking indicator already answer "is this current?" well enough)
- The indicator table includes a small trend sparkline per indicator (inline SVG — a browser page doesn't need the raster-image workaround the email uses for sparklines, since browsers render SVG natively)
- Backed by the same historical data store the v1 email pipeline already writes to for the stored/initial render and for history; a background check that finds new data updates that store too, so the email pipeline and the page stay consistent
- **v1.1 storage extension:** v1's store only persists raw indicator values, not the AI-generated summary/directional read (each email's AI content was generated fresh and never saved). For the fallback path to show something meaningful rather than just the table, v1.1 must also persist the most recent successful AI response (summary + directional read + the timestamp it was generated), overwritten on each new successful interpretation
- Complements rather than replaces the digest email; the email still fires on the existing trigger (Section 3.1), the page is for on-demand lookup

### 4.2 Ticker Dashboard
- Web app, no login required for v1.1
- Tickers grouped by asset type; the group names themselves come entirely from your config file, not a fixed list baked into the app — add, rename, split, or remove groups just by editing the file (see Section 7)
- Initial watchlist (from your config): SPY, IVW, DGRO (stocks) · VGIT, VGLT (bonds) · VIGI, VYMI, EMB (international) · FTEC + other Fidelity sector ETFs (sector) · MSFT, RELY + other trusted individual stocks (individual)
- Per-ticker card shows: current price, 52-week range, 20-day moving average, 200-day moving average, recent related news
- Add/remove tickers, and add/remove/rename groups, via a local config file (JSON), editable by hand — no separate editor UI in v1.1 (an in-app editor remains a backlog item, Section 5)

## 5. Backlog (v2+, not yet scheduled)
- ISM Manufacturing New Orders — deferred, no free open data feed; add once a paid vendor or workaround is chosen
- Shiller P/E ratio — deferred, no clean free API; add via scraping or manual periodic entry
- User accounts / authentication
- Multi-device sync (currently single-device, config-file based)
- In-app ticker management UI (no-login-required editor) as an alternative to hand-editing the config file
- Cycle-change / "market top" composite indicator (combining macro + sector signals) to support your rare sell decisions
- **Ticker Email Alerts** (moved out of v1.1 on 2026-09-12) — email delivery, mirroring current Fidelity behavior, via a background job that checks prices periodically independent of whether the dashboard is open; trigger conditions: price crosses a set threshold, price crosses the 20-day or 200-day moving average, price moves a set % above 52-week low or below 52-week high
- **Discount-Buy Thresholds** (moved out of v1.1 on 2026-09-12) — alert when a ticker is a configurable % off its 52-week high, with a global default threshold and per-ticker override; was designed to reuse the Ticker Email Alerts pipeline above
- **Hosted (non-local) live dashboard** (added 2026-09-12) — move the Indicator Digest Page (and/or Ticker Dashboard) off `localhost` onto somewhere reachable without your laptop running, once a hosting approach is chosen that avoids both a paid domain and public exposure (e.g. a free-tier host's auto-generated subdomain gated by a shared password/Basic Auth, since GitHub Pages can't run the live-pull server-side logic)

## 6. Data Sources (proposed)
| Need | Candidate | Notes |
|---|---|---|
| Macro indicators (all v1 indicators: claims, yield curve, permits, payrolls, industrial production, Fed rate, CPI, unemployment) | FRED | Free, official, no rate-limit concerns — single source covers all of v1 |
| Economic release calendar (for the next-release countdown) | FRED release calendar | Needed to know upcoming CPI/jobs report/FOMC dates |
| AI interpretation of indicators | Gemini API (free tier) | Generates plain-English summary + directional read; framed as informational commentary, not advice |
| *(v1.1, ticker dashboard)* Price, 52-wk range | Finnhub | Free tier has ~20 min delay; acceptable given Monday-cadence buying. `/stock/candle` turned out to be paid-tier-only (confirmed 2026-09-13), so the 52-wk range uses Finnhub's separate `/stock/metric` endpoint instead, which is still free |
| *(v1.1, ticker dashboard)* Moving averages (20d/200d) | Yahoo Finance (public chart endpoint) | Finnhub's free tier has no daily-close source at all; Yahoo's undocumented chart endpoint is free, unauthenticated, and (unlike stooq.io, tried first) doesn't gate requests behind a bot challenge |
| *(v1.1, ticker dashboard)* Ticker-related news | Finnhub | Still free, no change |
| *(backlog)* Shiller P/E | multpl.com or similar | No single clean free API; may need light scraping or manual periodic entry |
| *(backlog)* ISM Manufacturing New Orders | Paid vendor or workaround TBD | No free open feed available |

*Final source selection to be confirmed once we scope the technical build.*

## 7. Config File (v1.1 ticker list) — Draft Format
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
*Note: `groups` is an open map, not a fixed set of four keys — the dashboard renders whatever group names and tickers are in this file, in the order they appear. Add a new group, rename one, or move a ticker between groups just by editing the file; no code change needed. The `sector`/`individual` split above replaces an earlier combined `sector_and_individual` group.*

*Note: the `alert_defaults`/`alert_overrides` fields from the earlier draft moved to the Backlog (Section 5) along with Ticker Email Alerts and Discount-Buy Thresholds; re-add them here if/when that work is picked back up.*

## 8. Open Questions / Risks
- Timeline is ~2 weeks; requires a hosted background scheduler + email sending — GitHub Actions + Gmail SMTP selected (Section 10) to meet this without added cost
- The Indicator Digest Page's live-pull-on-reload requirement (Section 4.1) means v1.1 needs a server that can run the fetch/AI-interpretation logic on demand at request time, not just a static page reading committed JSON — resolved for now by running that server locally (Section 4.1); revisit if/when the Hosted live dashboard backlog item (Section 5) is picked up
- A background check happens on every page visit, so FRED calls happen on a per-visit basis rather than only on the fixed ingestion schedule — worth checking this stays comfortably within free-tier rate limits given single-user, low-frequency usage. Gemini calls, however, only happen when the check actually finds new data, so this is much less of a concern for the AI API specifically than an earlier draft assumed
- Local-only hosting means the Indicator Digest Page (and Ticker Dashboard) are only reachable when you've started the server on your own machine — unlike the v1 email, which arrives regardless of whether your laptop is on
- Release calendar dates occasionally shift — pre-release email timing should tolerate last-minute date changes
- Free-tier data APIs (for the v1.1 ticker dashboard) carry rate limits and/or ~20 min delay; acceptable given your usage pattern, but flagged as a future constraint if needs change
- Gmail requires generating an "app password" (not your regular password) to send via SMTP from a script — a one-time setup step in your Google Account security settings
- Commit-based storage means each workflow run needs write access to push back to the repo — the workflow will need a token with repo write permission (GitHub provides this automatically for workflows in the same repo)

## 9. Explicitly Out of Scope (for now)
- Trading execution (this is a monitoring/alerting tool, not a brokerage integration)
- Short selling / options / individual stocks outside your trusted list
- Mobile app (web-only for v1, per your device answer)

## 10. Chosen Stack (v1)
- **Scheduler + compute:** GitHub Actions scheduled workflow — runs the FRED fetch/ingest/email logic on GitHub's servers on a recurring schedule; free tier (2,000 min/mo) is far more than needed
- **Storage:** Commit-based data file (e.g. JSON) written back into the repo each run — no separate database to manage
- **Email:** Gmail SMTP with an app password — no new service to set up beyond your existing Gmail account
- **Data:** FRED API (all 8 v1 indicators + release calendar)
- **AI interpretation:** Gemini API (`gemini-3.8-flash`, free tier)

Note: fully free, and reliable regardless of whether your own laptop is on. Known limitation: GitHub's scheduled workflows aren't perfectly precise (can be delayed by minutes) and, under heavy platform load, can occasionally drop a scheduled run entirely — a real but low risk for a job that only needs to run every few hours for monthly-cadence indicators. If this becomes a problem in practice, revisit AWS EventBridge/Lambda for the scheduler.
