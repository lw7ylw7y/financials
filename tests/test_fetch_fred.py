import os
import sys
import unittest
from unittest.mock import Mock, patch

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

import requests
from fetch_fred import FredApiError, fetch_latest_observation


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


if __name__ == "__main__":
    unittest.main()
