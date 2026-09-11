import os
import sys
import unittest
from unittest.mock import Mock, patch

_SRC = os.path.join(os.path.dirname(__file__), "..", "src")
for _p in (
    _SRC,
    os.path.join(_SRC, "fred"),
    os.path.join(_SRC, "storage"),
    os.path.join(_SRC, "digest"),
    os.path.join(_SRC, "mailer"),
):
    sys.path.insert(0, _p)

import requests
from fetch_fred import (
    FredApiError,
    fetch_latest_observation,
    fetch_next_release_date,
    fetch_recent_observations,
)


class TestFetchLatestObservation(unittest.TestCase):
    @patch("fetch_fred.requests.get")
    def test_parses_latest_observation(self, mock_get):
        mock_get.return_value = Mock(
            json=lambda: {"observations": [{"date": "2026-08-30", "value": "235000"}]}
        )

        result = fetch_latest_observation("ICSA", api_key="test-key")

        self.assertEqual(result, {"date": "2026-08-30", "value": 235000.0})

    @patch("fetch_fred.requests.get")
    def test_raises_on_missing_value(self, mock_get):
        mock_get.return_value = Mock(
            json=lambda: {"observations": [{"date": "2026-08-30", "value": "."}]}
        )

        with self.assertRaises(FredApiError):
            fetch_latest_observation("ICSA", api_key="test-key")

    @patch("fetch_fred.requests.get")
    def test_raises_on_empty_observations(self, mock_get):
        mock_get.return_value = Mock(json=lambda: {"observations": []})

        with self.assertRaises(FredApiError):
            fetch_latest_observation("ICSA", api_key="test-key")

    @patch("fetch_fred.requests.get")
    def test_raises_on_request_exception(self, mock_get):
        mock_get.side_effect = requests.ConnectionError("boom")

        with self.assertRaises(FredApiError):
            fetch_latest_observation("ICSA", api_key="test-key")

    @patch.dict(os.environ, {}, clear=True)
    def test_raises_without_api_key(self):
        with self.assertRaises(FredApiError):
            fetch_latest_observation("ICSA")


class TestFetchRecentObservations(unittest.TestCase):
    @patch("fetch_fred.requests.get")
    def test_returns_oldest_to_newest(self, mock_get):
        # FRED returns newest-first for sort_order=desc.
        mock_get.return_value = Mock(
            json=lambda: {
                "observations": [
                    {"date": "2026-08-01", "value": "334.131"},
                    {"date": "2026-07-01", "value": "332.813"},
                    {"date": "2026-06-01", "value": "331.5"},
                ]
            }
        )

        result = fetch_recent_observations("CPIAUCSL", limit=3, api_key="test-key")

        self.assertEqual(
            result,
            [
                {"date": "2026-06-01", "value": 331.5},
                {"date": "2026-07-01", "value": 332.813},
                {"date": "2026-08-01", "value": 334.131},
            ],
        )

    @patch("fetch_fred.requests.get")
    def test_skips_missing_values(self, mock_get):
        mock_get.return_value = Mock(
            json=lambda: {
                "observations": [
                    {"date": "2026-08-01", "value": "."},
                    {"date": "2026-07-01", "value": "332.813"},
                ]
            }
        )

        result = fetch_recent_observations("CPIAUCSL", limit=2, api_key="test-key")

        self.assertEqual(result, [{"date": "2026-07-01", "value": 332.813}])

    @patch("fetch_fred.requests.get")
    def test_returns_empty_list_when_no_observations(self, mock_get):
        mock_get.return_value = Mock(json=lambda: {"observations": []})

        result = fetch_recent_observations("CPIAUCSL", api_key="test-key")

        self.assertEqual(result, [])

    @patch("fetch_fred.requests.get")
    def test_raises_on_request_exception(self, mock_get):
        mock_get.side_effect = requests.ConnectionError("boom")

        with self.assertRaises(FredApiError):
            fetch_recent_observations("CPIAUCSL", api_key="test-key")

    @patch.dict(os.environ, {}, clear=True)
    def test_raises_without_api_key(self):
        with self.assertRaises(FredApiError):
            fetch_recent_observations("CPIAUCSL")


class TestFetchNextReleaseDate(unittest.TestCase):
    @patch("fetch_fred.requests.get")
    def test_returns_earliest_upcoming_date(self, mock_get):
        # Dates out of order and including past dates, to confirm the
        # result isn't just "first in the response".
        mock_get.return_value = Mock(
            json=lambda: {
                "release_dates": [
                    {"date": "2026-08-06"},
                    {"date": "2026-10-01"},
                    {"date": "2026-09-11"},
                    {"date": "2026-07-02"},
                ]
            }
        )

        result = fetch_next_release_date(
            "180", api_key="test-key", today="2026-09-05"
        )

        self.assertEqual(result, "2026-09-11")

    @patch("fetch_fred.requests.get")
    def test_today_counts_as_upcoming(self, mock_get):
        mock_get.return_value = Mock(
            json=lambda: {"release_dates": [{"date": "2026-09-05"}]}
        )

        result = fetch_next_release_date(
            "180", api_key="test-key", today="2026-09-05"
        )

        self.assertEqual(result, "2026-09-05")

    @patch("fetch_fred.requests.get")
    def test_returns_none_when_no_upcoming_dates(self, mock_get):
        mock_get.return_value = Mock(
            json=lambda: {"release_dates": [{"date": "2026-01-01"}]}
        )

        result = fetch_next_release_date(
            "180", api_key="test-key", today="2026-09-05"
        )

        self.assertIsNone(result)

    @patch("fetch_fred.requests.get")
    def test_raises_on_request_exception(self, mock_get):
        mock_get.side_effect = requests.ConnectionError("boom")

        with self.assertRaises(FredApiError):
            fetch_next_release_date("180", api_key="test-key")

    @patch.dict(os.environ, {}, clear=True)
    def test_raises_without_api_key(self):
        with self.assertRaises(FredApiError):
            fetch_next_release_date("180")


if __name__ == "__main__":
    unittest.main()
