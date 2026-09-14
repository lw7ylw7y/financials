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
from finnhub_client import (
    FinnhubApiError,
    fetch_52_week_range,
    fetch_market_news,
    fetch_quote,
)


class TestFetchQuote(unittest.TestCase):
    @patch("finnhub_client.requests.get")
    def test_parses_price_and_change(self, mock_get):
        mock_get.return_value = Mock(json=lambda: {"c": 452.31, "d": 3.81, "dp": 0.85})

        result = fetch_quote("SPY", api_key="test-key")

        self.assertEqual(result, {"price": 452.31, "change": 3.81, "change_percent": 0.85})

    @patch("finnhub_client.requests.get")
    def test_missing_change_fields_degrade_to_none(self, mock_get):
        mock_get.return_value = Mock(json=lambda: {"c": 452.31})

        result = fetch_quote("SPY", api_key="test-key")

        self.assertEqual(result, {"price": 452.31, "change": None, "change_percent": None})

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


class TestFetchMarketNews(unittest.TestCase):
    @patch("finnhub_client.requests.get")
    def test_filters_to_top_news_category(self, mock_get):
        mock_get.return_value = Mock(
            json=lambda: [
                {"category": "top news", "headline": "Stocks rally", "url": "https://a", "datetime": 2, "source": "CNBC"},
                {"category": "business", "headline": "Unrelated world news", "url": "https://b", "datetime": 1, "source": "Reuters"},
            ]
        )

        result = fetch_market_news(api_key="test-key")

        self.assertEqual(len(result), 1)
        self.assertEqual(result[0]["headline"], "Stocks rally")
        self.assertEqual(result[0]["source"], "CNBC")

    @patch("finnhub_client.requests.get")
    def test_respects_limit(self, mock_get):
        mock_get.return_value = Mock(
            json=lambda: [
                {"category": "top news", "headline": f"Headline {i}", "url": f"https://{i}", "datetime": i}
                for i in range(20)
            ]
        )

        result = fetch_market_news(api_key="test-key", limit=5)

        self.assertEqual(len(result), 5)

    @patch("finnhub_client.requests.get")
    def test_skips_articles_missing_headline_or_url(self, mock_get):
        mock_get.return_value = Mock(
            json=lambda: [
                {"category": "top news", "headline": "", "url": "https://a", "datetime": 1},
                {"category": "top news", "headline": "Fine", "url": "", "datetime": 2},
            ]
        )

        result = fetch_market_news(api_key="test-key")

        self.assertEqual(result, [])

    @patch("finnhub_client.requests.get")
    def test_empty_response_returns_empty_list(self, mock_get):
        mock_get.return_value = Mock(json=lambda: [])

        result = fetch_market_news(api_key="test-key")

        self.assertEqual(result, [])

    @patch("finnhub_client.requests.get")
    def test_raises_on_request_exception(self, mock_get):
        mock_get.side_effect = requests.ConnectionError("boom")

        with self.assertRaises(FinnhubApiError):
            fetch_market_news(api_key="test-key")

    @patch.dict(os.environ, {}, clear=True)
    def test_raises_without_api_key(self):
        with self.assertRaises(FinnhubApiError):
            fetch_market_news(api_key=None)


if __name__ == "__main__":
    unittest.main()
