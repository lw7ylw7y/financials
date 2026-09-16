"""Local Flask app for the v2 web dashboard: the Indicator Digest Page
("/") and the Ticker Dashboard ("/tickers", plus its inline watchlist
editor, "/api/tickers/add" and "/api/tickers/remove"). Bound to
loopback only (127.0.0.1), never 0.0.0.0, so it is unreachable from
anything but the machine it's running on, per the local-only hosting
decision in Section 4.1 of investment_dashboard_requirements.md.

`_require_auth` gates every route behind HTTP Basic Auth when both
`DASHBOARD_USERNAME` and `DASHBOARD_PASSWORD` are set (the hosted
deployment) -- it's a no-op when either is unset, which is local
development's default.
"""

import os
import secrets
import sys

_WEB_DIR = os.path.dirname(os.path.abspath(__file__))
_SRC_DIR = os.path.dirname(_WEB_DIR)
for _subdir in ("fred", "storage", "digest", "mailer"):
    sys.path.insert(0, os.path.join(_SRC_DIR, _subdir))
sys.path.insert(0, _SRC_DIR)
sys.path.insert(0, _WEB_DIR)

from flask import Flask, Response, jsonify, request

from live_pull import check_for_updates, get_initial_page_data
from page_template import (
    render_check_response,
    render_indicator_digest_page,
    render_ticker_check_response,
    render_ticker_dashboard_page,
)
from ticker_dashboard import (
    TickerConfigError,
    add_ticker_to_group,
    check_for_market_news,
    check_for_ticker_updates,
    get_initial_market_news,
    get_initial_ticker_page_data,
    remove_ticker_from_group,
)

app = Flask(__name__)


@app.before_request
def _require_auth():
    """HTTP Basic Auth in front of every route. Both `DASHBOARD_USERNAME`
    and `DASHBOARD_PASSWORD` must be set to turn this on -- e.g. the
    hosted deployment's env vars -- otherwise it's a no-op, which is
    local development's default. `secrets.compare_digest` avoids
    leaking credential length/prefix through timing.
    """
    username = os.environ.get("DASHBOARD_USERNAME")
    password = os.environ.get("DASHBOARD_PASSWORD")
    if not username or not password:
        return None

    auth = request.authorization
    if (
        auth
        and secrets.compare_digest(auth.username or "", username)
        and secrets.compare_digest(auth.password or "", password)
    ):
        return None

    return Response(
        "Authentication required.",
        401,
        {"WWW-Authenticate": 'Basic realm="Investment Dashboard"'},
    )


@app.route("/")
def indicator_digest_page():
    data = get_initial_page_data()
    return render_indicator_digest_page(data)


@app.route("/tickers")
def ticker_dashboard_page():
    grouped_cards = get_initial_ticker_page_data()
    market_news = get_initial_market_news()
    return render_ticker_dashboard_page(grouped_cards, market_news)


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
    fast initial render. See ticker_dashboard.check_for_ticker_updates
    and check_for_market_news -- the market-news feed rides along in
    the same round trip rather than getting its own route."""
    grouped_cards = check_for_ticker_updates()
    market_news = check_for_market_news()
    return jsonify(render_ticker_check_response(grouped_cards, market_news))


@app.route("/api/tickers/add", methods=["POST"])
def api_add_ticker():
    """Called by the /tickers page's inline "add a ticker" form. Writes
    straight to config/tickers.json; the browser reloads the page on
    success so the new (pending) ticker and everything else stay in
    sync through the same stored-render + background-check path as any
    other page load -- no separate client-side patching for this."""
    body = request.get_json(silent=True) or {}
    try:
        add_ticker_to_group(body.get("symbol", ""), body.get("group", ""))
    except TickerConfigError as e:
        return jsonify({"error": str(e)}), 400
    return jsonify({"ok": True})


@app.route("/api/tickers/remove", methods=["POST"])
def api_remove_ticker():
    """Called by the /tickers page's inline "remove" button on each
    row. See api_add_ticker."""
    body = request.get_json(silent=True) or {}
    try:
        remove_ticker_from_group(body.get("symbol", ""), body.get("group", ""))
    except TickerConfigError as e:
        return jsonify({"error": str(e)}), 400
    return jsonify({"ok": True})


if __name__ == "__main__":
    app.run(host="127.0.0.1", port=5000, debug=False)
