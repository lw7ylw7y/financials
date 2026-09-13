import os
import sys
import unittest
from datetime import datetime, timezone

_SRC = os.path.join(os.path.dirname(__file__), "..", "src")
for _p in (
    _SRC,
    os.path.join(_SRC, "fred"),
    os.path.join(_SRC, "storage"),
    os.path.join(_SRC, "digest"),
    os.path.join(_SRC, "mailer"),
):
    sys.path.insert(0, _p)

from build_digest_content import build_digest_content
from interpret import InterpretationError

T0 = "2026-09-01T00:00:00+00:00"
NOW = datetime(2026, 9, 12, 18, 0, 0, tzinfo=timezone.utc)


def make_state(last_ai_response=None):
    state = {
        "indicators": {
            "cpi": {
                "name": "CPI",
                "category": "lagging",
                "history": [{"date": "2026-08-01", "value": 334.131, "fetched_at": T0}],
                "next_release_date": "2026-09-11",
            },
        }
    }
    if last_ai_response is not None:
        state["last_ai_response"] = last_ai_response
    return state


def fake_interpret_factory(succeed=True):
    def fake_interpret(indicators_context, updated_keys):
        if not succeed:
            raise InterpretationError("simulated AI failure")
        return {"summary": "CPI cooled slightly.", "directional_read": "neutral"}

    return fake_interpret


class TestBuildDigestContent(unittest.TestCase):
    def test_returns_table_countdown_and_ai_result(self):
        state = make_state()

        content = build_digest_content(
            state, ["cpi"], interpret_fn=fake_interpret_factory(), now=NOW
        )

        self.assertIn("lagging", content["table"])
        self.assertEqual(content["countdown"]["entries"][0]["key"], "cpi")
        self.assertEqual(content["ai_result"]["directional_read"], "neutral")
        self.assertEqual(content["table"]["lagging"][0]["sparkline_values"], [334.131])

    def test_successful_ai_call_persists_last_ai_response(self):
        state = make_state()

        build_digest_content(state, ["cpi"], interpret_fn=fake_interpret_factory(), now=NOW)

        self.assertEqual(
            state["last_ai_response"],
            {
                "summary": "CPI cooled slightly.",
                "directional_read": "neutral",
                "generated_at": NOW.isoformat(),
            },
        )

    def test_failed_ai_call_leaves_last_ai_response_untouched(self):
        previous = {
            "summary": "Old read.",
            "directional_read": "bullish",
            "generated_at": T0,
        }
        state = make_state(last_ai_response=previous)

        content = build_digest_content(
            state, ["cpi"], interpret_fn=fake_interpret_factory(succeed=False), now=NOW
        )

        self.assertIsNone(content["ai_result"])
        self.assertEqual(state["last_ai_response"], previous)

    def test_no_prior_ai_response_and_failed_call_leaves_it_absent(self):
        state = make_state()

        build_digest_content(
            state, ["cpi"], interpret_fn=fake_interpret_factory(succeed=False), now=NOW
        )

        self.assertNotIn("last_ai_response", state)


if __name__ == "__main__":
    unittest.main()
