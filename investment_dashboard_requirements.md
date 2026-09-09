# Investment Dashboard — Software Requirements

**Status:** Draft v1
**Owner:** You (customer) / Claude (PM)
**Last updated:** 2026-09-04

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

### 3.1 Post-Release Email with AI Interpretation (Priority 1)
- Sent when a new indicator value is published
- Includes: the new value, how it compares to the prior reading/trend, a plain-English explanation of what changed and why it matters, and a directional opinion (bullish / bearish / neutral)
- **Guardrail:** framed as informational commentary based on indicator trends, not personalized financial advice — labeled as such in the email

### 3.2 Indicator Table (Priority 2)
- A table (not full charts yet — that's a fast-follow polish item) showing each indicator's current value and recent history, grouped by leading/coincident/lagging/valuation
- Backed by a running historical store per indicator (a rolling 12-month window of values, not just the latest), so a trend view is possible once we build the visual layer — older readings are pruned since they're no longer useful for a trend view

### 3.3 Next-Indicator Preview (Priority 3)
- Shows what's coming next and when (e.g. "CPI releases in 3 days"), pulled from an economic release calendar (FRED release calendar or BLS release schedule)
- Surfaced in the indicator table only — no standalone pre-release email in v1 (not needed for macro indicators; may revisit for ticker price alerts later, see Section 4.2)

## 4. Fast-Follow (v1.1, right after v1 ships) — Ticker Dashboard & Alerts

### 4.1 Ticker Dashboard
- Web app, no login required for v1.1
- Tickers grouped by asset type: **Stocks / Bonds / International / Sector ETFs**
- Initial watchlist (from your config): SPY, IVW, DGRO (stocks) · VGIT, VGLT (bonds) · VIGI, VYMI, EMB (international) · FTEC + other sector ETFs, MSFT + trusted individual stocks (sector/individual)
- Per-ticker card shows: current price, 52-week range, 20-day moving average, 200-day moving average, recent related news
- Add/remove tickers via a local config file (JSON), editable by hand

### 4.2 Ticker Email Alerts
- Delivered via email (mirrors current Fidelity behavior)
- Requires a background job that checks prices periodically, independent of whether the dashboard is open
- Trigger conditions:
  - Price crosses above/below a set threshold
  - Price crosses the 20-day or 200-day moving average
  - Price moves a set % above 52-week low or below 52-week high

### 4.3 Discount-Buy Thresholds
- Alert when a ticker is a configurable % off its 52-week high
- Global default threshold, with per-ticker override
- Reuses the same alert/email pipeline as Section 4.2

## 5. Backlog (v2+, not yet scheduled)
- ISM Manufacturing New Orders — deferred, no free open data feed; add once a paid vendor or workaround is chosen
- Shiller P/E ratio — deferred, no clean free API; add via scraping or manual periodic entry
- User accounts / authentication
- Multi-device sync (currently single-device, config-file based)
- In-app ticker management UI (no-login-required editor) as an alternative to hand-editing the config file
- Cycle-change / "market top" composite indicator (combining macro + sector signals) to support your rare sell decisions

## 6. Data Sources (proposed)
| Need | Candidate | Notes |
|---|---|---|
| Macro indicators (all v1 indicators: claims, yield curve, permits, payrolls, industrial production, Fed rate, CPI, unemployment) | FRED | Free, official, no rate-limit concerns — single source covers all of v1 |
| Economic release calendar (for the next-release countdown) | FRED release calendar | Needed to know upcoming CPI/jobs report/FOMC dates |
| AI interpretation of indicators | Claude API | Generates plain-English summary + directional read; framed as informational commentary, not advice |
| *(v1.1, ticker dashboard)* Price, 52-wk range, moving averages | Finnhub | Free tier has ~20 min delay; acceptable given Monday-cadence buying |
| *(v1.1, ticker dashboard)* Ticker-related news | Finnhub | Same provider, simplifies integration |
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
    "sector_and_individual": ["FTEC", "MSFT"]
  },
  "alert_defaults": {
    "discount_pct_below_52wk_high": 15
  },
  "alert_overrides": {
    "MSFT": { "discount_pct_below_52wk_high": 20 }
  }
}
```

## 8. Open Questions / Risks
- Timeline is ~2 weeks; requires a hosted background scheduler + email sending — GitHub Actions + Gmail SMTP selected (Section 10) to meet this without added cost
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
- **AI interpretation:** Claude API

Note: fully free, and reliable regardless of whether your own laptop is on. Known limitation: GitHub's scheduled workflows aren't perfectly precise (can be delayed by minutes) and, under heavy platform load, can occasionally drop a scheduled run entirely — a real but low risk for a job that only needs to run every few hours for monthly-cadence indicators. If this becomes a problem in practice, revisit AWS EventBridge/Lambda for the scheduler.
