import json
from datetime import date, timedelta
import os
import sys
import unittest
from types import SimpleNamespace
from unittest.mock import Mock, patch

_SRC = os.path.join(os.path.dirname(__file__), "..", "src")
for _p in (
    _SRC,
    os.path.join(_SRC, "fred"),
    os.path.join(_SRC, "storage"),
    os.path.join(_SRC, "digest"),
    os.path.join(_SRC, "mailer"),
    os.path.join(_SRC, "web"),
):
    sys.path.insert(0, _p)

from google.genai import errors
from gemini_models import DEFAULT_FALLBACK_MODELS
from interpret import MAX_PROMPT_READINGS, MODEL, InterpretationError, build_user_prompt, interpret

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


def daily_context(days):
    start = date(2025, 9, 25)
    window = [
        {"date": (start + timedelta(days=i)).isoformat(), "value": float(i)} for i in range(days)
    ]
    return [{"key": "yield_curve_spread", "name": "Spread", "category": "leading",
             "history_window": window, "heuristic": None}]


class TestPromptSampling(unittest.TestCase):
    def test_short_series_are_sent_in_full(self):
        prompt = build_user_prompt(daily_context(MAX_PROMPT_READINGS), [])

        self.assertEqual(prompt.count("\n- "), MAX_PROMPT_READINGS)

    def test_a_year_of_daily_readings_is_sampled_to_one_per_week(self):
        prompt = build_user_prompt(daily_context(365), [])

        readings = prompt.count("\n- ")
        self.assertLessEqual(readings, 54)
        self.assertGreaterEqual(readings, 52)

    def test_sampling_keeps_the_latest_reading_and_the_order(self):
        prompt = build_user_prompt(daily_context(365), [])

        lines = [l for l in prompt.split("\n") if l.startswith("- ")]
        self.assertTrue(lines[-1].endswith(": 364.0"))
        self.assertEqual(lines, sorted(lines))


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


class TestGeminiModelFallbackChain(unittest.TestCase):
    def called_models(self, client):
        return [c.kwargs["model"] for c in client.models.generate_content.call_args_list]

    def test_each_fallback_model_is_tried_in_order_until_one_succeeds(self):
        client = Mock()
        client.models.generate_content.side_effect = [
            make_api_error(),
            make_api_error(),
            make_api_error(),
            SimpleNamespace(text=json.dumps({"summary": "ok", "directional_read": "bullish"})),
        ]
        with patch("interpret.genai.Client", return_value=client):
            interpret(INDICATORS_CONTEXT, UPDATED_KEYS)
        self.assertEqual(self.called_models(client), [MODEL, *DEFAULT_FALLBACK_MODELS[:3]])

    def test_later_models_are_not_called_once_one_succeeds(self):
        client = fake_client(text=json.dumps({"summary": "ok", "directional_read": "bullish"}))
        with patch("interpret.genai.Client", return_value=client):
            interpret(INDICATORS_CONTEXT, UPDATED_KEYS)
        client.models.generate_content.assert_called_once()

    def test_injected_client_never_falls_back(self):
        client = fake_client(side_effect=make_api_error())
        with self.assertRaises(InterpretationError):
            interpret(INDICATORS_CONTEXT, UPDATED_KEYS, client=client)
        client.models.generate_content.assert_called_once()

    def test_raises_after_trying_every_model_and_names_each_in_the_error(self):
        client = fake_client(side_effect=make_api_error())
        with patch("interpret.genai.Client", return_value=client):
            with self.assertRaises(InterpretationError) as raised:
                interpret(INDICATORS_CONTEXT, UPDATED_KEYS)
        self.assertEqual(self.called_models(client), [MODEL, *DEFAULT_FALLBACK_MODELS])
        for model in (MODEL, *DEFAULT_FALLBACK_MODELS):
            self.assertIn(model, str(raised.exception))

    @patch.dict(os.environ, {"GEMINI_FALLBACK_MODELS": "model-a, model-b"})
    def test_fallback_models_are_configurable(self):
        client = fake_client(side_effect=make_api_error())
        with patch("interpret.genai.Client", return_value=client):
            with self.assertRaises(InterpretationError):
                interpret(INDICATORS_CONTEXT, UPDATED_KEYS)
        self.assertEqual(self.called_models(client), [MODEL, "model-a", "model-b"])


if __name__ == "__main__":
    unittest.main()
