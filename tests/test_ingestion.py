import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from fetch_fred import FredApiError
from main import load_state, run_ingestion, save_state

FIXTURES = {
    "ICSA": {"date": "2026-09-04", "value": 235000.0},
    "T10Y2Y": {"date": "2026-09-04", "value": 0.3},
    "PERMIT": {"date": "2026-08-01", "value": 1400.0},
    "PAYEMS": {"date": "2026-08-01", "value": 158000.0},
    "INDPRO": {"date": "2026-08-01", "value": 103.2},
    "FEDFUNDS": {"date": "2026-08-01", "value": 5.25},
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

    def test_state_persists_across_processes(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            path = os.path.join(tmp_dir, "indicators.json")
            fetch_fn = fake_fetch_factory(FIXTURES)

            state = load_state(path)
            run_ingestion(state, fetch_fn=fetch_fn)
            save_state(state, path)

            reloaded = load_state(path)

            self.assertEqual(
                reloaded["indicators"]["initial_jobless_claims"]["history"][0]["value"],
                235000.0,
            )

    def test_missing_state_file_initializes_cleanly(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            path = os.path.join(tmp_dir, "does_not_exist.json")

            state = load_state(path)

            self.assertEqual(state, {"indicators": {}})


if __name__ == "__main__":
    unittest.main()
