import json
import os
import sys
import unittest
from types import SimpleNamespace
from unittest.mock import Mock, patch

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from google.genai import errors
from interpret import InterpretationError, interpret

INDICATOR = {"name": "Nonfarm Payrolls", "category": "coincident"}
HISTORY_WINDOW = [
    {"date": "2026-07-01", "value": 158000.0},
    {"date": "2026-08-01", "value": 159075.0},
]


def fake_client(text=None, side_effect=None):
    client = Mock()
    if side_effect is not None:
        client.models.generate_content.side_effect = side_effect
    else:
        client.models.generate_content.return_value = SimpleNamespace(text=text)
    return client


def make_api_error():
    # google.genai.errors.APIError expects (code, response_json)
    return errors.ClientError(400, {"error": {"message": "bad request"}})


class TestInterpret(unittest.TestCase):
    def test_parses_summary_and_directional_read(self):
        text = json.dumps(
            {"summary": "Payrolls rose modestly.", "directional_read": "neutral"}
        )
        client = fake_client(text=text)

        result = interpret(INDICATOR, HISTORY_WINDOW, client=client)

        self.assertEqual(
            result, {"summary": "Payrolls rose modestly.", "directional_read": "neutral"}
        )

    def test_raises_on_api_error(self):
        client = fake_client(side_effect=make_api_error())

        with self.assertRaises(InterpretationError):
            interpret(INDICATOR, HISTORY_WINDOW, client=client)

    def test_raises_on_malformed_json(self):
        client = fake_client(text="not json")

        with self.assertRaises(InterpretationError):
            interpret(INDICATOR, HISTORY_WINDOW, client=client)

    def test_raises_on_invalid_directional_read(self):
        text = json.dumps({"summary": "ok", "directional_read": "up"})
        client = fake_client(text=text)

        with self.assertRaises(InterpretationError):
            interpret(INDICATOR, HISTORY_WINDOW, client=client)

    def test_raises_on_missing_summary(self):
        text = json.dumps({"directional_read": "neutral"})
        client = fake_client(text=text)

        with self.assertRaises(InterpretationError):
            interpret(INDICATOR, HISTORY_WINDOW, client=client)

    def test_raises_on_empty_response_text(self):
        client = fake_client(text=None)

        with self.assertRaises(InterpretationError):
            interpret(INDICATOR, HISTORY_WINDOW, client=client)

    def test_raises_when_no_credentials_configured(self):
        # genai.Client() raises a bare ValueError (not an APIError) when no
        # API key is configured - confirmed against the real SDK.
        with patch(
            "interpret.genai.Client",
            side_effect=ValueError("No API key was provided."),
        ):
            with self.assertRaises(InterpretationError):
                interpret(INDICATOR, HISTORY_WINDOW, client=None)


if __name__ == "__main__":
    unittest.main()
