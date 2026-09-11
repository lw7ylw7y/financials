import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from interpret import InterpretationError
from post_release import build_diff, run_post_release
from send_email import EmailSendError


def make_state():
    return {
        "indicators": {
            "nonfarm_payrolls": {
                "name": "Nonfarm Payrolls",
                "category": "coincident",
                "history": [
                    {"date": "2026-07-01", "value": 158000.0},
                    {"date": "2026-08-01", "value": 159075.0},
                ],
            },
            "cpi": {
                "name": "CPI",
                "category": "lagging",
                "history": [
                    {"date": "2026-07-01", "value": 314.5},
                ],
            },
            "unemployment_rate": {
                "name": "Unemployment Rate",
                "category": "lagging",
                "history": [{"date": "2026-08-01", "value": 4.1}],
            },
        }
    }


def fake_send_factory(calls, fail_for=()):
    def fake_send(subject, body):
        calls.append({"subject": subject, "body": body})
        if subject in fail_for:
            raise EmailSendError("simulated smtp failure")

    return fake_send


def fake_interpret_factory(succeed=True):
    def fake_interpret(indicator, history_window, heuristic=None):
        if not succeed:
            raise InterpretationError("simulated AI failure")
        return {"summary": "Modest change.", "directional_read": "neutral"}

    return fake_interpret


class TestBuildDiff(unittest.TestCase):
    def test_computes_absolute_and_percent_change(self):
        history = [
            {"date": "2026-07-01", "value": 158000.0},
            {"date": "2026-08-01", "value": 159075.0},
        ]

        diff = build_diff(history)

        self.assertEqual(diff["new_value"], 159075.0)
        self.assertEqual(diff["prior_value"], 158000.0)
        self.assertEqual(diff["absolute_change"], 1075.0)
        self.assertAlmostEqual(diff["percent_change"], 0.680379746835443)

    def test_first_ever_reading_has_no_prior(self):
        diff = build_diff([{"date": "2026-07-01", "value": 314.5}])

        self.assertIsNone(diff["prior_value"])
        self.assertIsNone(diff["absolute_change"])
        self.assertIsNone(diff["percent_change"])


class TestRunPostRelease(unittest.TestCase):
    def test_unchanged_indicator_is_not_notified(self):
        state = make_state()
        results = {"nonfarm_payrolls": {"status": "unchanged"}}
        calls = []

        outcomes = run_post_release(
            state,
            results,
            send_fn=fake_send_factory(calls),
            interpret_fn=fake_interpret_factory(),
        )

        self.assertEqual(outcomes, {})
        self.assertEqual(calls, [])

    def test_updated_indicator_triggers_email_with_ai_content(self):
        state = make_state()
        results = {"nonfarm_payrolls": {"status": "updated"}}
        calls = []

        outcomes = run_post_release(
            state,
            results,
            send_fn=fake_send_factory(calls),
            interpret_fn=fake_interpret_factory(succeed=True),
        )

        self.assertEqual(outcomes["nonfarm_payrolls"]["status"], "sent")
        self.assertEqual(len(calls), 1)
        body = calls[0]["body"]
        self.assertIn("Modest change.", body)
        self.assertIn("Directional read: neutral", body)
        self.assertIn(
            "This is automated commentary based on indicator trends, "
            "not personalized financial advice.",
            body,
        )

    def test_ai_failure_degrades_to_raw_data_only_email(self):
        state = make_state()
        results = {"nonfarm_payrolls": {"status": "updated"}}
        calls = []

        outcomes = run_post_release(
            state,
            results,
            send_fn=fake_send_factory(calls),
            interpret_fn=fake_interpret_factory(succeed=False),
        )

        self.assertEqual(outcomes["nonfarm_payrolls"]["status"], "sent_without_ai")
        self.assertEqual(len(calls), 1)
        body = calls[0]["body"]
        self.assertIn("New value: 159075", body)
        self.assertIn("Prior value: 158000", body)
        self.assertNotIn("Directional read", body)
        self.assertNotIn("not personalized financial advice", body)

    def test_email_send_failure_for_one_indicator_does_not_block_others(self):
        state = make_state()
        results = {
            "nonfarm_payrolls": {"status": "updated"},
            "cpi": {"status": "updated"},
        }
        calls = []
        failing_subject = "[Indicator Update] Nonfarm Payrolls: 159075 (+1075)"

        outcomes = run_post_release(
            state,
            results,
            send_fn=fake_send_factory(calls, fail_for={failing_subject}),
            interpret_fn=fake_interpret_factory(succeed=True),
        )

        self.assertEqual(outcomes["nonfarm_payrolls"]["status"], "error")
        self.assertEqual(outcomes["cpi"]["status"], "sent")
        self.assertEqual(len(calls), 2)


if __name__ == "__main__":
    unittest.main()
