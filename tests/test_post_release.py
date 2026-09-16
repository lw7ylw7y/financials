import os
import sys
import unittest
from datetime import date, datetime, timedelta, timezone

_SRC = os.path.join(os.path.dirname(__file__), "..", "src")
for _p in (
    _SRC,
    os.path.join(_SRC, "fred"),
    os.path.join(_SRC, "storage"),
    os.path.join(_SRC, "digest"),
    os.path.join(_SRC, "mailer"),
):
    sys.path.insert(0, _p)

from interpret import InterpretationError
from post_release import (
    build_countdown,
    build_digest_email,
    build_indicators_context,
    build_sparkline_images,
    build_table,
    indicators_updated_since,
    maybe_send_digest_email,
    refresh_ai_response_if_updated,
)
from send_email import EmailSendError

PNG_MAGIC = b"\x89PNG\r\n\x1a\n"

T0 = "2026-09-01T00:00:00+00:00"
T1 = "2026-09-08T00:00:00+00:00"


def make_state():
    return {
        "indicators": {
            "nonfarm_payrolls": {
                "name": "Nonfarm Payrolls",
                "category": "coincident",
                "history": [
                    {"date": "2026-07-01", "value": 158000.0, "fetched_at": T0},
                    {"date": "2026-08-01", "value": 159075.0, "fetched_at": T0},
                ],
                "next_release_date": "2026-10-02",
            },
            "cpi": {
                "name": "CPI",
                "category": "lagging",
                "history": [{"date": "2026-08-01", "value": 334.131, "fetched_at": T0}],
                "next_release_date": "2026-09-11",
            },
            "yield_curve_spread": {
                "name": "10yr-2yr Treasury Spread",
                "category": "leading",
                "history": [{"date": "2026-09-10", "value": 0.39, "fetched_at": T0}],
                "next_release_date": None,
            },
        }
    }


def fake_send_factory(calls, fail=False):
    def fake_send(subject, body, html_body=None, images=None):
        calls.append(
            {"subject": subject, "body": body, "html_body": html_body, "images": images}
        )
        if fail:
            raise EmailSendError("simulated smtp failure")

    return fake_send


def fake_interpret_factory(succeed=True):
    def fake_interpret(indicators_context, updated_keys):
        if not succeed:
            raise InterpretationError("simulated AI failure")
        return {"summary": "Modest changes across the board.", "directional_read": "neutral"}

    return fake_interpret


class TestBuildIndicatorsContext(unittest.TestCase):
    def test_includes_every_indicator_with_history(self):
        state = make_state()

        context = build_indicators_context(state)

        keys = {c["key"] for c in context}
        self.assertEqual(keys, {"nonfarm_payrolls", "cpi", "yield_curve_spread"})

    def test_skips_indicators_with_no_history(self):
        state = make_state()
        state["indicators"]["building_permits"] = {
            "name": "Building Permits",
            "category": "leading",
            "history": [],
            "next_release_date": None,
        }

        context = build_indicators_context(state)

        keys = {c["key"] for c in context}
        self.assertNotIn("building_permits", keys)


class TestBuildTable(unittest.TestCase):
    def test_groups_by_category_with_latest_and_prior(self):
        context = build_indicators_context(make_state())

        table = build_table(context)

        self.assertEqual(len(table["coincident"]), 1)
        row = table["coincident"][0]
        self.assertEqual(row["latest_value"], 159075.0)
        self.assertEqual(row["prior_value"], 158000.0)

    def test_prior_value_is_none_for_single_reading(self):
        context = build_indicators_context(make_state())

        table = build_table(context)

        cpi_row = table["lagging"][0]
        self.assertIsNone(cpi_row["prior_value"])

    def test_each_row_gets_a_sparkline_cid(self):
        context = build_indicators_context(make_state())

        table = build_table(context)

        row = table["coincident"][0]
        self.assertEqual(row["sparkline_cid"], "spark-nonfarm_payrolls")


class TestBuildSparklineImages(unittest.TestCase):
    def test_returns_one_png_per_indicator_keyed_by_cid(self):
        context = build_indicators_context(make_state())

        images = build_sparkline_images(context)

        self.assertEqual(
            set(images.keys()),
            {"spark-nonfarm_payrolls", "spark-cpi", "spark-yield_curve_spread"},
        )
        for png in images.values():
            self.assertTrue(png.startswith(PNG_MAGIC))


class TestBuildCountdown(unittest.TestCase):
    def test_days_until_is_correct_for_known_date(self):
        state = make_state()

        countdown = build_countdown(state, today=date(2026, 9, 8))

        cpi_entry = next(e for e in countdown["entries"] if e["key"] == "cpi")
        self.assertEqual(cpi_entry["days_until"], 3)

    def test_excludes_indicators_with_no_next_release_date(self):
        state = make_state()

        countdown = build_countdown(state, today=date(2026, 9, 8))

        keys = {e["key"] for e in countdown["entries"]}
        self.assertNotIn("yield_curve_spread", keys)

    def test_soonest_is_correctly_identified(self):
        state = make_state()

        countdown = build_countdown(state, today=date(2026, 9, 8))

        self.assertEqual(countdown["soonest"]["key"], "cpi")


class TestBuildDigestEmail(unittest.TestCase):
    def test_includes_ai_content_and_disclaimer_when_present(self):
        state = make_state()
        context = build_indicators_context(state)
        ai_result = {"summary": "Test summary.", "directional_read": "bullish"}

        email = build_digest_email(state, context, ["cpi"], ai_result)

        self.assertIn("Test summary.", email["body"])
        self.assertIn("Overall directional read: bullish", email["body"])
        self.assertIn("not personalized financial advice", email["body"])

    def test_omits_ai_section_when_none(self):
        state = make_state()
        context = build_indicators_context(state)

        email = build_digest_email(state, context, ["cpi"], None)

        self.assertNotIn("Overall directional read", email["body"])
        self.assertNotIn("not personalized financial advice", email["body"])

    def test_body_includes_full_table_regardless_of_what_updated(self):
        state = make_state()
        context = build_indicators_context(state)

        email = build_digest_email(state, context, ["cpi"], None)

        self.assertIn("Nonfarm Payrolls", email["body"])
        self.assertIn("CPI", email["body"])
        self.assertIn("10yr-2yr Treasury Spread", email["body"])

    def test_html_body_is_present_and_well_formed(self):
        state = make_state()
        context = build_indicators_context(state)
        ai_result = {"summary": "Test summary.", "directional_read": "bullish"}

        email = build_digest_email(state, context, ["cpi"], ai_result)

        self.assertIn("<!doctype html>", email["html_body"].lower())
        self.assertIn("Test summary.", email["html_body"])
        self.assertIn("Nonfarm Payrolls", email["html_body"])
        self.assertIn("CPI", email["html_body"])

    def test_subject_names_updated_indicators(self):
        state = make_state()
        context = build_indicators_context(state)

        email = build_digest_email(state, context, ["cpi", "nonfarm_payrolls"], None)

        self.assertIn("2 update(s)", email["subject"])
        self.assertIn("CPI", email["subject"])
        self.assertIn("Nonfarm Payrolls", email["subject"])


class TestIndicatorsUpdatedSince(unittest.TestCase):
    def test_none_since_treats_every_indicator_with_history_as_updated(self):
        state = make_state()

        updated = indicators_updated_since(state, None)

        self.assertEqual(set(updated), {"nonfarm_payrolls", "cpi", "yield_curve_spread"})

    def test_only_entries_fetched_after_since_count(self):
        state = make_state()
        state["indicators"]["cpi"]["history"][-1]["fetched_at"] = T1

        updated = indicators_updated_since(state, T0)

        self.assertEqual(updated, ["cpi"])

    def test_indicator_with_no_history_is_excluded(self):
        state = make_state()
        state["indicators"]["building_permits"] = {
            "name": "Building Permits",
            "category": "leading",
            "history": [],
        }

        updated = indicators_updated_since(state, None)

        self.assertNotIn("building_permits", updated)


class TestRefreshAiResponseIfUpdated(unittest.TestCase):
    """Story 11: the AI response refreshes every run that found new
    data, independent of the email's own weekly throttle."""

    def test_returns_none_and_leaves_state_untouched_when_nothing_updated(self):
        state = make_state()

        content = refresh_ai_response_if_updated(state, [], interpret_fn=fake_interpret_factory())

        self.assertIsNone(content)
        self.assertNotIn("last_ai_response", state)

    def test_persists_ai_response_when_something_updated(self):
        state = make_state()

        content = refresh_ai_response_if_updated(
            state, ["cpi"], interpret_fn=fake_interpret_factory()
        )

        self.assertIsNotNone(content)
        self.assertEqual(state["last_ai_response"]["directional_read"], "neutral")

    def test_ai_failure_degrades_but_still_returns_content(self):
        state = make_state()

        content = refresh_ai_response_if_updated(
            state, ["cpi"], interpret_fn=fake_interpret_factory(succeed=False)
        )

        self.assertIsNotNone(content)
        self.assertIsNone(content["ai_result"])
        self.assertNotIn("last_ai_response", state)

    def test_refreshes_regardless_of_the_email_throttle_state(self):
        # No 7-day gate on this part -- that's the whole point of Story
        # 11 decoupling it from the email.
        state = make_state()
        state["last_digest_sent_at"] = T1  # "recently" sent

        content = refresh_ai_response_if_updated(
            state, ["cpi"], interpret_fn=fake_interpret_factory()
        )

        self.assertIsNotNone(content)
        self.assertIn("last_ai_response", state)


STALE_FINGERPRINT = "stale-fingerprint-from-a-previous-run"


class TestMaybeSendDigestEmail(unittest.TestCase):
    """Story 11: the email send-gate is a content fingerprint of the
    *current* persisted state plus the minimum interval -- no longer
    coupled to whether the AI response was just refreshed this cycle."""

    def test_first_ever_digest_sends_immediately_with_no_prior_state(self):
        state = make_state()
        refresh_ai_response_if_updated(
            state,
            ["nonfarm_payrolls", "cpi", "yield_curve_spread"],
            interpret_fn=fake_interpret_factory(),
        )
        calls = []

        outcome = maybe_send_digest_email(state, send_fn=fake_send_factory(calls))

        self.assertEqual(outcome["status"], "sent")
        self.assertEqual(len(calls), 1)
        self.assertIn("last_digest_sent_at", state)
        self.assertIn("last_digest_content_fingerprint", state)
        self.assertEqual(
            set(calls[0]["images"].keys()),
            {"spark-nonfarm_payrolls", "spark-cpi", "spark-yield_curve_spread"},
        )

    def test_unchanged_content_sends_no_email_even_once_the_interval_has_passed(self):
        state = make_state()
        refresh_ai_response_if_updated(state, ["cpi"], interpret_fn=fake_interpret_factory())
        now = datetime.fromisoformat(T0) + timedelta(days=7)
        first_calls = []
        maybe_send_digest_email(state, send_fn=fake_send_factory(first_calls), now=now)
        self.assertEqual(len(first_calls), 1)  # sanity: the first send actually happened

        # Nothing about state changes between cycles; another 7 days pass.
        second_calls = []
        outcome = maybe_send_digest_email(
            state, send_fn=fake_send_factory(second_calls), now=now + timedelta(days=7)
        )

        self.assertEqual(outcome["status"], "skipped")
        self.assertEqual(outcome["reason"], "content unchanged since last digest")
        self.assertEqual(second_calls, [])

    def test_changed_content_within_a_week_of_last_digest_is_held_back(self):
        state = make_state()
        state["last_digest_sent_at"] = T0
        state["last_digest_content_fingerprint"] = STALE_FINGERPRINT
        state["indicators"]["cpi"]["history"][-1]["fetched_at"] = T1
        calls = []

        outcome = maybe_send_digest_email(
            state,
            send_fn=fake_send_factory(calls),
            now=datetime.fromisoformat(T0) + timedelta(days=3),
        )

        self.assertEqual(outcome["status"], "skipped")
        self.assertEqual(outcome["reason"], "last digest sent too recently")
        self.assertEqual(calls, [])

    def test_changed_content_at_or_after_a_week_since_last_digest_sends(self):
        state = make_state()
        state["last_digest_sent_at"] = T0
        state["last_digest_content_fingerprint"] = STALE_FINGERPRINT
        state["indicators"]["cpi"]["history"][-1]["fetched_at"] = T1
        refresh_ai_response_if_updated(state, ["cpi"], interpret_fn=fake_interpret_factory())
        calls = []

        outcome = maybe_send_digest_email(
            state,
            send_fn=fake_send_factory(calls),
            now=datetime.fromisoformat(T0) + timedelta(days=7),
        )

        self.assertEqual(outcome["status"], "sent")
        self.assertEqual(len(calls), 1)

    def test_update_that_happened_several_ticks_ago_is_still_named_in_the_subject(self):
        # cpi updated right after the last digest (T0), long before the
        # 7-day gate opens - it must still show up in the eventual digest's
        # subject, not be silently dropped for not having "just" updated.
        state = make_state()
        state["last_digest_sent_at"] = T0
        state["last_digest_content_fingerprint"] = STALE_FINGERPRINT
        state["indicators"]["cpi"]["history"][-1]["fetched_at"] = (
            datetime.fromisoformat(T0) + timedelta(hours=6)
        ).isoformat()
        calls = []

        maybe_send_digest_email(
            state,
            send_fn=fake_send_factory(calls),
            now=datetime.fromisoformat(T0) + timedelta(days=7),
        )

        self.assertIn("CPI", calls[0]["subject"])

    def test_sending_updates_last_digest_sent_at_and_fingerprint(self):
        state = make_state()
        now = datetime.fromisoformat(T0) + timedelta(days=7)

        maybe_send_digest_email(state, send_fn=fake_send_factory([]), now=now)

        self.assertEqual(state["last_digest_sent_at"], now.isoformat())
        self.assertIn("last_digest_content_fingerprint", state)

    def test_uses_whatever_ai_response_is_currently_persisted_not_a_fresh_call(self):
        # maybe_send_digest_email has no interpret_fn parameter at all --
        # it can't call Gemini even if it wanted to, only reuse whatever
        # refresh_ai_response_if_updated already persisted this or a
        # prior cycle.
        state = make_state()
        refresh_ai_response_if_updated(state, ["cpi"], interpret_fn=fake_interpret_factory())
        calls = []

        maybe_send_digest_email(state, send_fn=fake_send_factory(calls))

        self.assertIn("Modest changes across the board.", calls[0]["body"])

    def test_no_ai_response_persisted_sends_without_ai(self):
        state = make_state()
        # refresh_ai_response_if_updated never ran this history -- no
        # last_ai_response to fall back on.
        calls = []

        outcome = maybe_send_digest_email(state, send_fn=fake_send_factory(calls))

        self.assertEqual(outcome["status"], "sent_without_ai")
        self.assertEqual(len(calls), 1)
        body = calls[0]["body"]
        self.assertIn("CPI", body)
        self.assertNotIn("Overall directional read", body)

    def test_send_failure_is_reported_as_error_and_does_not_update_state(self):
        state = make_state()
        refresh_ai_response_if_updated(state, ["cpi"], interpret_fn=fake_interpret_factory())
        calls = []

        outcome = maybe_send_digest_email(state, send_fn=fake_send_factory(calls, fail=True))

        self.assertEqual(outcome["status"], "error")
        self.assertNotIn("last_digest_sent_at", state)


if __name__ == "__main__":
    unittest.main()
