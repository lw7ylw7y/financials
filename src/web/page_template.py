"""Indicator Digest Page HTML rendering (Story 1/1a).

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
