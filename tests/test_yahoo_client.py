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
from yahoo_client import YahooApiError, fetch_daily_closes


def make_response(closes):
    return Mock(
        json=lambda: {
            "chart": {
                "result": [
                    {"indicators": {"quote": [{"close": closes}]}}
                ]
            }
        }
    )


class TestFetchDailyCloses(unittest.TestCase):
    @patch("yahoo_client._session.get")
    def test_parses_closes_oldest_to_newest(self, mock_get):
        mock_get.return_value = make_response([100.0, 101.5, 99.25])

        result = fetch_daily_closes("SPY")

        self.assertEqual(result, [100.0, 101.5, 99.25])

    @patch("yahoo_client._session.get")
    def test_skips_null_closes(self, mock_get):
        mock_get.return_value = make_response([100.0, None, 99.25])

        result = fetch_daily_closes("SPY")

        self.assertEqual(result, [100.0, 99.25])

    @patch("yahoo_client._session.get")
    def test_raises_on_all_null_closes(self, mock_get):
        mock_get.return_value = make_response([None, None])

        with self.assertRaises(YahooApiError):
            fetch_daily_closes("SPY")

    @patch("yahoo_client._session.get")
    def test_raises_on_unexpected_response_shape(self, mock_get):
        mock_get.return_value = Mock(json=lambda: {"chart": {"result": None}})

        with self.assertRaises(YahooApiError):
            fetch_daily_closes("SPY")

    @patch("yahoo_client._session.get")
    def test_raises_on_request_exception(self, mock_get):
        mock_get.side_effect = requests.ConnectionError("boom")

        with self.assertRaises(YahooApiError):
            fetch_daily_closes("SPY")


if __name__ == "__main__":
    unittest.main()
