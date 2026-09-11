"""Per-indicator trend sparklines for the digest email (Story 5 polish).

Rendered as small PNG images rather than inline SVG — most email
clients (Gmail included) strip <svg> from HTML email entirely, but a
raster image embedded via a Content-ID reference (see send_email.py)
renders reliably everywhere.
"""

import io

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt

# Displayed at roughly 90x24 in the email; rendered at 3x for crispness
# on retina/high-DPI displays.
DISPLAY_WIDTH_PX = 90
DISPLAY_HEIGHT_PX = 24
SCALE = 3
DPI = 100

LINE_COLOR = "#2563eb"
FILL_COLOR = "#2563eb"
FILL_ALPHA = 0.12
UP_COLOR = "#15803d"
DOWN_COLOR = "#b91c1c"
FLAT_COLOR = "#64748b"


def render_sparkline(history_window: list[dict]) -> bytes:
    """Render a minimal trend line (no axes/labels/ticks) as PNG bytes.

    `history_window` is a chronologically ordered list of {"date",
    "value"} entries. The endpoint dot is colored green/red/gray based
    on the last vs. second-to-last value; a single-point history renders
    as just that dot.
    """
    values = [entry["value"] for entry in history_window]
    x = list(range(len(values)))

    width_in = DISPLAY_WIDTH_PX * SCALE / DPI
    height_in = DISPLAY_HEIGHT_PX * SCALE / DPI
    fig = plt.figure(figsize=(width_in, height_in), dpi=DPI)
    ax = fig.add_axes((0.0, 0.0, 1.0, 1.0))
    ax.axis("off")

    if len(values) >= 2:
        ax.plot(x, values, color=LINE_COLOR, linewidth=1.8, solid_capstyle="round")
        ax.fill_between(x, values, min(values), color=FILL_COLOR, alpha=FILL_ALPHA, linewidth=0)
        if values[-1] > values[-2]:
            endpoint_color = UP_COLOR
        elif values[-1] < values[-2]:
            endpoint_color = DOWN_COLOR
        else:
            endpoint_color = FLAT_COLOR
    else:
        endpoint_color = FLAT_COLOR

    ax.scatter([x[-1]], [values[-1]], color=endpoint_color, s=14, zorder=3, edgecolors="none")

    value_range = max(values) - min(values)
    pad = value_range * 0.2 if value_range else 1
    ax.set_ylim(min(values) - pad, max(values) + pad)
    ax.set_xlim(-0.5, x[-1] + 0.5)

    buf = io.BytesIO()
    fig.savefig(buf, format="png", transparent=True)
    plt.close(fig)
    return buf.getvalue()
