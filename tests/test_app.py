import base64
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

NO_AUTH_ENV = {"DASHBOARD_USERNAME": "", "DASHBOARD_PASSWORD": ""}


def basic_auth_header(username: str, password: str) -> dict:
    token = base64.b64encode(f"{username}:{password}".encode()).decode()
    return {"Authorization": f"Basic {token}"}


class TestDashboardAuth(unittest.TestCase):
    """Story 8: HTTP Basic Auth gate in front of every route, on only
    when both DASHBOARD_USERNAME/PASSWORD are set. Data/network calls
    are mocked out -- this is testing the auth gate, not page content.
    """

    def setUp(self):
        self.client = app_module.app.test_client()
        for target, value in (
            ("app.get_initial_page_data", {"table": {}, "countdown": {"entries": []}, "ai_result": None}),
            ("app.get_initial_ticker_page_data", {}),
            ("app.get_initial_market_news", {"headlines": [], "pending": False}),
            ("app.get_initial_ticker_valuation", {"overview": None, "groups": [], "individual_by_verdict": {}, "pending": True}),
        ):
            patcher = mock.patch(target, return_value=value)
            patcher.start()
            self.addCleanup(patcher.stop)

    def test_no_env_vars_allows_request_without_credentials(self):
        with mock.patch.dict(os.environ, NO_AUTH_ENV):
            response = self.client.get("/")

        self.assertEqual(response.status_code, 200)

    def test_only_username_set_is_still_a_no_op(self):
        with mock.patch.dict(os.environ, {**NO_AUTH_ENV, "DASHBOARD_USERNAME": "alice"}):
            response = self.client.get("/")

        self.assertEqual(response.status_code, 200)

    def test_missing_credentials_rejected_when_configured(self):
        with mock.patch.dict(os.environ, {"DASHBOARD_USERNAME": "alice", "DASHBOARD_PASSWORD": "secret"}):
            response = self.client.get("/")

        self.assertEqual(response.status_code, 401)
        self.assertIn("Basic", response.headers.get("WWW-Authenticate", ""))

    def test_wrong_credentials_rejected(self):
        with mock.patch.dict(os.environ, {"DASHBOARD_USERNAME": "alice", "DASHBOARD_PASSWORD": "secret"}):
            response = self.client.get("/", headers=basic_auth_header("alice", "wrong"))

        self.assertEqual(response.status_code, 401)

    def test_correct_credentials_allowed(self):
        with mock.patch.dict(os.environ, {"DASHBOARD_USERNAME": "alice", "DASHBOARD_PASSWORD": "secret"}):
            response = self.client.get("/", headers=basic_auth_header("alice", "secret"))

        self.assertEqual(response.status_code, 200)

    def test_api_routes_require_auth_too(self):
        with mock.patch.dict(os.environ, {"DASHBOARD_USERNAME": "alice", "DASHBOARD_PASSWORD": "secret"}):
            response = self.client.get("/api/check")

        self.assertEqual(response.status_code, 401)

    def test_ticker_group_check_route_requires_auth_too(self):
        with mock.patch.dict(os.environ, {"DASHBOARD_USERNAME": "alice", "DASHBOARD_PASSWORD": "secret"}):
            response = self.client.get("/api/tickers/groups/stocks/check")

        self.assertEqual(response.status_code, 401)

    def test_ticker_valuation_check_route_requires_auth_too(self):
        with mock.patch.dict(os.environ, {"DASHBOARD_USERNAME": "alice", "DASHBOARD_PASSWORD": "secret"}):
            response = self.client.get("/api/tickers/valuation/check")

        self.assertEqual(response.status_code, 401)


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
        valuation = {"overview": "Test.", "groups": [], "individual_by_verdict": {}, "pending": False}
        with mock.patch("app.check_for_ticker_valuation", return_value=valuation):
            response = self.client.get("/api/tickers/valuation/check")

        self.assertEqual(response.status_code, 200)
        self.assertIn("valuation_html", response.get_json())
        self.assertIn("Test.", response.get_json()["valuation_html"])


if __name__ == "__main__":
    unittest.main()
