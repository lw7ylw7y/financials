import os
import sys
import unittest
from unittest import mock

_SRC = os.path.join(os.path.dirname(__file__), "..", "src")
for _p in (
    _SRC,
    os.path.join(_SRC, "fred"),
    os.path.join(_SRC, "storage"),
    os.path.join(_SRC, "digest"),
    os.path.join(_SRC, "mailer"),
    os.path.join(_SRC, "web"),
):
    sys.path.insert(0, _p)

import app as app_module
import google_auth

NO_AUTH_ENV = {"GOOGLE_CLIENT_ID": ""}
AUTH_ENV = {
    "GOOGLE_CLIENT_ID": "client-id",
    "GOOGLE_CLIENT_SECRET": "client-secret",
    "ALLOWED_EMAIL": "Me@Example.com",
    "SECRET_KEY": "test-secret-key",
}


class TestDashboardAuth(unittest.TestCase):
    """Google sign-in gate in front of every route, on only when
    GOOGLE_CLIENT_ID is set. Data/network calls are mocked out -- this
    is testing the auth gate, not page content.
    """

    def setUp(self):
        self.client = app_module.app.test_client()
        for target, value in (
            ("app.get_initial_page_data", {"table": {}, "countdown": {"entries": []}, "ai_result": None}),
            ("app.get_initial_ticker_page_data", {}),
            ("app.get_initial_market_news", {"headlines": [], "pending": False}),
            ("app.get_initial_ticker_valuation", {"overview": None, "groups": [], "tickers_by_verdict": {}, "pending": True}),
        ):
            patcher = mock.patch(target, return_value=value)
            patcher.start()
            self.addCleanup(patcher.stop)

    def sign_in(self, email="me@example.com"):
        with self.client.session_transaction() as sess:
            sess["email"] = email

    def test_no_client_id_allows_request_without_signing_in(self):
        with mock.patch.dict(os.environ, NO_AUTH_ENV):
            response = self.client.get("/")

        self.assertEqual(response.status_code, 200)

    def test_page_redirects_to_login_when_signed_out(self):
        with mock.patch.dict(os.environ, AUTH_ENV):
            response = self.client.get("/")

        self.assertEqual(response.status_code, 302)
        self.assertTrue(response.headers["Location"].endswith("/login"))

    def test_api_routes_return_401_not_a_redirect_when_signed_out(self):
        with mock.patch.dict(os.environ, AUTH_ENV):
            for path in (
                "/api/check",
                "/api/tickers/groups/stocks/check",
                "/api/market-news/check",
                "/api/tickers/valuation/check",
            ):
                self.assertEqual(self.client.get(path).status_code, 401, path)
            self.assertEqual(self.client.post("/api/tickers/add", json={}).status_code, 401)
            self.assertEqual(self.client.post("/api/tickers/remove", json={}).status_code, 401)

    def test_signed_in_allowed_email_can_view_the_page(self):
        self.sign_in("me@example.com")
        with mock.patch.dict(os.environ, AUTH_ENV):
            response = self.client.get("/")

        self.assertEqual(response.status_code, 200)

    def test_session_for_a_different_email_is_rejected(self):
        self.sign_in("someone-else@example.com")
        with mock.patch.dict(os.environ, AUTH_ENV):
            response = self.client.get("/")

        self.assertEqual(response.status_code, 302)

    def test_partial_config_fails_closed_instead_of_opening_the_dashboard(self):
        with mock.patch.dict(os.environ, {"GOOGLE_CLIENT_ID": "client-id", "GOOGLE_CLIENT_SECRET": "",
                                          "ALLOWED_EMAIL": "", "SECRET_KEY": ""}):
            response = self.client.get("/")

        self.assertEqual(response.status_code, 503)
        self.assertIn("ALLOWED_EMAIL", response.get_data(as_text=True))

    def test_login_redirects_to_google_and_remembers_state(self):
        with mock.patch.dict(os.environ, AUTH_ENV):
            response = self.client.get("/login")
            with self.client.session_transaction() as sess:
                state = sess["oauth_state"]

        location = response.headers["Location"]
        self.assertTrue(location.startswith("https://accounts.google.com/"))
        self.assertIn(f"state={state}", location)
        self.assertIn("client_id=client-id", location)
        self.assertIn("auth%2Fcallback", location)

    def callback(self, email, state="abc", session_state="abc", code="the-code", error=None):
        with self.client.session_transaction() as sess:
            if session_state is not None:
                sess["oauth_state"] = session_state
        with mock.patch.dict(os.environ, AUTH_ENV), mock.patch(
            "app.google_auth.fetch_verified_email", return_value=email, side_effect=error
        ) as fetch:
            query = f"?state={state}" + (f"&code={code}" if code else "")
            return self.client.get("/auth/callback" + query), fetch

    def test_callback_signs_in_the_allowed_email(self):
        response, _ = self.callback("me@example.com")

        self.assertEqual(response.status_code, 302)
        with self.client.session_transaction() as sess:
            self.assertEqual(sess["email"], "me@example.com")
        with mock.patch.dict(os.environ, AUTH_ENV):
            self.assertEqual(self.client.get("/").status_code, 200)

    def test_callback_rejects_a_different_google_account(self):
        response, _ = self.callback("stranger@example.com")

        self.assertEqual(response.status_code, 403)
        with self.client.session_transaction() as sess:
            self.assertNotIn("email", sess)

    def test_callback_rejects_an_unverified_email(self):
        response, _ = self.callback(None)

        self.assertEqual(response.status_code, 403)

    def test_callback_rejects_a_state_mismatch_without_calling_google(self):
        response, fetch = self.callback("me@example.com", state="forged", session_state="abc")

        self.assertEqual(response.status_code, 400)
        fetch.assert_not_called()

    def test_callback_rejects_a_missing_session_state(self):
        response, fetch = self.callback("me@example.com", session_state=None)

        self.assertEqual(response.status_code, 400)
        fetch.assert_not_called()

    def test_callback_rejects_a_missing_code(self):
        response, fetch = self.callback("me@example.com", code=None)

        self.assertEqual(response.status_code, 400)
        fetch.assert_not_called()

    def test_callback_reports_a_google_failure(self):
        response, _ = self.callback("me@example.com", error=google_auth.GoogleAuthError("down"))

        self.assertEqual(response.status_code, 502)

    def test_state_cannot_be_replayed(self):
        self.callback("me@example.com")
        with self.client.session_transaction() as sess:
            sess.pop("email")
        with mock.patch.dict(os.environ, AUTH_ENV):
            response = self.client.get("/auth/callback?state=abc&code=the-code")

        self.assertEqual(response.status_code, 400)

    def test_logout_ends_the_session(self):
        self.sign_in()
        with mock.patch.dict(os.environ, AUTH_ENV):
            self.client.get("/logout")
            response = self.client.get("/")

        self.assertEqual(response.status_code, 302)


class TestApiCheckTickerGroup(unittest.TestCase):
    """The ticker page's background check hits one route per group
    instead of one combined /api/check-tickers, so a group with fewer
    tickers repaints before a slower one finishes."""

    def setUp(self):
        self.client = app_module.app.test_client()
        self.env_patcher = mock.patch.dict(os.environ, NO_AUTH_ENV)
        self.env_patcher.start()
        self.addCleanup(self.env_patcher.stop)

    def test_known_group_returns_only_that_groups_html(self):
        with (
            mock.patch("app.load_ticker_config", return_value={"stocks": ["SPY"], "bonds": ["VGIT"]}),
            mock.patch("app.check_for_ticker_updates") as mock_check,
        ):
            pending_fields = ("price", "change", "change_percent", "week52_low", "week52_high",
                              "pct_off_high", "market_cap", "pe_ratio")
            pending_card = {field: None for field in pending_fields}
            pending_card.update(symbol="SPY", group="stocks", pending=True, error=None)
            mock_check.return_value = {"stocks": [pending_card]}
            response = self.client.get("/api/tickers/groups/stocks/check")

        mock_check.assert_called_once_with(config={"stocks": ["SPY"]})
        self.assertEqual(response.status_code, 200)
        self.assertIn("SPY", response.get_json()["group_html"])

    def test_unknown_group_returns_404_without_fetching(self):
        with (
            mock.patch("app.load_ticker_config", return_value={"stocks": ["SPY"]}),
            mock.patch("app.check_for_ticker_updates") as mock_check,
        ):
            response = self.client.get("/api/tickers/groups/nonexistent/check")

        mock_check.assert_not_called()
        self.assertEqual(response.status_code, 404)
        self.assertIn("error", response.get_json())


class TestApiCheckMarketNews(unittest.TestCase):
    def setUp(self):
        self.client = app_module.app.test_client()
        self.env_patcher = mock.patch.dict(os.environ, NO_AUTH_ENV)
        self.env_patcher.start()
        self.addCleanup(self.env_patcher.stop)

    def test_returns_news_html(self):
        with mock.patch("app.check_for_market_news", return_value={"headlines": [], "pending": False}):
            response = self.client.get("/api/market-news/check")

        self.assertEqual(response.status_code, 200)
        self.assertIn("news_html", response.get_json())


class TestApiCheckTickerValuation(unittest.TestCase):
    def setUp(self):
        self.client = app_module.app.test_client()
        self.env_patcher = mock.patch.dict(os.environ, NO_AUTH_ENV)
        self.env_patcher.start()
        self.addCleanup(self.env_patcher.stop)

    def test_returns_valuation_html(self):
        valuation = {"overview": "Test.", "groups": [], "tickers_by_verdict": {}, "pending": False}
        with mock.patch("app.check_for_ticker_valuation", return_value=valuation):
            response = self.client.get("/api/tickers/valuation/check")

        self.assertEqual(response.status_code, 200)
        self.assertIn("valuation_html", response.get_json())
        self.assertIn("Test.", response.get_json()["valuation_html"])


if __name__ == "__main__":
    unittest.main()
