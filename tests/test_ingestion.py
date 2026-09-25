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
from main import run_ingestion

FIXTURES = {
    "ICSA": {"date": "2026-09-04", "value": 235000.0},
    "T10Y2Y": {"date": "2026-09-04", "value": 0.3},
    "PERMIT": {"date": "2026-08-01", "value": 1400.0},
    "PAYEMS": {"date": "2026-08-01", "value": 158000.0},
    "INDPRO": {"date": "2026-08-01", "value": 103.2},
    "DFF": {"date": "2026-08-01", "value": 5.25},
    "CPIAUCSL": {"date": "2026-08-01", "value": 314.5},
    "UNRATE": {"date": "2026-08-01", "value": 4.1},
}


def fake_fetch_factory(responses):
    def fake_fetch(series_id):
        response = responses[series_id]
        if isinstance(response, Exception):
            raise response
        return response

    return fake_fetch


class TestRunIngestion(unittest.TestCase):
    def test_a_changed_series_discards_the_old_series_history(self):
        state = {
            "indicators": {
                "fed_funds_rate": {
                    "name": "Fed Funds Rate",
                    "category": "lagging",
                    "fred_series_id": "FEDFUNDS",
                    "fred_release_id": None,
                    "history": [{"date": "2026-08-01", "value": 3.63, "fetched_at": "t"}],
                    "next_release_date": None,
                }
            }
        }
        responses = dict(FIXTURES)
        responses["DFF"] = {"date": "2026-09-24", "value": 3.88}

        run_ingestion(state, fetch_fn=fake_fetch_factory(responses))

        entry = state["indicators"]["fed_funds_rate"]
        self.assertEqual(entry["fred_series_id"], "DFF")
        self.assertEqual([e["value"] for e in entry["history"]], [3.88])

    def test_a_missing_stored_series_id_keeps_existing_history(self):
        state = {
            "indicators": {
                "fed_funds_rate": {
                    "name": "Fed Funds Rate",
                    "category": "lagging",
                    "history": [{"date": "2026-08-01", "value": 3.63, "fetched_at": "t"}],
                    "next_release_date": None,
                }
            }
        }
        responses = dict(FIXTURES)
        responses["DFF"] = {"date": "2026-09-24", "value": 3.88}

        run_ingestion(state, fetch_fn=fake_fetch_factory(responses))

        history = state["indicators"]["fed_funds_rate"]["history"]
        self.assertEqual([e["value"] for e in history], [3.63, 3.88])

    def test_all_eight_indicators_processed_and_tagged(self):
        fetch_fn = fake_fetch_factory(FIXTURES)
        state = {"indicators": {}}

        results = run_ingestion(state, fetch_fn=fetch_fn)

        self.assertEqual(len(results), 8)
        self.assertEqual(results["initial_jobless_claims"]["category"], "leading")
        self.assertEqual(results["nonfarm_payrolls"]["category"], "coincident")
        self.assertEqual(results["fed_funds_rate"]["category"], "lagging")
        self.assertTrue(all(r["status"] == "updated" for r in results.values()))

    def test_one_indicator_failure_does_not_block_others(self):
        responses = dict(FIXTURES)
        responses["ICSA"] = FredApiError("simulated outage")
        fetch_fn = fake_fetch_factory(responses)
        state = {"indicators": {}}

        results = run_ingestion(state, fetch_fn=fetch_fn)

        self.assertEqual(results["initial_jobless_claims"]["status"], "error")
        self.assertIn("simulated outage", results["initial_jobless_claims"]["error"])
        other_statuses = [
            r["status"] for k, r in results.items() if k != "initial_jobless_claims"
        ]
        self.assertTrue(all(status == "updated" for status in other_statuses))

    def test_unchanged_value_is_not_reprocessed(self):
        state = {
            "indicators": {
                "initial_jobless_claims": {
                    "name": "Initial Jobless Claims",
                    "category": "leading",
                    "history": [
                        {
                            "date": "2026-09-04",
                            "value": 235000.0,
                            "fetched_at": "2026-09-04T12:00:00Z",
                        }
                    ],
                }
            }
        }
        fetch_fn = fake_fetch_factory(FIXTURES)

        results = run_ingestion(state, fetch_fn=fetch_fn)

        self.assertEqual(results["initial_jobless_claims"]["status"], "unchanged")
        self.assertEqual(
            len(state["indicators"]["initial_jobless_claims"]["history"]), 1
        )

    def test_older_date_than_stored_is_ignored_not_appended(self):
        # Simulates a stale/cached FRED response returning an older
        # observation than what's already on file.
        responses = dict(FIXTURES)
        responses["ICSA"] = {"date": "2026-08-28", "value": 220000.0}
        state = {
            "indicators": {
                "initial_jobless_claims": {
                    "name": "Initial Jobless Claims",
                    "category": "leading",
                    "history": [
                        {
                            "date": "2026-09-04",
                            "value": 235000.0,
                            "fetched_at": "2026-09-04T12:00:00Z",
                        }
                    ],
                }
            }
        }
        fetch_fn = fake_fetch_factory(responses)

        results = run_ingestion(state, fetch_fn=fetch_fn)

        self.assertEqual(results["initial_jobless_claims"]["status"], "unchanged")
        history = state["indicators"]["initial_jobless_claims"]["history"]
        self.assertEqual(len(history), 1)
        self.assertEqual(history[0]["date"], "2026-09-04")

    def test_same_date_different_value_is_ignored_not_appended(self):
        # A same-date revision must not create a second entry for that
        # date — Story 2 requires history is never overwritten, and this
        # keeps at most one record per release date.
        responses = dict(FIXTURES)
        responses["ICSA"] = {"date": "2026-09-04", "value": 236000.0}
        state = {
            "indicators": {
                "initial_jobless_claims": {
                    "name": "Initial Jobless Claims",
                    "category": "leading",
                    "history": [
                        {
                            "date": "2026-09-04",
                            "value": 235000.0,
                            "fetched_at": "2026-09-04T12:00:00Z",
                        }
                    ],
                }
            }
        }
        fetch_fn = fake_fetch_factory(responses)

        results = run_ingestion(state, fetch_fn=fetch_fn)

        self.assertEqual(results["initial_jobless_claims"]["status"], "unchanged")
        history = state["indicators"]["initial_jobless_claims"]["history"]
        self.assertEqual(len(history), 1)
        self.assertEqual(history[0]["value"], 235000.0)

    def test_newer_date_is_appended(self):
        responses = dict(FIXTURES)
        responses["ICSA"] = {"date": "2026-09-11", "value": 240000.0}
        state = {
            "indicators": {
                "initial_jobless_claims": {
                    "name": "Initial Jobless Claims",
                    "category": "leading",
                    "history": [
                        {
                            "date": "2026-09-04",
                            "value": 235000.0,
                            "fetched_at": "2026-09-04T12:00:00Z",
                        }
                    ],
                }
            }
        }
        fetch_fn = fake_fetch_factory(responses)

        results = run_ingestion(state, fetch_fn=fetch_fn)

        self.assertEqual(results["initial_jobless_claims"]["status"], "updated")
        history = state["indicators"]["initial_jobless_claims"]["history"]
        self.assertEqual([e["date"] for e in history], ["2026-09-04", "2026-09-11"])

    def test_fetches_run_concurrently_not_sequentially(self):
        # 8 indicators each sleeping 0.1s: sequential would take >=0.8s;
        # concurrent (one thread per indicator) should take close to 0.1s.
        def slow_fetch(series_id):
            time.sleep(0.1)
            return FIXTURES[series_id]

        state = {"indicators": {}}
        started = time.monotonic()
        run_ingestion(state, fetch_fn=slow_fetch)
        elapsed = time.monotonic() - started

        self.assertLess(elapsed, 0.4)

    def test_results_ordered_by_config_not_completion(self):
        # Give initial_jobless_claims (first in INDICATORS) the longest
        # delay so it resolves last -- results must still come back keyed
        # correctly per indicator regardless of fetch completion order.
        delays = {"ICSA": 0.05}

        def fake_fetch(series_id):
            time.sleep(delays.get(series_id, 0.0))
            return FIXTURES[series_id]

        state = {"indicators": {}}
        results = run_ingestion(state, fetch_fn=fake_fetch)

        self.assertEqual(results["initial_jobless_claims"]["status"], "updated")
        self.assertEqual(results["initial_jobless_claims"]["date"], "2026-09-04")
        self.assertTrue(all(r["status"] == "updated" for r in results.values()))


if __name__ == "__main__":
    unittest.main()
