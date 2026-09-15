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


if __name__ == "__main__":
    unittest.main()
