"""Digest email rendering — plain-text and HTML bodies.

Kept separate from post_release.py's orchestration/throttling logic:
this module only turns already-computed data (AI result, table,
countdown) into email content. HTML uses inline styles and a
table-based layout throughout — the safe subset that renders
consistently across email clients (including older Outlook), which
don't reliably support <style> blocks, flexbox, or grid.
"""

from html import escape

DISCLAIMER = (
    "This is automated commentary based on indicator trends, "
    "not personalized financial advice."
)
CATEGORY_ORDER = ["leading", "coincident", "lagging"]
CATEGORY_LABELS = {"leading": "Leading", "coincident": "Coincident", "lagging": "Lagging"}

DIRECTIONAL_STYLE = {
    "bullish": {"text": "#15803d", "bg": "#dcfce7", "accent": "#22c55e", "label": "Bullish"},
    "bearish": {"text": "#b91c1c", "bg": "#fee2e2", "accent": "#ef4444", "label": "Bearish"},
    "neutral": {"text": "#475569", "bg": "#e2e8f0", "accent": "#94a3b8", "label": "Neutral"},
}

FONT_STACK = (
    "-apple-system,BlinkMacSystemFont,'Segoe UI',Roboto,Helvetica,Arial,sans-serif"
)


def render_subject(updated_names: list[str]) -> str:
    return f"[Indicator Digest] {len(updated_names)} update(s): {', '.join(updated_names)}"


def render_text(table: dict, countdown: dict, ai_result: dict | None) -> str:
    """Plain-text body — the multipart/alternative fallback."""
    lines = []
    if ai_result is not None:
        lines += [
            ai_result["summary"],
            f"Overall directional read: {ai_result['directional_read']}",
            "",
            DISCLAIMER,
            "",
        ]

    for category in CATEGORY_ORDER:
        rows = table.get(category, [])
        if not rows:
            continue
        lines.append(f"{CATEGORY_LABELS[category]}:")
        for row in rows:
            prior = f"{row['prior_value']:g}" if row["prior_value"] is not None else "n/a"
            lines.append(
                f"  {row['name']}: {row['latest_value']:g} as of "
                f"{row['latest_date']} (prior: {prior})"
            )
        lines.append("")

    if countdown["entries"]:
        lines.append("Next releases:")
        soonest = countdown["soonest"]
        lines.append(
            f"  Next up: {soonest['name']} in {soonest['days_until']} day(s) "
            f"({soonest['next_release_date']})"
        )
        for entry in countdown["entries"]:
            if entry["key"] == soonest["key"]:
                continue
            lines.append(
                f"  {entry['name']}: in {entry['days_until']} day(s) "
                f"({entry['next_release_date']})"
            )

    return "\n".join(lines).rstrip() + "\n"


def _sparkline_img(cid: str | None) -> str:
    if not cid:
        return '<span style="color:#94a3b8;">&mdash;</span>'
    return (
        f'<img src="cid:{cid}" width="90" height="24" alt="trend" '
        f'style="display:block;border:0;">'
    )


def _render_ai_section(ai_result: dict | None) -> str:
    if ai_result is None:
        return ""

    style = DIRECTIONAL_STYLE[ai_result["directional_read"]]
    summary = escape(ai_result["summary"])
    return f"""
    <tr>
      <td style="padding:0 24px 20px 24px;">
        <table role="presentation" width="100%" cellpadding="0" cellspacing="0"
               style="background:{style['bg']};border-left:4px solid {style['accent']};
                      border-radius:6px;">
          <tr>
            <td style="padding:18px 20px;">
              <p style="margin:0 0 12px 0;font-size:15px;line-height:1.6;color:#1e293b;">
                {summary}
              </p>
              <span style="display:inline-block;padding:3px 10px;border-radius:999px;
                            background:#ffffff;color:{style['text']};font-size:12px;
                            font-weight:700;letter-spacing:.04em;text-transform:uppercase;">
                {style['label']}
              </span>
              <p style="margin:12px 0 0 0;font-size:12px;line-height:1.5;color:#64748b;
                        font-style:italic;">
                {escape(DISCLAIMER)}
              </p>
            </td>
          </tr>
        </table>
      </td>
    </tr>"""


def _render_table_section(table: dict) -> str:
    sections = []
    for category in CATEGORY_ORDER:
        rows = table.get(category, [])
        if not rows:
            continue

        row_html = []
        for i, row in enumerate(rows):
            bg = "#ffffff" if i % 2 == 0 else "#f8fafc"
            prior = f"{row['prior_value']:g}" if row["prior_value"] is not None else "n/a"
            row_html.append(f"""
            <tr style="background:{bg};">
              <td style="padding:10px 12px;font-size:14px;color:#1e293b;border-bottom:1px solid #e2e8f0;">
                {escape(row['name'])}
              </td>
              <td style="padding:10px 12px;font-size:14px;color:#1e293b;font-weight:600;
                        border-bottom:1px solid #e2e8f0;text-align:right;">
                {row['latest_value']:g}
              </td>
              <td style="padding:10px 12px;font-size:13px;color:#64748b;border-bottom:1px solid #e2e8f0;
                        text-align:right;">
                {escape(row['latest_date'])}
              </td>
              <td style="padding:10px 12px;font-size:13px;color:#94a3b8;border-bottom:1px solid #e2e8f0;
                        text-align:right;">
                prior: {prior}
              </td>
              <td style="padding:10px 12px;border-bottom:1px solid #e2e8f0;text-align:right;">
                {_sparkline_img(row.get('sparkline_cid'))}
              </td>
            </tr>""")

        sections.append(f"""
    <tr>
      <td style="padding:0 24px 20px 24px;">
        <p style="margin:0 0 8px 0;font-size:13px;font-weight:700;letter-spacing:.04em;
                  text-transform:uppercase;color:#334155;">
          {CATEGORY_LABELS[category]}
        </p>
        <table role="presentation" width="100%" cellpadding="0" cellspacing="0"
               style="border:1px solid #e2e8f0;border-radius:6px;overflow:hidden;">
          {''.join(row_html)}
        </table>
      </td>
    </tr>""")
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
          <td style="padding:6px 0;font-size:13px;color:#475569;">{escape(entry['name'])}</td>
          <td style="padding:6px 0;font-size:13px;color:#94a3b8;text-align:right;">
            in {entry['days_until']} day(s) &middot; {escape(entry['next_release_date'])}
          </td>
        </tr>""")

    return f"""
    <tr>
      <td style="padding:0 24px 24px 24px;">
        <p style="margin:0 0 8px 0;font-size:13px;font-weight:700;letter-spacing:.04em;
                  text-transform:uppercase;color:#334155;">
          Next Releases
        </p>
        <table role="presentation" width="100%" cellpadding="0" cellspacing="0"
               style="background:#eff6ff;border-radius:6px;">
          <tr>
            <td style="padding:14px 16px;">
              <span style="display:inline-block;padding:2px 8px;border-radius:999px;
                          background:#2563eb;color:#ffffff;font-size:11px;font-weight:700;
                          letter-spacing:.04em;text-transform:uppercase;margin-right:8px;">
                Next up
              </span>
              <span style="font-size:14px;color:#1e293b;font-weight:600;">
                {escape(soonest['name'])}
              </span>
              <span style="font-size:13px;color:#475569;">
                &mdash; in {soonest['days_until']} day(s) ({escape(soonest['next_release_date'])})
              </span>
            </td>
          </tr>
          {f'''<tr><td style="padding:0 16px 14px 16px;">
            <table role="presentation" width="100%" cellpadding="0" cellspacing="0">
              {''.join(other_rows)}
            </table>
          </td></tr>''' if other_rows else ''}
        </table>
      </td>
    </tr>"""


def render_html(table: dict, countdown: dict, ai_result: dict | None) -> str:
    return f"""<!doctype html>
<html>
  <body style="margin:0;padding:0;background:#f1f5f9;font-family:{FONT_STACK};">
    <table role="presentation" width="100%" cellpadding="0" cellspacing="0" style="background:#f1f5f9;">
      <tr>
        <td align="center" style="padding:24px 12px;">
          <table role="presentation" width="600" cellpadding="0" cellspacing="0"
                 style="width:100%;max-width:600px;background:#ffffff;border-radius:8px;
                        overflow:hidden;border:1px solid #e2e8f0;">
            <tr>
              <td style="padding:24px 24px 4px 24px;">
                <p style="margin:0;font-size:12px;font-weight:700;letter-spacing:.08em;
                          text-transform:uppercase;color:#2563eb;">
                  Indicator Digest
                </p>
              </td>
            </tr>
            {_render_ai_section(ai_result)}
            {_render_table_section(table)}
            {_render_countdown_section(countdown)}
            <tr>
              <td style="padding:16px 24px;border-top:1px solid #e2e8f0;">
                <p style="margin:0;font-size:11px;color:#94a3b8;">
                  Automated macro indicator digest &middot; data from FRED
                </p>
              </td>
            </tr>
          </table>
        </td>
      </tr>
    </table>
  </body>
</html>"""
