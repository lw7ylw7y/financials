import os
import sys
import unittest
from unittest.mock import Mock, patch

_SRC = os.path.join(os.path.dirname(__file__), "..", "src")
for _p in (
    _SRC,
    os.path.join(_SRC, "web"),
):
    sys.path.insert(0, _p)

import requests
from finnhub_client import FinnhubApiError, fetch_52_week_range, fetch_quote


class TestFetchQuote(unittest.TestCase):
    @patch("finnhub_client.requests.get")
    def test_parses_price(self, mock_get):
        mock_get.return_value = Mock(json=lambda: {"c": 452.31})

        result = fetch_quote("SPY", api_key="test-key")

        self.assertEqual(result, {"price": 452.31})

    @patch("finnhub_client.requests.get")
    def test_raises_on_zero_price(self, mock_get):
        mock_get.return_value = Mock(json=lambda: {"c": 0})

        with self.assertRaises(FinnhubApiError):
            fetch_quote("BADSYM", api_key="test-key")

    @patch("finnhub_client.requests.get")
    def test_raises_on_request_exception(self, mock_get):
        mock_get.side_effect = requests.ConnectionError("boom")

        with self.assertRaises(FinnhubApiError):
            fetch_quote("SPY", api_key="test-key")

    @patch.dict(os.environ, {}, clear=True)
    def test_raises_without_api_key(self):
        with self.assertRaises(FinnhubApiError):
            fetch_quote("SPY", api_key=None)


class TestFetch52WeekRange(unittest.TestCase):
    @patch("finnhub_client.requests.get")
    def test_parses_range(self, mock_get):
        mock_get.return_value = Mock(
            json=lambda: {"metric": {"52WeekLow": 629.28, "52WeekHigh": 779.37}}
        )

        result = fetch_52_week_range("SPY", api_key="test-key")

        self.assertEqual(result, {"low": 629.28, "high": 779.37})

    @patch("finnhub_client.requests.get")
    def test_raises_on_missing_metric(self, mock_get):
        mock_get.return_value = Mock(json=lambda: {"metric": {}})

        with self.assertRaises(FinnhubApiError):
            fetch_52_week_range("BADSYM", api_key="test-key")

    @patch("finnhub_client.requests.get")
    def test_raises_on_request_exception(self, mock_get):
        mock_get.side_effect = requests.ConnectionError("boom")

        with self.assertRaises(FinnhubApiError):
            fetch_52_week_range("SPY", api_key="test-key")


if __name__ == "__main__":
    unittest.main()
