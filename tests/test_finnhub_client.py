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
    fetch_company_industry,
    fetch_market_news,
    fetch_quote,
    fetch_stock_metrics,
)


class TestFetchQuote(unittest.TestCase):
    @patch("finnhub_client._session.get")
    def test_parses_price_and_change(self, mock_get):
        mock_get.return_value = Mock(json=lambda: {"c": 452.31, "d": 3.81, "dp": 0.85})

        result = fetch_quote("SPY", api_key="test-key")

        self.assertEqual(result, {"price": 452.31, "change": 3.81, "change_percent": 0.85})

    @patch("finnhub_client._session.get")
    def test_missing_change_fields_degrade_to_none(self, mock_get):
        mock_get.return_value = Mock(json=lambda: {"c": 452.31})

        result = fetch_quote("SPY", api_key="test-key")

        self.assertEqual(result, {"price": 452.31, "change": None, "change_percent": None})

    @patch("finnhub_client._session.get")
    def test_raises_on_zero_price(self, mock_get):
        mock_get.return_value = Mock(json=lambda: {"c": 0})

        with self.assertRaises(FinnhubApiError):
            fetch_quote("BADSYM", api_key="test-key")

    @patch("finnhub_client._session.get")
    def test_raises_on_request_exception(self, mock_get):
        mock_get.side_effect = requests.ConnectionError("boom")

        with self.assertRaises(FinnhubApiError):
            fetch_quote("SPY", api_key="test-key")

    @patch.dict(os.environ, {}, clear=True)
    def test_raises_without_api_key(self):
        with self.assertRaises(FinnhubApiError):
            fetch_quote("SPY", api_key=None)


class TestFetchStockMetrics(unittest.TestCase):
    @patch("finnhub_client._session.get")
    def test_parses_range_market_cap_pe_and_peg(self, mock_get):
        mock_get.return_value = Mock(
            json=lambda: {
                "metric": {
                    "52WeekLow": 629.28,
                    "52WeekHigh": 779.37,
                    "marketCapitalization": 3500000.0,
                    "peTTM": 34.2,
                    "pegTTM": 2.1,
                }
            }
        )

        result = fetch_stock_metrics("SPY", api_key="test-key")

        self.assertEqual(
            result,
            {
                "low": 629.28, "high": 779.37, "market_cap": 3500000.0,
                "pe_ratio": 34.2, "peg_ratio": 2.1,
                "revenue_growth": None, "eps_growth": None, "roe": None,
                "net_margin": None, "debt_to_equity": None, "dividend_yield": None,
            },
        )

    @patch("finnhub_client._session.get")
    def test_parses_growth_and_quality_fields(self, mock_get):
        mock_get.return_value = Mock(
            json=lambda: {
                "metric": {
                    "52WeekLow": 1.0,
                    "52WeekHigh": 2.0,
                    "revenueGrowthTTMYoy": 14.24,
                    "epsGrowthTTMYoy": 32.61,
                    "roeTTM": 137.18,
                    "netProfitMarginTTM": 27.62,
                    "totalDebt/totalEquityAnnual": 1.3547,
                    "dividendYieldIndicatedAnnual": 0.505,
                }
            }
        )

        result = fetch_stock_metrics("AAPL", api_key="test-key")

        self.assertEqual(result["revenue_growth"], 14.24)
        self.assertEqual(result["eps_growth"], 32.61)
        self.assertEqual(result["roe"], 137.18)
        self.assertEqual(result["net_margin"], 27.62)
        self.assertEqual(result["debt_to_equity"], 1.3547)
        self.assertEqual(result["dividend_yield"], 0.505)

    @patch("finnhub_client._session.get")
    def test_missing_market_cap_pe_peg_and_growth_fields_degrade_to_none(self, mock_get):
        mock_get.return_value = Mock(
            json=lambda: {"metric": {"52WeekLow": 629.28, "52WeekHigh": 779.37}}
        )

        result = fetch_stock_metrics("SPY", api_key="test-key")

        self.assertIsNone(result["market_cap"])
        self.assertIsNone(result["pe_ratio"])
        self.assertIsNone(result["peg_ratio"])
        self.assertIsNone(result["revenue_growth"])
        self.assertIsNone(result["eps_growth"])
        self.assertIsNone(result["roe"])
        self.assertIsNone(result["net_margin"])
        self.assertIsNone(result["debt_to_equity"])
        self.assertIsNone(result["dividend_yield"])

    @patch("finnhub_client._session.get")
    def test_pe_falls_back_through_alternate_fields(self, mock_get):
        mock_get.return_value = Mock(
            json=lambda: {
                "metric": {
                    "52WeekLow": 1.0,
                    "52WeekHigh": 2.0,
                    "peBasicExclExtraTTM": 18.5,
                }
            }
        )

        result = fetch_stock_metrics("SPY", api_key="test-key")

        self.assertEqual(result["pe_ratio"], 18.5)

    @patch("finnhub_client._session.get")
    def test_peg_falls_back_to_forward_peg(self, mock_get):
        mock_get.return_value = Mock(
            json=lambda: {
                "metric": {
                    "52WeekLow": 1.0,
                    "52WeekHigh": 2.0,
                    "forwardPEG": 1.8,
                }
            }
        )

        result = fetch_stock_metrics("SPY", api_key="test-key")

        self.assertEqual(result["peg_ratio"], 1.8)

    @patch("finnhub_client._session.get")
    def test_raises_on_missing_metric(self, mock_get):
        mock_get.return_value = Mock(json=lambda: {"metric": {}})

        with self.assertRaises(FinnhubApiError):
            fetch_stock_metrics("BADSYM", api_key="test-key")

    @patch("finnhub_client._session.get")
    def test_raises_on_request_exception(self, mock_get):
        mock_get.side_effect = requests.ConnectionError("boom")

        with self.assertRaises(FinnhubApiError):
            fetch_stock_metrics("SPY", api_key="test-key")


class TestFetchMarketNews(unittest.TestCase):
    @patch("finnhub_client._session.get")
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

    @patch("finnhub_client._session.get")
    def test_respects_limit(self, mock_get):
        mock_get.return_value = Mock(
            json=lambda: [
                {"category": "top news", "headline": f"Headline {i}", "url": f"https://{i}", "datetime": i}
                for i in range(20)
            ]
        )

        result = fetch_market_news(api_key="test-key", limit=5)

        self.assertEqual(len(result), 5)

    @patch("finnhub_client._session.get")
    def test_skips_articles_missing_headline_or_url(self, mock_get):
        mock_get.return_value = Mock(
            json=lambda: [
                {"category": "top news", "headline": "", "url": "https://a", "datetime": 1},
                {"category": "top news", "headline": "Fine", "url": "", "datetime": 2},
            ]
        )

        result = fetch_market_news(api_key="test-key")

        self.assertEqual(result, [])

    @patch("finnhub_client._session.get")
    def test_empty_response_returns_empty_list(self, mock_get):
        mock_get.return_value = Mock(json=lambda: [])

        result = fetch_market_news(api_key="test-key")

        self.assertEqual(result, [])

    @patch("finnhub_client._session.get")
    def test_raises_on_request_exception(self, mock_get):
        mock_get.side_effect = requests.ConnectionError("boom")

        with self.assertRaises(FinnhubApiError):
            fetch_market_news(api_key="test-key")

    @patch.dict(os.environ, {}, clear=True)
    def test_raises_without_api_key(self):
        with self.assertRaises(FinnhubApiError):
            fetch_market_news(api_key=None)


class TestFetchCompanyIndustry(unittest.TestCase):
    @patch("finnhub_client._session.get")
    def test_returns_finnhub_industry(self, mock_get):
        mock_get.return_value = Mock(json=lambda: {"finnhubIndustry": "Semiconductors"})

        result = fetch_company_industry("AMD", api_key="test-key")

        self.assertEqual(result, "Semiconductors")

    @patch("finnhub_client._session.get")
    def test_missing_industry_returns_none(self, mock_get):
        mock_get.return_value = Mock(json=lambda: {})

        result = fetch_company_industry("SPY", api_key="test-key")

        self.assertIsNone(result)

    @patch("finnhub_client._session.get")
    def test_raises_on_request_exception(self, mock_get):
        mock_get.side_effect = requests.ConnectionError("boom")

        with self.assertRaises(FinnhubApiError):
            fetch_company_industry("AMD", api_key="test-key")

    @patch.dict(os.environ, {}, clear=True)
    def test_raises_without_api_key(self):
        with self.assertRaises(FinnhubApiError):
            fetch_company_industry("AMD", api_key=None)


if __name__ == "__main__":
    unittest.main()
