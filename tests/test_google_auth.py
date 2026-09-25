import os
import sys
import unittest
from unittest.mock import Mock, patch
from urllib.parse import parse_qs, urlparse

_SRC = os.path.join(os.path.dirname(__file__), "..", "src")
for _p in (
    _SRC,
    os.path.join(_SRC, "web"),
):
    sys.path.insert(0, _p)

import requests

from google_auth import (
    GoogleAuthError,
    allowed_email,
    build_authorize_url,
    fetch_verified_email,
    is_enabled,
    missing_config,
)

ENV = {"GOOGLE_CLIENT_ID": "cid", "GOOGLE_CLIENT_SECRET": "csecret", "ALLOWED_EMAIL": " Me@Example.com "}


class TestConfig(unittest.TestCase):
    @patch.dict(os.environ, {}, clear=True)
    def test_disabled_without_client_id(self):
        self.assertFalse(is_enabled())

    @patch.dict(os.environ, {"GOOGLE_CLIENT_ID": "cid"}, clear=True)
    def test_enabled_by_client_id_alone_and_reports_what_is_missing(self):
        self.assertTrue(is_enabled())
        self.assertEqual(missing_config(), ["GOOGLE_CLIENT_SECRET", "ALLOWED_EMAIL", "SECRET_KEY"])

    @patch.dict(os.environ, ENV, clear=True)
    def test_allowed_email_is_trimmed_and_lowercased(self):
        self.assertEqual(allowed_email(), "me@example.com")


class TestBuildAuthorizeUrl(unittest.TestCase):
    @patch.dict(os.environ, ENV, clear=True)
    def test_includes_the_required_oauth_parameters(self):
        url = build_authorize_url("https://app.example/auth/callback", "st8")

        parsed = urlparse(url)
        params = parse_qs(parsed.query)
        self.assertEqual(parsed.netloc, "accounts.google.com")
        self.assertEqual(params["client_id"], ["cid"])
        self.assertEqual(params["redirect_uri"], ["https://app.example/auth/callback"])
        self.assertEqual(params["response_type"], ["code"])
        self.assertEqual(params["state"], ["st8"])
        self.assertEqual(params["scope"], ["openid email"])


class TestFetchVerifiedEmail(unittest.TestCase):
    def responses(self, info):
        token = Mock(json=lambda: {"access_token": "tok"})
        userinfo = Mock(json=lambda: info)
        return token, userinfo

    @patch.dict(os.environ, ENV, clear=True)
    @patch("google_auth._session.get")
    @patch("google_auth._session.post")
    def test_returns_the_lowercased_verified_email(self, mock_post, mock_get):
        mock_post.return_value, mock_get.return_value = self.responses(
            {"email": "Me@Example.com", "email_verified": True}
        )

        self.assertEqual(fetch_verified_email("code", "https://app/cb"), "me@example.com")
        self.assertEqual(mock_post.call_args.kwargs["data"]["code"], "code")
        self.assertEqual(mock_post.call_args.kwargs["data"]["client_secret"], "csecret")
        self.assertEqual(mock_get.call_args.kwargs["headers"]["Authorization"], "Bearer tok")

    @patch.dict(os.environ, ENV, clear=True)
    @patch("google_auth._session.get")
    @patch("google_auth._session.post")
    def test_unverified_email_returns_none(self, mock_post, mock_get):
        mock_post.return_value, mock_get.return_value = self.responses(
            {"email": "me@example.com", "email_verified": False}
        )

        self.assertIsNone(fetch_verified_email("code", "https://app/cb"))

    @patch.dict(os.environ, ENV, clear=True)
    @patch("google_auth._session.post", side_effect=requests.ConnectionError("down"))
    def test_request_failure_raises(self, _):
        with self.assertRaises(GoogleAuthError):
            fetch_verified_email("code", "https://app/cb")

    @patch.dict(os.environ, ENV, clear=True)
    @patch("google_auth._session.post")
    def test_missing_access_token_raises(self, mock_post):
        mock_post.return_value = Mock(json=lambda: {"error": "invalid_grant"})

        with self.assertRaises(GoogleAuthError):
            fetch_verified_email("code", "https://app/cb")


if __name__ == "__main__":
    unittest.main()
