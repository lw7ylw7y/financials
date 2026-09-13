import os
import sys
import time
import unittest

_SRC = os.path.join(os.path.dirname(__file__), "..", "src")
for _p in (
    _SRC,
    os.path.join(_SRC, "fred"),
    os.path.join(_SRC, "storage"),
    os.path.join(_SRC, "digest"),
    os.path.join(_SRC, "mailer"),
):
    sys.path.insert(0, _p)

from fetch_fred import FredApiError
from main import update_release_calendar


def fake_fetch_factory(responses, default="2026-12-01"):
    def fake_fetch(release_id):
        response = responses.get(release_id, default)
        if isinstance(response, Exception):
            raise response
        return response

    return fake_fetch


class TestUpdateReleaseCalendar(unittest.TestCase):
    def test_stores_next_release_date_for_indicator_with_release_id(self):
        fetch_fn = fake_fetch_factory({"180": "2026-09-11"})
        state = {
            "indicators": {
                "initial_jobless_claims": {
                    "name": "Initial Jobless Claims",
                    "category": "leading",
                    "fred_series_id": "ICSA",
                    "fred_release_id": "180",
                    "history": [],
                    "next_release_date": None,
                }
            }
        }

        results = update_release_calendar(state, fetch_fn=fetch_fn)

        self.assertEqual(results["initial_jobless_claims"]["status"], "updated")
        self.assertEqual(
            state["indicators"]["initial_jobless_claims"]["next_release_date"],
            "2026-09-11",
        )

    def test_indicator_with_null_release_id_is_skipped_without_error(self):
        fetch_fn = fake_fetch_factory({})
        state = {
            "indicators": {
                "yield_curve_spread": {
                    "name": "10yr-2yr Treasury Spread",
                    "category": "leading",
                    "fred_series_id": "T10Y2Y",
                    "fred_release_id": None,
                    "history": [],
                    "next_release_date": None,
                }
            }
        }

        results = update_release_calendar(state, fetch_fn=fetch_fn)

        self.assertNotIn("yield_curve_spread", results)
        self.assertIsNone(
            state["indicators"]["yield_curve_spread"]["next_release_date"]
        )

    def test_stale_next_release_date_is_cleared_when_config_drops_release_id(self):
        # Simulates fed_funds_rate: it used to have a fred_release_id and
        # a stored next_release_date, but the config no longer maps it to
        # one (its release didn't reflect its own update cadence) - the
        # stale value must not linger forever.
        state = {
            "indicators": {
                "fed_funds_rate": {
                    "name": "Fed Funds Rate",
                    "category": "lagging",
                    "fred_series_id": "FEDFUNDS",
                    "fred_release_id": "18",
                    "history": [],
                    "next_release_date": "2026-09-11",
                }
            }
        }

        update_release_calendar(state, fetch_fn=fake_fetch_factory({}))

        self.assertIsNone(state["indicators"]["fed_funds_rate"]["next_release_date"])

    def test_changed_date_on_refresh_overwrites_not_duplicates(self):
        state = {
            "indicators": {
                "initial_jobless_claims": {
                    "name": "Initial Jobless Claims",
                    "category": "leading",
                    "fred_series_id": "ICSA",
                    "fred_release_id": "180",
                    "history": [],
                    "next_release_date": "2026-09-04",
                }
            }
        }

        fetch_fn = fake_fetch_factory({"180": "2026-09-11"})
        update_release_calendar(state, fetch_fn=fetch_fn)

        indicator = state["indicators"]["initial_jobless_claims"]
        self.assertEqual(indicator["next_release_date"], "2026-09-11")
        # A single scalar field, not a list — nothing to deduplicate,
        # just confirming the old value is gone, not retained anywhere.
        self.assertNotIn("release_date_history", indicator)

    def test_one_indicator_failure_does_not_block_others(self):
        fetch_fn = fake_fetch_factory(
            {
                "180": FredApiError("simulated outage"),
                "50": "2026-10-02",
            }
        )
        state = {
            "indicators": {
                "initial_jobless_claims": {
                    "name": "Initial Jobless Claims",
                    "category": "leading",
                    "fred_series_id": "ICSA",
                    "fred_release_id": "180",
                    "history": [],
                    "next_release_date": None,
                },
                "unemployment_rate": {
                    "name": "Unemployment Rate",
                    "category": "lagging",
                    "fred_series_id": "UNRATE",
                    "fred_release_id": "50",
                    "history": [],
                    "next_release_date": None,
                },
            }
        }

        results = update_release_calendar(state, fetch_fn=fetch_fn)

        self.assertEqual(results["initial_jobless_claims"]["status"], "error")
        self.assertEqual(results["unemployment_rate"]["status"], "updated")
        self.assertEqual(
            state["indicators"]["unemployment_rate"]["next_release_date"],
            "2026-10-02",
        )

    def test_fetches_run_concurrently_not_sequentially(self):
        # 6 indicators have a release_id; each fetch sleeps 0.1s.
        # Sequential would take >=0.6s, concurrent should be close to 0.1s.
        def slow_fetch(release_id):
            time.sleep(0.1)
            return "2026-12-01"

        state = {
            "indicators": {
                key: {
                    "name": key,
                    "category": "leading",
                    "fred_series_id": key.upper(),
                    "fred_release_id": str(i),
                    "history": [],
                    "next_release_date": None,
                }
                for i, key in enumerate(["a", "b", "c", "d", "e", "f"])
            }
        }

        started = time.monotonic()
        update_release_calendar(state, fetch_fn=slow_fetch)
        elapsed = time.monotonic() - started

        self.assertLess(elapsed, 0.4)


if __name__ == "__main__":
    unittest.main()
