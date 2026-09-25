"""Local Flask app for the v2 web dashboard: the Indicator Digest Page
("/") and the Ticker Dashboard ("/tickers", plus its inline watchlist
editor, "/api/tickers/add" and "/api/tickers/remove"). The ticker
page's background live check hits one route per group
("/api/tickers/groups/<name>/check") plus one for market news
("/api/market-news/check") and one for the AI valuation section
("/api/tickers/valuation/check") rather than a single combined route,
so a group with fewer tickers repaints before a slower one finishes. Bound
to loopback only (127.0.0.1), never 0.0.0.0, so it is unreachable from
anything but the machine it's running on, per the local-only hosting
decision in Section 4.1 of investment_dashboard_requirements.md.

`_require_auth` gates every route behind Google sign-in when
`GOOGLE_CLIENT_ID` is set (the hosted deployment) -- it's a no-op when
unset, which is local development's default.
"""

import os
import secrets
import sys
from datetime import timedelta

_WEB_DIR = os.path.dirname(os.path.abspath(__file__))
_SRC_DIR = os.path.dirname(_WEB_DIR)
for _subdir in ("fred", "storage", "digest", "mailer"):
    sys.path.insert(0, os.path.join(_SRC_DIR, _subdir))
sys.path.insert(0, _SRC_DIR)
sys.path.insert(0, _WEB_DIR)

from flask import Flask, Response, jsonify, redirect, request, session, url_for
from werkzeug.middleware.proxy_fix import ProxyFix

import google_auth

from live_pull import check_for_updates, get_initial_page_data
from page_template import (
    render_check_response,
    render_indicator_digest_page,
    render_market_news_check_response,
    render_ticker_dashboard_page,
    render_ticker_group_check_response,
    render_ticker_valuation_check_response,
)
from ticker_dashboard import (
    TickerConfigError,
    add_ticker_to_group,
    check_for_market_news,
    check_for_ticker_updates,
    check_for_ticker_valuation,
    get_initial_market_news,
    get_initial_ticker_page_data,
    get_initial_ticker_valuation,
    load_ticker_config,
    remove_ticker_from_group,
)

app = Flask(__name__)
# Render terminates TLS in front of the app; without this, the redirect URI
# built for Google would be http:// and never match the registered one.
app.wsgi_app = ProxyFix(app.wsgi_app, x_proto=1, x_host=1)
app.config.update(
    SECRET_KEY=os.environ.get("SECRET_KEY") or secrets.token_hex(32),
    SESSION_COOKIE_HTTPONLY=True,
    SESSION_COOKIE_SAMESITE="Lax",
    SESSION_COOKIE_SECURE=google_auth.is_enabled(),
    PERMANENT_SESSION_LIFETIME=timedelta(days=30),
)

_AUTH_ENDPOINTS = {"login", "auth_callback", "logout"}


def _page(message: str, status: int) -> Response:
    return Response(message, status, {"Content-Type": "text/plain; charset=utf-8"})


@app.before_request
def _require_auth():
    """Google sign-in in front of every route. Turned on by setting
    `GOOGLE_CLIENT_ID` (the hosted deployment); otherwise a no-op, which
    is local development's default. Once on, a missing companion setting
    fails closed with a 503 instead of leaving the dashboard open. Only
    the session's own signed email counts, and it must match
    `ALLOWED_EMAIL`; an unauthenticated `/api/*` call gets a 401 rather
    than a redirect its fetch() couldn't follow usefully.
    """
    if not google_auth.is_enabled():
        return None

    missing = google_auth.missing_config()
    if missing:
        return _page(f"Sign-in is misconfigured; missing: {', '.join(missing)}", 503)

    if request.endpoint in _AUTH_ENDPOINTS:
        return None

    email = session.get("email")
    if email and secrets.compare_digest(email, google_auth.allowed_email()):
        return None

    if request.path.startswith("/api/"):
        return jsonify({"error": "authentication required"}), 401
    return redirect(url_for("login"))


@app.route("/login")
def login():
    if not google_auth.is_enabled():
        return redirect(url_for("indicator_digest_page"))
    state = secrets.token_urlsafe(32)
    session["oauth_state"] = state
    redirect_uri = url_for("auth_callback", _external=True)
    return redirect(google_auth.build_authorize_url(redirect_uri, state))


@app.route("/auth/callback")
def auth_callback():
    expected_state = session.pop("oauth_state", None)
    state = request.args.get("state", "")
    code = request.args.get("code")
    if not expected_state or not secrets.compare_digest(state, expected_state) or not code:
        return _page("Sign-in failed: invalid or expired request. Go to /login to try again.", 400)

    try:
        email = google_auth.fetch_verified_email(code, url_for("auth_callback", _external=True))
    except google_auth.GoogleAuthError:
        return _page("Sign-in failed: could not verify your Google account. Go to /login to try again.", 502)

    if not email or not secrets.compare_digest(email, google_auth.allowed_email()):
        session.clear()
        return _page("This Google account is not allowed to view this dashboard.", 403)

    session.clear()
    session["email"] = email
    session.permanent = True
    return redirect(url_for("indicator_digest_page"))


@app.route("/logout")
def logout():
    session.clear()
    return _page("Signed out.", 200)


@app.route("/")
def indicator_digest_page():
    data = get_initial_page_data()
    return render_indicator_digest_page(data)


@app.route("/tickers")
def ticker_dashboard_page():
    grouped_cards = get_initial_ticker_page_data()
    market_news = get_initial_market_news()
    valuation = get_initial_ticker_valuation()
    return render_ticker_dashboard_page(grouped_cards, market_news, valuation)


@app.route("/api/check")
def api_check():
    """Called by the page's own background script after the fast
    initial render. See live_pull.check_for_updates."""
    result = check_for_updates()
    if not result["data_updated"]:
        return jsonify({"data_updated": False})
    fragments = render_check_response(result["content"])
    return jsonify({"data_updated": True, **fragments})


@app.route("/api/tickers/groups/<group_name>/check")
def api_check_ticker_group(group_name):
    """Called independently by each group's own block in the ticker
    page's background script, one small live fetch per group instead
    of one big one for the whole watchlist -- so a group with fewer
    tickers finishes and repaints before a slower one does. See
    ticker_dashboard.check_for_ticker_updates."""
    config = load_ticker_config()
    if group_name not in config:
        return jsonify({"error": f"unknown group: {group_name!r}"}), 404
    grouped_cards = check_for_ticker_updates(config={group_name: config[group_name]})
    return jsonify(render_ticker_group_check_response(group_name, grouped_cards[group_name]))


@app.route("/api/market-news/check")
def api_check_market_news():
    """Called independently of any ticker group's own check -- see
    api_check_ticker_group."""
    market_news = check_for_market_news()
    return jsonify(render_market_news_check_response(market_news))


@app.route("/api/tickers/valuation/check")
def api_check_ticker_valuation():
    """Called independently of any ticker group's or market news' own
    check. Usually returns the already-cached valuation straight back
    without a real Gemini call -- see
    ticker_dashboard.MIN_VALUATION_INTERVAL."""
    valuation = check_for_ticker_valuation()
    return jsonify(render_ticker_valuation_check_response(valuation))


@app.route("/api/tickers/add", methods=["POST"])
def api_add_ticker():
    """Called by the /tickers page's inline "add a ticker" form. Writes
    straight to config/tickers.json; on success the page inserts a
    pending row for the new ticker and re-checks just that one group
    (see render_ticker_dashboard_page's script) rather than reloading
    the whole page."""
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
    # threaded=True so the ticker page's concurrent per-group check
    # requests actually run concurrently in local dev too, instead of
    # queueing on Werkzeug's single-threaded default -- matching how
    # gunicorn already serves concurrent requests on a hosted deploy.
    app.run(host="127.0.0.1", port=5000, debug=False, threaded=True)
