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
import yahoo_client
from yahoo_client import YahooApiError, fetch_etf_pe_ratio


def quote_summary_response(status_code=200, raw_pe=None, no_result=False):
    if no_result:
        body = {"quoteSummary": {"result": None, "error": {"code": "Not Found"}}}
    else:
        body = {
            "quoteSummary": {
                "result": [{"topHoldings": {"equityHoldings": {"priceToEarnings": {"raw": raw_pe}}}}]
            }
        }
    response = Mock(status_code=status_code, json=lambda: body)
    response.raise_for_status = Mock()
    if status_code >= 400:
        response.raise_for_status.side_effect = requests.HTTPError(f"{status_code}")
    return response


class TestFetchEtfPeRatio(unittest.TestCase):
    def setUp(self):
        yahoo_client._crumb = None

    @patch("yahoo_client._session.get")
    def test_inverts_earnings_yield_into_a_pe_ratio(self, mock_get):
        mock_get.side_effect = [
            Mock(),  # cookie priming GET
            Mock(text="abc123"),  # crumb GET
            quote_summary_response(raw_pe=0.04035),
        ]

        result = fetch_etf_pe_ratio("SPY")

        self.assertAlmostEqual(result, 1 / 0.04035)

    @patch("yahoo_client._session.get")
    def test_zero_raw_value_means_no_equity_holdings(self, mock_get):
        mock_get.side_effect = [Mock(), Mock(text="abc123"), quote_summary_response(raw_pe=0.0)]

        result = fetch_etf_pe_ratio("VGIT")

        self.assertIsNone(result)

    @patch("yahoo_client._session.get")
    def test_no_result_means_symbol_has_no_fundamentals_data(self, mock_get):
        mock_get.side_effect = [Mock(), Mock(text="abc123"), quote_summary_response(no_result=True)]

        result = fetch_etf_pe_ratio("AMD")

        self.assertIsNone(result)

    @patch("yahoo_client._session.get")
    def test_retries_once_with_a_fresh_crumb_on_401(self, mock_get):
        mock_get.side_effect = [
            Mock(),  # cookie priming GET
            Mock(text="stale-crumb"),  # initial crumb GET
            quote_summary_response(status_code=401),  # stale crumb rejected
            Mock(),  # cookie priming GET for refresh
            Mock(text="fresh-crumb"),  # refreshed crumb GET
            quote_summary_response(raw_pe=0.05),  # succeeds with fresh crumb
        ]

        result = fetch_etf_pe_ratio("SPY")

        self.assertAlmostEqual(result, 1 / 0.05)

    @patch("yahoo_client._session.get")
    def test_raises_on_request_exception(self, mock_get):
        mock_get.side_effect = requests.ConnectionError("boom")

        with self.assertRaises(YahooApiError):
            fetch_etf_pe_ratio("SPY")

    @patch("yahoo_client._session.get")
    def test_raises_on_unexpected_response_shape(self, mock_get):
        mock_get.side_effect = [Mock(), Mock(text="abc123"), Mock(status_code=200, json=lambda: {})]

        with self.assertRaises(YahooApiError):
            fetch_etf_pe_ratio("SPY")

    @patch("yahoo_client._session.get")
    def test_raises_on_empty_crumb_response(self, mock_get):
        mock_get.side_effect = [Mock(), Mock(text="  ")]

        with self.assertRaises(YahooApiError):
            fetch_etf_pe_ratio("SPY")

    @patch("yahoo_client._session.get")
    def test_crumb_is_cached_across_calls(self, mock_get):
        mock_get.side_effect = [
            Mock(),
            Mock(text="abc123"),
            quote_summary_response(raw_pe=0.04),
            quote_summary_response(raw_pe=0.05),
        ]

        fetch_etf_pe_ratio("SPY")
        fetch_etf_pe_ratio("DGRO")

        self.assertEqual(mock_get.call_count, 4)  # 2 for the crumb handshake, then one call each


if __name__ == "__main__":
    unittest.main()
