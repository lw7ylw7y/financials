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
    @patch("yahoo_client._session.get")
    def test_inverts_earnings_yield_into_a_pe_ratio(self, mock_get):
        mock_get.return_value = quote_summary_response(raw_pe=0.04035)

        result = fetch_etf_pe_ratio("SPY")

        self.assertAlmostEqual(result, 1 / 0.04035)

    @patch("yahoo_client._session.get")
    def test_zero_raw_value_means_no_equity_holdings(self, mock_get):
        mock_get.return_value = quote_summary_response(raw_pe=0.0)

        result = fetch_etf_pe_ratio("VGIT")

        self.assertIsNone(result)

    @patch("yahoo_client._session.get")
    def test_no_result_means_symbol_has_no_fundamentals_data(self, mock_get):
        mock_get.return_value = quote_summary_response(no_result=True)

        result = fetch_etf_pe_ratio("AMD")

        self.assertIsNone(result)

    @patch("yahoo_client._session.get")
    def test_raises_on_request_exception(self, mock_get):
        mock_get.side_effect = requests.ConnectionError("boom")

        with self.assertRaises(YahooApiError):
            fetch_etf_pe_ratio("SPY")

    @patch("yahoo_client._session.get")
    def test_raises_on_http_error(self, mock_get):
        mock_get.return_value = quote_summary_response(status_code=404)

        with self.assertRaises(YahooApiError):
            fetch_etf_pe_ratio("SPY")

    @patch("yahoo_client._session.get")
    def test_raises_on_unexpected_response_shape(self, mock_get):
        mock_get.return_value = Mock(status_code=200, json=lambda: {})
        mock_get.return_value.raise_for_status = Mock()

        with self.assertRaises(YahooApiError):
            fetch_etf_pe_ratio("SPY")


if __name__ == "__main__":
    unittest.main()
