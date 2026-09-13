"""Local Flask app for the v1.1 web dashboard: the Indicator Digest Page
(Story 1/1a, "/") and the Ticker Dashboard (Story 2/3, "/tickers").
Bound to loopback only (127.0.0.1), never 0.0.0.0, so it is unreachable
from anything but the machine it's running on, per the local-only
hosting decision in Section 4.1 of investment_dashboard_requirements.md.
No authentication layer: unnecessary when the app can never be reached
from outside the machine itself.
"""

import os
import sys

_WEB_DIR = os.path.dirname(os.path.abspath(__file__))
_SRC_DIR = os.path.dirname(_WEB_DIR)
for _subdir in ("fred", "storage", "digest", "mailer"):
    sys.path.insert(0, os.path.join(_SRC_DIR, _subdir))
sys.path.insert(0, _SRC_DIR)
sys.path.insert(0, _WEB_DIR)

from flask import Flask, jsonify

from live_pull import check_for_updates, get_initial_page_data
from page_template import (
    render_check_response,
    render_indicator_digest_page,
    render_ticker_check_response,
    render_ticker_dashboard_page,
)
from ticker_dashboard import check_for_ticker_updates, get_initial_ticker_page_data

app = Flask(__name__)


@app.route("/")
def indicator_digest_page():
    data = get_initial_page_data()
    return render_indicator_digest_page(data)


@app.route("/tickers")
def ticker_dashboard_page():
    grouped_cards = get_initial_ticker_page_data()
    return render_ticker_dashboard_page(grouped_cards)


@app.route("/api/check")
def api_check():
    """Called by the page's own background script after the fast
    initial render. See live_pull.check_for_updates."""
    result = check_for_updates()
    if not result["data_updated"]:
        return jsonify({"data_updated": False})
    fragments = render_check_response(result["content"])
    return jsonify({"data_updated": True, **fragments})


@app.route("/api/check-tickers")
def api_check_tickers():
    """Called by the ticker page's own background script after the
    fast initial render. See ticker_dashboard.check_for_ticker_updates."""
    grouped_cards = check_for_ticker_updates()
    return jsonify(render_ticker_check_response(grouped_cards))


if __name__ == "__main__":
    app.run(host="127.0.0.1", port=5000, debug=False)
