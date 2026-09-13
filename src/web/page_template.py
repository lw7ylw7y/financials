"""HTML rendering for both v1.1 pages: the Indicator Digest Page
(Story 1/1a) and the Ticker Dashboard (Story 2/3).

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
RANGE_BAR_WIDTH = 100
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
    """Shared nav so either v1.1 page links to the other -- clicking
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
    group in config/tickers.json appears correctly with no code change
    (Story 2/3's AC, Section 5.2 of the tech design)."""
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


def _render_ma_cell(price: float, ma: float | None) -> str:
    """A moving-average value plus how far the current price sits above
    or below it, as both a color (green above / red below, matching the
    directional badges elsewhere) and a same-information arrow + signed
    percentage -- so the read doesn't depend on color perception alone.
    "n/a" when there isn't enough history yet (Story 3's documented
    fewer-than-window behavior).
    """
    if ma is None:
        return '<td class="num muted">n/a</td>'

    pct_diff = (price - ma) / ma * 100
    if pct_diff > 0:
        css_class, arrow, color = "up", "&#9650;", SPARKLINE_UP_COLOR
    elif pct_diff < 0:
        css_class, arrow, color = "down", "&#9660;", SPARKLINE_DOWN_COLOR
    else:
        css_class, arrow, color = "flat", "", SPARKLINE_FLAT_COLOR

    return (
        f'<td class="num">{ma:,.2f} '
        f'<span class="ma-delta {css_class}" style="color:{color};">{arrow}{abs(pct_diff):.1f}%</span></td>'
    )


def _render_ticker_row(card: dict) -> str:
    if card["pending"]:
        return f"""
              <tr>
                <td>{escape(card['symbol'])}</td>
                <td colspan="5" class="muted">Loading&hellip;</td>
              </tr>"""

    if card["error"]:
        return f"""
              <tr>
                <td>{escape(card['symbol'])}</td>
                <td colspan="5" class="muted">Unable to load data.</td>
              </tr>"""

    return f"""
              <tr>
                <td>{escape(card['symbol'])}</td>
                <td class="num">${card['price']:,.2f}</td>
                <td class="range-bar-cell">{_render_range_bar(card['symbol'], card['week52_low'], card['week52_high'], card['price'])}</td>
                {_render_ma_cell(card['price'], card['ma20'])}
                {_render_ma_cell(card['price'], card['ma50'])}
                {_render_ma_cell(card['price'], card['ma200'])}
              </tr>"""


def _render_ticker_groups(grouped_cards: dict) -> str:
    """The group tables only -- shared by the full-page initial render
    and the /api/check-tickers fragment, both of which the page's
    #ticker-groups div swaps in. Group headers are derived from the
    config keys (see `_group_header`), never a fixed list, and a
    pending/errored ticker stands in for any row not yet fetched or
    whose fetch failed, without affecting the other rows.
    """
    sections = []
    for group_name, cards in grouped_cards.items():
        row_html = "".join(_render_ticker_row(card) for card in cards)
        sections.append(f"""
        <div class="category-block">
          <p class="category-label">{escape(_group_header(group_name))}</p>
          <table class="indicator-table ticker-table">
            <thead>
              <tr>
                <th>Ticker</th>
                <th class="num">Price</th>
                <th>52-Week Range</th>
                <th class="num">20d MA</th>
                <th class="num">50d MA</th>
                <th class="num">200d MA</th>
              </tr>
            </thead>
            <tbody>
              {row_html}
            </tbody>
          </table>
        </div>""")
    return "".join(sections)


def render_ticker_dashboard_page(grouped_cards: dict) -> str:
    """`grouped_cards` per ticker_dashboard.get_initial_ticker_page_data:
    `{group_name: [card, ...]}` in file order, built entirely from the
    local snapshot cache -- so this renders instantly, same as the
    Indicator Digest Page. A ticker with no cached snapshot yet renders
    as a "Loading..." placeholder row. The page's own script then calls
    /api/check-tickers in the background to fetch live and patch
    #ticker-groups in place; a "Checking for updates..." indicator is
    shown for the duration and removed once it settles either way.
    """
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
    <div id="ticker-groups">{_render_ticker_groups(grouped_cards)}</div>
    <footer class="page-footer">
      <p class="muted">Price and 52-week range from Finnhub &middot; moving averages from Yahoo Finance &middot; free tier may lag by up to ~20 minutes</p>
    </footer>
  </main>
  <script>
    function hideCheckingIndicator() {{
      var el = document.getElementById('checking-indicator');
      if (el) el.remove();
    }}
    fetch('/api/check-tickers').then(function(r) {{ return r.json(); }}).then(function(data) {{
      hideCheckingIndicator();
      document.getElementById('ticker-groups').innerHTML = data.groups_html;
    }}).catch(function() {{ hideCheckingIndicator(); /* stay on the stored snapshot already shown */ }});
  </script>
</body>
</html>"""


def render_ticker_check_response(grouped_cards: dict) -> dict:
    """HTML fragment for /api/check-tickers, called once
    check_for_ticker_updates finishes its live pull (which always
    re-fetches -- there's no "nothing changed" gate for tickers the way
    there is for the AI-backed indicator digest)."""
    return {"groups_html": _render_ticker_groups(grouped_cards)}


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
