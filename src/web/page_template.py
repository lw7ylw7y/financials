"""HTML rendering for both v2 pages: the Indicator Digest Page and the
Ticker Dashboard.

A browser page, not an email, so this doesn't inherit email_template.py's
Outlook-safe inline-style-table constraints or its CID-image sparklines —
trend lines here are plain inline <svg> (see _render_sparkline_svg),
since a browser (unlike most email clients) renders SVG natively. It
does reuse email_template's copy/color constants (disclaimer text,
category labels, directional badge colors) so the two surfaces never
drift out of sync on wording or meaning, even though the markup itself
is page-specific.
"""

import os
import sys
from html import escape

_WEB_DIR = os.path.dirname(os.path.abspath(__file__))
_SRC_DIR = os.path.dirname(_WEB_DIR)
for _subdir in ("fred", "storage", "digest", "mailer"):
    sys.path.insert(0, os.path.join(_SRC_DIR, _subdir))

from email_template import CATEGORY_LABELS, CATEGORY_ORDER, DIRECTIONAL_STYLE, DISCLAIMER

# Reuses the indicator digest's own bullish/bearish/neutral palette
# rather than inventing a second green/red/gray scale -- "discount" is
# the same "good" read as "bullish", "overpriced" the same "bad" read
# as "bearish", "fair" the same neutral gray.
VALUATION_STYLE = {
    "discount": DIRECTIONAL_STYLE["bullish"],
    "fair": DIRECTIONAL_STYLE["neutral"],
    "overpriced": DIRECTIONAL_STYLE["bearish"],
}
VALUATION_HEADINGS = {"discount": "Discount", "fair": "Fair", "overpriced": "Overpriced"}
# Distinct from email_template.DISCLAIMER, which is worded specifically
# around "indicator trends" -- this section is about ticker valuation,
# not the macro indicators, so it needs its own wording.
VALUATION_DISCLAIMER = (
    "This is automated commentary based on the price and fundamentals data "
    "shown above, not personalized financial advice."
)

# Mirrors src/mailer/sparkline.py's palette so the email and web trend
# lines read as the same feature, even though the email renders its
# version as a matplotlib PNG (email clients strip <svg>) and this one
# is a plain inline <svg> (fine in a browser, no such workaround needed).
SPARKLINE_WIDTH = 90
SPARKLINE_HEIGHT = 24
SPARKLINE_LINE_COLOR = "#2563eb"
SPARKLINE_FILL_COLOR = "#2563eb"
SPARKLINE_UP_COLOR = "#15803d"
SPARKLINE_DOWN_COLOR = "#b91c1c"
SPARKLINE_FLAT_COLOR = "#64748b"

# Status scale for the 52-week range bar: good (near the low, cheap) ->
# warning (mid-range) -> critical (near the high, expensive). Reuses the
# same green/red already established above for up/down, plus one amber
# step for the middle -- not a new, unrelated palette.
RANGE_GOOD_COLOR = SPARKLINE_UP_COLOR
RANGE_WARNING_COLOR = "#f59e0b"
RANGE_CRITICAL_COLOR = SPARKLINE_DOWN_COLOR
RANGE_BAR_WIDTH = 90
RANGE_BAR_HEIGHT = 10

NAV_LINKS = [("/", "Indicator Digest"), ("/tickers", "Ticker Dashboard")]


def _render_sparkline_svg(values: list[float]) -> str:
    """Minimal inline-SVG trend line for a table row, mirroring
    mailer.sparkline.render_sparkline's look (line + light fill +
    a green/red/gray endpoint dot for up/down/flat vs. the prior
    value). A single-point history renders as just the dot.
    """
    w, h = SPARKLINE_WIDTH, SPARKLINE_HEIGHT
    pad = 3
    if len(values) < 2:
        cx, cy = w - pad, h / 2
        return (
            f'<svg class="sparkline" width="{w}" height="{h}" viewBox="0 0 {w} {h}" '
            f'role="img" aria-label="trend unavailable">'
            f'<circle cx="{cx}" cy="{cy}" r="2.4" fill="{SPARKLINE_FLAT_COLOR}"/></svg>'
        )

    lo, hi = min(values), max(values)
    value_range = hi - lo
    span = value_range if value_range else 1

    def x_at(i: int) -> float:
        return pad + (w - 2 * pad) * i / (len(values) - 1)

    def y_at(v: float) -> float:
        return pad + (h - 2 * pad) * (1 - (v - lo) / span)

    points = [(x_at(i), y_at(v)) for i, v in enumerate(values)]
    line_points = " ".join(f"{x:.1f},{y:.1f}" for x, y in points)
    fill_points = f"{points[0][0]:.1f},{h - pad:.1f} " + line_points + f" {points[-1][0]:.1f},{h - pad:.1f}"

    if values[-1] > values[-2]:
        endpoint_color = SPARKLINE_UP_COLOR
    elif values[-1] < values[-2]:
        endpoint_color = SPARKLINE_DOWN_COLOR
    else:
        endpoint_color = SPARKLINE_FLAT_COLOR
    end_x, end_y = points[-1]

    return (
        f'<svg class="sparkline" width="{w}" height="{h}" viewBox="0 0 {w} {h}" '
        f'role="img" aria-label="trend line">'
        f'<polygon points="{fill_points}" fill="{SPARKLINE_FILL_COLOR}" opacity="0.12"/>'
        f'<polyline points="{line_points}" fill="none" stroke="{SPARKLINE_LINE_COLOR}" '
        f'stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"/>'
        f'<circle cx="{end_x:.1f}" cy="{end_y:.1f}" r="2.4" fill="{endpoint_color}"/>'
        f"</svg>"
    )

def _render_nav(active_path: str) -> str:
    """Shared nav so either v2 page links to the other -- clicking
    between the Indicator Digest Page and the Ticker Dashboard doesn't
    require typing a URL."""
    links = []
    for path, label in NAV_LINKS:
        css_class = "active" if path == active_path else ""
        links.append(f'<a href="{path}" class="{css_class}">{escape(label)}</a>')
    return f'<nav class="site-nav">{"".join(links)}</nav>'


def _render_ai_section(ai_result: dict | None) -> str:
    if ai_result is None:
        return """
        <section class="card">
          <p class="muted">No AI interpretation on file yet.</p>
        </section>"""

    style = DIRECTIONAL_STYLE[ai_result["directional_read"]]
    return f"""
        <section class="card" style="background:{style['bg']};border-left:4px solid {style['accent']};">
          <p class="ai-summary">{escape(ai_result['summary'])}</p>
          <span class="directional-badge" style="color:{style['text']};">{style['label']}</span>
          <p class="disclaimer">{escape(DISCLAIMER)}</p>
        </section>"""


def _render_table_section(table: dict) -> str:
    sections = []
    for category in CATEGORY_ORDER:
        rows = table.get(category, [])
        if not rows:
            continue

        row_html = []
        for row in rows:
            prior = f"{row['prior_value']:g}" if row["prior_value"] is not None else "n/a"
            sparkline = _render_sparkline_svg(row["sparkline_values"])
            row_html.append(f"""
              <tr>
                <td>{escape(row['name'])}</td>
                <td class="sparkline-cell">{sparkline}</td>
                <td class="num">{row['latest_value']:g}</td>
                <td class="num muted">{escape(row['latest_date'])}</td>
                <td class="num muted">prior: {prior}</td>
              </tr>""")

        sections.append(f"""
        <div class="category-block">
          <p class="category-label">{CATEGORY_LABELS[category]}</p>
          <table class="indicator-table">
            {''.join(row_html)}
          </table>
        </div>""")
    return "".join(sections)


def _render_countdown_section(countdown: dict) -> str:
    if not countdown["entries"]:
        return ""

    soonest = countdown["soonest"]
    other_rows = []
    for entry in countdown["entries"]:
        if entry["key"] == soonest["key"]:
            continue
        other_rows.append(f"""
          <tr>
            <td>{escape(entry['name'])}</td>
            <td class="num muted">in {entry['days_until']} day(s) &middot; {escape(entry['next_release_date'])}</td>
          </tr>""")

    return f"""
        <section class="card countdown">
          <p class="category-label">Next Releases</p>
          <p>
            <span class="next-up-badge">Next up</span>
            <strong>{escape(soonest['name'])}</strong>
            &mdash; in {soonest['days_until']} day(s) ({escape(soonest['next_release_date'])})
          </p>
          {f'<table class="indicator-table">{"".join(other_rows)}</table>' if other_rows else ''}
        </section>"""


def render_indicator_digest_page(data: dict) -> str:
    """`data` per live_pull.get_initial_page_data: table, countdown,
    ai_result — always built from stored data, so this renders
    instantly. The page's own script then calls /api/check in the
    background; if that finds at least one indicator with a genuinely
    new value, it patches #table-section / #countdown-section /
    #ai-section in place. If nothing's new, the check costs a FRED call
    but never an AI call, and the page is left exactly as rendered here
    — no point re-rendering (or re-billing Gemini) for a no-op. A
    "Checking for updates..." indicator is shown for the duration of
    that call and removed once it settles (updated, no-op, or failed
    alike), so the reader always knows whether a check is actually in
    flight.
    """
    return f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <title>Indicator Digest</title>
  <link rel="stylesheet" href="/static/dashboard.css">
</head>
<body>
  <main class="page">
    {_render_nav("/")}
    <header class="page-header">
      <h1>Indicator Digest</h1>
      <div class="header-meta">
        <span class="checking-indicator muted" id="checking-indicator">Checking for updates&hellip;</span>
      </div>
    </header>

    <div id="ai-section">{_render_ai_section(data['ai_result'])}</div>
    <div id="table-section">{_render_table_section(data['table'])}</div>
    <div id="countdown-section">{_render_countdown_section(data['countdown'])}</div>

    <footer class="page-footer">
      <p class="muted">Automated macro indicator digest &middot; data from FRED &middot; checks for live updates in the background</p>
    </footer>
  </main>
  <script>
    function hideCheckingIndicator() {{
      var el = document.getElementById('checking-indicator');
      if (el) el.remove();
    }}
    fetch('/api/check').then(function(r) {{ return r.json(); }}).then(function(data) {{
      hideCheckingIndicator();
      if (!data.data_updated) return;
      document.getElementById('table-section').innerHTML = data.table_html;
      document.getElementById('countdown-section').innerHTML = data.countdown_html;
      if (data.ai_html) {{
        document.getElementById('ai-section').innerHTML = data.ai_html;
      }}
    }}).catch(function() {{ hideCheckingIndicator(); /* stay on the stored snapshot already shown */ }});
  </script>
</body>
</html>"""


def _group_header(group_name: str) -> str:
    """Section header derived straight from the config key, e.g.
    "sector" -> "Sector" -- never a fixed lookup, so a new or renamed
    group in config/tickers.json appears correctly with no code change."""
    return group_name.replace("_", " ").replace("-", " ").title()


def _render_range_bar(symbol: str, low: float, high: float, price: float) -> str:
    """52-week range as a green (near the low, cheap) -> amber ->
    red (near the high, expensive) status gradient, with a marker at
    the current price's position -- a continuous read of "where in its
    range does this sit", not just the raw numbers. Never color-alone:
    the low/high are printed as text below the bar, and the exact price
    is its own table column, so the read survives without color too.
    """
    w, h = RANGE_BAR_WIDTH, RANGE_BAR_HEIGHT
    span = high - low
    pct = 0.5 if span <= 0 else max(0.0, min(1.0, (price - low) / span))
    marker_x = pct * w
    gradient_id = f"range-grad-{escape(symbol)}"

    return f"""
            <div class="range-cell">
              <svg class="range-bar" width="{w}" height="{h}" viewBox="0 0 {w} {h}" role="img"
                   aria-label="52-week range ${low:,.2f} to ${high:,.2f}, current price ${price:,.2f}">
                <defs>
                  <linearGradient id="{gradient_id}" x1="0" y1="0" x2="1" y2="0">
                    <stop offset="0%" stop-color="{RANGE_GOOD_COLOR}"/>
                    <stop offset="50%" stop-color="{RANGE_WARNING_COLOR}"/>
                    <stop offset="100%" stop-color="{RANGE_CRITICAL_COLOR}"/>
                  </linearGradient>
                </defs>
                <rect x="0" y="{h / 2 - 3:.1f}" width="{w}" height="6" rx="3" fill="url(#{gradient_id})"/>
                <circle cx="{marker_x:.1f}" cy="{h / 2:.1f}" r="3.5" fill="#fff" stroke="#0f172a" stroke-width="1.3"/>
              </svg>
              <div class="range-labels muted">
                <span>${low:,.2f}</span><span>${high:,.2f}</span>
              </div>
            </div>"""


def _render_change_cell(change: float | None, change_percent: float | None) -> str:
    """Today's price move vs. the previous close -- same never-color-
    alone convention as the moving-average cells: a signed arrow +
    percentage alongside the color, plus the absolute $ change. "n/a"
    if Finnhub's quote response didn't carry these fields.
    """
    if change is None or change_percent is None:
        return '<td class="num muted">n/a</td>'

    if change > 0:
        css_class, arrow, color = "up", "&#9650;", SPARKLINE_UP_COLOR
    elif change < 0:
        css_class, arrow, color = "down", "&#9660;", SPARKLINE_DOWN_COLOR
    else:
        css_class, arrow, color = "flat", "", SPARKLINE_FLAT_COLOR

    return (
        f'<td class="num">{change:+,.2f} '
        f'<span class="ma-delta {css_class}" style="color:{color};">{arrow}{abs(change_percent):.2f}%</span></td>'
    )


def _render_pct_off_high_cell(pct_off_high: float | None) -> str:
    """How far below the 52-week high the current price sits, as a
    plain number -- a precise complement to the range bar's visual
    read, which already carries the color signal, so this cell
    deliberately doesn't repeat it.
    """
    if pct_off_high is None:
        return '<td class="num muted">n/a</td>'
    return f'<td class="num">{pct_off_high:.1f}%</td>'


def _format_market_cap(market_cap: float) -> str:
    """`market_cap` is Finnhub's `marketCapitalization`, in millions of
    USD -- convert to dollars, then pick the largest suffix (T/B/M)
    that keeps the number readable at a glance rather than printing a
    raw multi-digit millions figure."""
    value = market_cap * 1_000_000
    if value >= 1_000_000_000_000:
        return f"${value / 1_000_000_000_000:.2f}T"
    if value >= 1_000_000_000:
        return f"${value / 1_000_000_000:.2f}B"
    return f"${value / 1_000_000:.2f}M"


def _render_market_cap_cell(market_cap: float | None) -> str:
    if market_cap is None:
        return '<td class="num muted">n/a</td>'
    return f'<td class="num">{_format_market_cap(market_cap)}</td>'


def _render_pe_cell(pe_ratio: float | None) -> str:
    """Trailing P/E as a plain number -- "n/a" when there's nothing to
    show, not an error: Finnhub has none (common for money-losing or
    thinly-covered companies, see `finnhub_client.fetch_stock_metrics`)
    and, for the equity-fund groups, Yahoo's aggregate-holdings fallback
    also came up empty (`ticker_dashboard._EQUITY_ETF_GROUPS`,
    `yahoo_client.fetch_etf_pe_ratio`).
    """
    if pe_ratio is None:
        return '<td class="num muted">n/a</td>'
    return f'<td class="num">{pe_ratio:.1f}</td>'


def _render_peg_cell(peg_ratio: float | None) -> str:
    """PEG (P/E to growth) as a plain number -- "n/a" when Finnhub has
    none (common for companies with no analyst growth estimate, or any
    ETF, since Finnhub never computes fund-level fundamentals at all;
    see `finnhub_client.fetch_stock_metrics`). Unlike `pe_ratio`, there
    is no Yahoo fallback for this field -- its aggregate-holdings
    module has no PEG equivalent for a fund.
    """
    if peg_ratio is None:
        return '<td class="num muted">n/a</td>'
    return f'<td class="num">{peg_ratio:.2f}</td>'


def _render_remove_ticker_button(symbol: str, group_name: str) -> str:
    """A small "x" on every row (pending/errored/live alike -- removal
    doesn't depend on a successful fetch) that posts to
    /api/tickers/remove. Rendered as the row's own trailing cell rather
    than next to the ticker symbol, so it doesn't crowd the column
    readers scan first. Event-delegated in the page's own script
    rather than bound per-button, since a row's whole group block gets
    replaced wholesale whenever that group's own check response lands."""
    return (
        f'<button type="button" class="remove-ticker" data-group="{escape(group_name)}" '
        f'data-symbol="{escape(symbol)}" title="Remove {escape(symbol)} from {escape(group_name)}" '
        f'aria-label="Remove {escape(symbol)}">&times;</button>'
    )


_TICKER_DATA_COLUMN_COUNT = 7  # Price, Change, 52-Week Range, % Off High, Market Cap, P/E, PEG


def _render_ticker_row(card: dict) -> str:
    """`data-symbol`/`data-pct-off-high` on the `<tr>` are read by the
    page's own client-side sort script (see render_ticker_dashboard_page)
    so a click on the Ticker/% Off High header can reorder rows without a
    server round trip; `data-pct-off-high` is left empty for a pending or
    errored card, which the sort script treats as sorting last rather than
    as zero."""
    symbol_attr = escape(card["symbol"], quote=True)
    pct_off_high_attr = "" if card["pct_off_high"] is None else f"{card['pct_off_high']}"
    row_attrs = f' data-symbol="{symbol_attr}" data-pct-off-high="{pct_off_high_attr}"'
    remove_cell = f"<td>{_render_remove_ticker_button(card['symbol'], card['group'])}</td>"

    if card["pending"]:
        return f"""
              <tr{row_attrs}>
                <td>{escape(card['symbol'])}</td>
                <td colspan="{_TICKER_DATA_COLUMN_COUNT}" class="muted">Loading&hellip;</td>
                {remove_cell}
              </tr>"""

    if card["error"]:
        return f"""
              <tr{row_attrs}>
                <td>{escape(card['symbol'])}</td>
                <td colspan="{_TICKER_DATA_COLUMN_COUNT}" class="muted">Unable to load data.</td>
                {remove_cell}
              </tr>"""

    return f"""
              <tr{row_attrs}>
                <td>{escape(card['symbol'])}</td>
                <td class="num">${card['price']:,.2f}</td>
                {_render_change_cell(card['change'], card['change_percent'])}
                <td class="range-bar-cell">{_render_range_bar(card['symbol'], card['week52_low'], card['week52_high'], card['price'])}</td>
                {_render_pct_off_high_cell(card['pct_off_high'])}
                {_render_market_cap_cell(card['market_cap'])}
                {_render_pe_cell(card['pe_ratio'])}
                {_render_peg_cell(card['peg_ratio'])}
                {remove_cell}
              </tr>"""


def _render_add_ticker_form(group_name: str) -> str:
    """A small inline form under each group's table that posts to
    /api/tickers/add. Only adds within this existing group --
    creating a new group is still a hand-edit of config/tickers.json."""
    return f"""
          <form class="add-ticker-form" data-group="{escape(group_name)}">
            <input type="text" name="symbol" class="add-ticker-input" placeholder="Add ticker&hellip;" maxlength="10" autocomplete="off">
            <button type="submit">Add</button>
          </form>"""


def _render_ticker_groups(grouped_cards: dict) -> str:
    """The group tables only -- shared by the full-page initial render
    and each group's own /api/tickers/groups/<name>/check fragment
    (called with a single-entry `grouped_cards` dict, which this
    function handles the same as the full one since it just loops).
    Group headers are derived from the config keys (see
    `_group_header`), never a fixed list, and a pending/errored ticker
    stands in for any row not yet fetched or whose fetch failed,
    without affecting the other rows.

    Each `.category-block` carries `data-group="<name>"` so the page's
    own script (see render_ticker_dashboard_page) can fetch and patch
    one group's block independently of the others -- a group with
    fewer tickers finishes and repaints before a slower one does,
    rather than the whole page waiting on one combined request.

    The Ticker and % Off High headers carry `class="sortable"` plus a
    `data-sort-key` the page's own client-side script uses to reorder a
    table's rows in place on click -- sorting is purely a DOM reshuffle
    of the rows already rendered here, not a server round trip, and
    each table sorts independently of the others.
    """
    sections = []
    for group_name, cards in grouped_cards.items():
        row_html = "".join(_render_ticker_row(card) for card in cards)
        sections.append(f"""
        <div class="category-block" data-group="{escape(group_name, quote=True)}">
          <p class="category-label">{escape(_group_header(group_name))}</p>
          <table class="indicator-table ticker-table">
            <thead>
              <tr>
                <th class="sortable" data-sort-key="symbol">Ticker</th>
                <th class="num">Price</th>
                <th class="num">Change</th>
                <th>52-Week Range</th>
                <th class="num sortable" data-sort-key="pctOffHigh">% Off High</th>
                <th class="num">Market Cap</th>
                <th class="num">P/E</th>
                <th class="num">PEG</th>
                <th></th>
              </tr>
            </thead>
            <tbody>
              {row_html}
            </tbody>
          </table>
          {_render_add_ticker_form(group_name)}
        </div>""")
    return "".join(sections)


def _render_valuation_group_badge(group_verdict: dict) -> str:
    style = VALUATION_STYLE[group_verdict["verdict"]]
    return (
        f'<div class="valuation-group-badge" style="background:{style["bg"]};border-left:3px solid {style["accent"]};">'
        f'<span class="valuation-group-name">{escape(group_verdict["group"])}</span> '
        f'<span class="directional-badge" style="color:{style["text"]};">{VALUATION_HEADINGS[group_verdict["verdict"]]}</span>'
        f'<p class="valuation-group-reasoning">{escape(group_verdict["reasoning"])}</p>'
        f"</div>"
    )


def _render_valuation_ticker_column(verdict: str, tickers: list[dict]) -> str:
    style = VALUATION_STYLE[verdict]
    if not tickers:
        items = '<p class="muted">None.</p>'
    else:
        items = "<ul>" + "".join(
            f'<li><strong>{escape(t["symbol"])}</strong> &mdash; {escape(t["reasoning"])}</li>'
            for t in tickers
        ) + "</ul>"
    return f"""
          <div class="valuation-column" style="border-top:3px solid {style['accent']};">
            <p class="category-label" style="color:{style['text']};">{VALUATION_HEADINGS[verdict]}</p>
            {items}
          </div>"""


def _render_ticker_valuation(valuation: dict) -> str:
    """The AI valuation section shown once at the top of the Ticker
    Dashboard: an overall paragraph plus a discount/fair/overpriced
    badge per ETF group, then the individual-stock group's tickers
    sorted under three "Discount"/"Fair"/"Overpriced" headings rather
    than one flat list -- see `ticker_valuation.py` for how the AI
    response is grouped and `ticker_dashboard.MIN_VALUATION_INTERVAL`
    for why this doesn't refresh nearly as often as ticker prices do.
    A `pending` valuation (nothing generated yet, or the one Gemini
    call so far has failed with nothing to fall back on -- e.g. a
    quota 429 on a brand-new deployment) shows a muted placeholder
    rather than an error.
    """
    if valuation["pending"]:
        return """
        <section class="card">
          <p class="muted">AI valuation not yet available.</p>
        </section>"""

    by_verdict = valuation["individual_by_verdict"]
    columns = "".join(
        _render_valuation_ticker_column(verdict, by_verdict.get(verdict, []))
        for verdict in ("discount", "fair", "overpriced")
    )
    group_badges = "".join(_render_valuation_group_badge(g) for g in valuation["groups"])

    return f"""
        <section class="card">
          <p class="ai-summary">{escape(valuation['overview'])}</p>
          <div class="valuation-group-badges">{group_badges}</div>
          <div class="valuation-columns">{columns}</div>
          <p class="disclaimer">{escape(VALUATION_DISCLAIMER)}</p>
        </section>"""


def _render_market_news(market_news: dict) -> str:
    """A single page-level feed of general market headlines shown once
    at the top of the Ticker Dashboard -- deliberately distinct from a
    per-ticker news column: one feed, not one list per row, avoids
    cluttering the table.
    """
    if market_news["pending"]:
        return """
        <section class="card">
          <p class="muted">Loading market news&hellip;</p>
        </section>"""

    headlines = market_news["headlines"]
    if not headlines:
        return """
        <section class="card">
          <p class="muted">Market news unavailable.</p>
        </section>"""

    items = []
    for h in headlines:
        source = f' <span class="muted">&middot; {escape(h["source"])}</span>' if h.get("source") else ""
        items.append(
            f'<li><a href="{escape(h["url"])}" target="_blank" rel="noopener">{escape(h["headline"])}</a>{source}</li>'
        )

    return f"""
        <section class="card">
          <p class="category-label">Market News</p>
          <ul class="market-news-list">{''.join(items)}</ul>
        </section>"""


_PENDING_VALUATION = {"overview": None, "groups": [], "individual_by_verdict": {}, "pending": True}


def render_ticker_dashboard_page(grouped_cards: dict, market_news: dict, valuation: dict | None = None) -> str:
    """`grouped_cards` per ticker_dashboard.get_initial_ticker_page_data,
    `market_news` per ticker_dashboard.get_initial_market_news,
    `valuation` per ticker_dashboard.get_initial_ticker_valuation --
    all three built entirely from local caches, so this renders
    instantly, same as the Indicator Digest Page. A ticker with no
    cached snapshot yet renders as a "Loading..." placeholder row;
    market news and the AI valuation each render their own
    "Loading..."/"not yet available" placeholder when uncached. The
    page's own script then fetches each group's own
    /api/tickers/groups/<name>/check, /api/market-news/check, and
    /api/tickers/valuation/check independently in the background -- a
    group with fewer tickers finishes and repaints before a slower one
    does, rather than the whole page waiting on one combined request
    the way it used to. A "Checking for updates..." indicator is shown
    until every one of those requests has settled, one way or another
    -- the valuation check included, even though it usually just
    returns its throttled, already-cached value straight back rather
    than making a real Gemini call (see MIN_VALUATION_INTERVAL).

    `valuation` defaults to a pending placeholder (rather than being
    required) so callers that don't care about this section -- most
    existing tests -- don't need to pass it.
    """
    valuation = valuation if valuation is not None else _PENDING_VALUATION
    return f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <title>Ticker Dashboard</title>
  <link rel="stylesheet" href="/static/dashboard.css">
</head>
<body>
  <main class="page page-wide">
    {_render_nav("/tickers")}
    <header class="page-header">
      <h1>Ticker Dashboard</h1>
      <div class="header-meta">
        <span class="checking-indicator muted" id="checking-indicator">Checking for updates&hellip;</span>
      </div>
    </header>
    <div id="ticker-valuation">{_render_ticker_valuation(valuation)}</div>
    <div id="market-news">{_render_market_news(market_news)}</div>
    <div id="ticker-groups">{_render_ticker_groups(grouped_cards)}</div>
    <footer class="page-footer">
      <p class="muted">Price, change, and 52-week range from Finnhub &middot; free tier may lag by up to ~20 minutes</p>
    </footer>
  </main>
  <script>
    function hideCheckingIndicator() {{
      var el = document.getElementById('checking-indicator');
      if (el) el.remove();
    }}

    // Fetches one group's own live data and swaps its whole block in
    // place -- shared by the initial background check and by the
    // add-ticker handler below, which re-fires this on just the
    // affected group instead of reloading the page.
    function checkGroup(block) {{
      var group = block.dataset.group;
      return fetch('/api/tickers/groups/' + encodeURIComponent(group) + '/check')
        .then(function(r) {{ return r.json(); }})
        .then(function(data) {{
          if (data.group_html) block.outerHTML = data.group_html.trim();
        }});
    }}

    var checks = [];
    document.querySelectorAll('#ticker-groups .category-block[data-group]').forEach(function(block) {{
      checks.push(checkGroup(block).catch(function() {{ /* stay on the stored snapshot already shown */ }}));
    }});
    checks.push(
      fetch('/api/market-news/check').then(function(r) {{ return r.json(); }}).then(function(data) {{
        document.getElementById('market-news').innerHTML = data.news_html;
      }}).catch(function() {{ /* stay on the stored snapshot already shown */ }})
    );
    checks.push(
      fetch('/api/tickers/valuation/check').then(function(r) {{ return r.json(); }}).then(function(data) {{
        document.getElementById('ticker-valuation').innerHTML = data.valuation_html;
      }}).catch(function() {{ /* stay on the stored valuation already shown */ }})
    );
    Promise.allSettled(checks).then(hideCheckingIndicator);

    var tickerGroups = document.getElementById('ticker-groups');
    tickerGroups.addEventListener('click', function(e) {{
      var th = e.target.closest('th[data-sort-key]');
      if (th) {{
        var table = th.closest('table');
        var newDir = th.classList.contains('sort-asc') ? 'desc' : 'asc';
        table.querySelectorAll('th[data-sort-key]').forEach(function(other) {{
          other.classList.remove('sort-asc', 'sort-desc');
        }});
        th.classList.add('sort-' + newDir);
        var mult = newDir === 'asc' ? 1 : -1;
        var key = th.dataset.sortKey;
        var tbody = table.querySelector('tbody');
        var rows = Array.prototype.slice.call(tbody.querySelectorAll('tr'));
        rows.sort(function(a, b) {{
          if (key === 'symbol') {{
            return mult * a.dataset.symbol.localeCompare(b.dataset.symbol);
          }}
          var av = a.dataset.pctOffHigh === '' ? null : parseFloat(a.dataset.pctOffHigh);
          var bv = b.dataset.pctOffHigh === '' ? null : parseFloat(b.dataset.pctOffHigh);
          if (av === null && bv === null) return 0;
          if (av === null) return 1;
          if (bv === null) return -1;
          return mult * (av - bv);
        }});
        rows.forEach(function(r) {{ tbody.appendChild(r); }});
        return;
      }}

      var btn = e.target.closest('.remove-ticker');
      if (!btn) return;
      var group = btn.dataset.group, symbol = btn.dataset.symbol;
      if (!confirm('Remove ' + symbol + ' from ' + group + '?')) return;

      var row = btn.closest('tr');
      var parent = row.parentNode;
      var nextRow = row.nextSibling;
      row.remove();

      fetch('/api/tickers/remove', {{
        method: 'POST',
        headers: {{'Content-Type': 'application/json'}},
        body: JSON.stringify({{group: group, symbol: symbol}})
      }}).then(function(r) {{ return r.json(); }}).then(function(data) {{
        if (data.error) {{
          alert(data.error);
          parent.insertBefore(row, nextRow);
        }}
      }}).catch(function() {{
        alert('Failed to remove ' + symbol + '.');
        parent.insertBefore(row, nextRow);
      }});
    }});
    tickerGroups.addEventListener('submit', function(e) {{
      var form = e.target.closest('.add-ticker-form');
      if (!form) return;
      e.preventDefault();
      var group = form.dataset.group, symbol = form.symbol.value.trim().toUpperCase();
      if (!symbol) return;
      fetch('/api/tickers/add', {{
        method: 'POST',
        headers: {{'Content-Type': 'application/json'}},
        body: JSON.stringify({{group: group, symbol: symbol}})
      }}).then(function(r) {{ return r.json(); }}).then(function(data) {{
        if (data.error) {{ alert(data.error); return; }}
        form.reset();

        var block = document.querySelector('#ticker-groups .category-block[data-group="' + group + '"]');
        if (!block) return;
        var tbody = block.querySelector('tbody');
        var alreadyShown = tbody.querySelector('tr[data-symbol="' + symbol + '"]');
        if (!alreadyShown) {{
          var row = document.createElement('tr');
          row.dataset.symbol = symbol;
          row.dataset.pctOffHigh = '';

          var symbolCell = document.createElement('td');
          symbolCell.textContent = symbol;
          var loadingCell = document.createElement('td');
          loadingCell.colSpan = {_TICKER_DATA_COLUMN_COUNT};
          loadingCell.className = 'muted';
          loadingCell.textContent = 'Loading…';
          var removeCell = document.createElement('td');
          var removeBtn = document.createElement('button');
          removeBtn.type = 'button';
          removeBtn.className = 'remove-ticker';
          removeBtn.dataset.group = group;
          removeBtn.dataset.symbol = symbol;
          removeBtn.title = 'Remove ' + symbol + ' from ' + group;
          removeBtn.setAttribute('aria-label', 'Remove ' + symbol);
          removeBtn.textContent = '×';
          removeCell.appendChild(removeBtn);

          row.appendChild(symbolCell);
          row.appendChild(loadingCell);
          row.appendChild(removeCell);
          tbody.appendChild(row);
        }}

        // Re-check just this group so the new ticker (and everything
        // else in it) gets real data -- no full page reload needed.
        checkGroup(block).catch(function() {{ /* leave the pending row as-is */ }});
      }}).catch(function() {{ alert('Failed to add ' + symbol + '.'); }});
    }});
  </script>
</body>
</html>"""


def render_ticker_group_check_response(group_name: str, cards: list[dict]) -> dict:
    """HTML fragment for GET /api/tickers/groups/<group_name>/check,
    called once that group's own check_for_ticker_updates call finishes
    (it always re-fetches -- there's no "nothing changed" gate for
    tickers the way there is for the AI-backed indicator digest). Only
    this one group's block is returned, so the page's script can patch
    it without touching any other group's table."""
    return {"group_html": _render_ticker_groups({group_name: cards})}


def render_market_news_check_response(market_news: dict) -> dict:
    """HTML fragment for GET /api/market-news/check, independent of any
    ticker group's own check."""
    return {"news_html": _render_market_news(market_news)}


def render_ticker_valuation_check_response(valuation: dict) -> dict:
    """HTML fragment for GET /api/tickers/valuation/check, independent
    of any ticker group's or market news' own check."""
    return {"valuation_html": _render_ticker_valuation(valuation)}


def render_check_response(content: dict) -> dict:
    """HTML fragments for /api/check once check_for_updates finds at
    least one indicator with a genuinely new value. `content` matches
    build_digest_content's return shape.

    `ai_html` is only non-None when the AI call also succeeded this
    check — table/countdown can update live while the AI section is
    left untouched (still showing its last Saved read), same
    independent-freshness behavior as the initial page render.
    """
    ai_result = content["ai_result"]
    ai_html = _render_ai_section(ai_result) if ai_result is not None else None
    return {
        "table_html": _render_table_section(content["table"]),
        "countdown_html": _render_countdown_section(content["countdown"]),
        "ai_html": ai_html,
    }
