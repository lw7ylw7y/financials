import json
import os
import sys
import unittest
from types import SimpleNamespace
from unittest.mock import Mock, patch

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from google.genai import errors
from interpret import InterpretationError, build_user_prompt, interpret

INDICATORS_CONTEXT = [
    {
        "key": "nonfarm_payrolls",
        "name": "Nonfarm Payrolls",
        "category": "coincident",
        "history_window": [
            {"date": "2026-07-01", "value": 158000.0},
            {"date": "2026-08-01", "value": 159075.0},
        ],
        "heuristic": None,
    },
    {
        "key": "cpi",
        "name": "CPI",
        "category": "lagging",
        "history_window": [
            {"date": "2026-07-01", "value": 332.813},
            {"date": "2026-08-01", "value": 334.131},
        ],
        "heuristic": None,
    },
]
UPDATED_KEYS = ["cpi"]


def fake_client(text=None, side_effect=None):
    client = Mock()
    if side_effect is not None:
        client.models.generate_content.side_effect = side_effect
    else:
        client.models.generate_content.return_value = SimpleNamespace(text=text)
    return client


def make_api_error():
    return errors.ClientError(400, {"error": {"message": "bad request"}})


class TestBuildUserPrompt(unittest.TestCase):
    def test_marks_updated_indicators_and_includes_all(self):
        prompt = build_user_prompt(INDICATORS_CONTEXT, UPDATED_KEYS)

        self.assertIn("Indicators with a new value this run: CPI", prompt)
        self.assertIn("### Nonfarm Payrolls (coincident)", prompt)
        self.assertIn("### CPI (lagging) — NEW VALUE THIS RUN", prompt)


class TestInterpret(unittest.TestCase):
    def test_parses_summary_and_directional_read(self):
        text = json.dumps(
            {
                "summary": "Inflation ticked up while employment stayed solid.",
                "directional_read": "neutral",
            }
        )
        client = fake_client(text=text)

        result = interpret(INDICATORS_CONTEXT, UPDATED_KEYS, client=client)

        self.assertEqual(
            result,
            {
                "summary": "Inflation ticked up while employment stayed solid.",
                "directional_read": "neutral",
            },
        )

    def test_raises_on_api_error(self):
        client = fake_client(side_effect=make_api_error())

        with self.assertRaises(InterpretationError):
            interpret(INDICATORS_CONTEXT, UPDATED_KEYS, client=client)

    def test_raises_on_malformed_json(self):
        client = fake_client(text="not json")

        with self.assertRaises(InterpretationError):
            interpret(INDICATORS_CONTEXT, UPDATED_KEYS, client=client)

    def test_raises_on_invalid_directional_read(self):
        text = json.dumps({"summary": "ok", "directional_read": "up"})
        client = fake_client(text=text)

        with self.assertRaises(InterpretationError):
            interpret(INDICATORS_CONTEXT, UPDATED_KEYS, client=client)

    def test_raises_on_missing_summary(self):
        text = json.dumps({"directional_read": "neutral"})
        client = fake_client(text=text)

        with self.assertRaises(InterpretationError):
            interpret(INDICATORS_CONTEXT, UPDATED_KEYS, client=client)

    def test_raises_on_empty_response_text(self):
        client = fake_client(text=None)

        with self.assertRaises(InterpretationError):
            interpret(INDICATORS_CONTEXT, UPDATED_KEYS, client=client)

    def test_raises_when_no_credentials_configured(self):
        # genai.Client() raises a bare ValueError (not an APIError) when no
        # API key is configured - confirmed against the real SDK.
        with patch(
            "interpret.genai.Client",
            side_effect=ValueError("No API key was provided."),
        ):
            with self.assertRaises(InterpretationError):
                interpret(INDICATORS_CONTEXT, UPDATED_KEYS, client=None)


if __name__ == "__main__":
    unittest.main()
