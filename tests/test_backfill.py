import os
import sys
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

from backfill import backfill_history
from fetch_fred import FredApiError
from indicators_config import INDICATORS

CPI_OBSERVATIONS = [
    {"date": "2026-06-01", "value": 331.5},
    {"date": "2026-07-01", "value": 332.813},
    {"date": "2026-08-01", "value": 334.131},
]


def fake_fetch_factory(responses):
    """responses: {fred_series_id: list[dict] | Exception}. Unlisted series
    default to an empty observation list, matching indicators with nothing
    of interest to a given test.
    """

    def fake_fetch(series_id, limit=12):
        response = responses.get(series_id, [])
        if isinstance(response, Exception):
            raise response
        return response

    return fake_fetch


def cpi_only_state(existing_history=None):
    return {
        "indicators": {
            "cpi": {
                "name": "CPI",
                "category": "lagging",
                "fred_series_id": "CPIAUCSL",
                "fred_release_id": "10",
                "history": existing_history or [],
                "next_release_date": None,
            }
        }
    }


class TestBackfillHistory(unittest.TestCase):
    def test_adds_observations_not_already_in_history(self):
        state = cpi_only_state(
            existing_history=[
                {
                    "date": "2026-07-01",
                    "value": 332.813,
                    "fetched_at": "2026-09-09T00:00:00+00:00",
                }
            ]
        )
        fetch_fn = fake_fetch_factory({"CPIAUCSL": CPI_OBSERVATIONS})

        results = backfill_history(state, fetch_fn=fetch_fn)

        dates = [e["date"] for e in state["indicators"]["cpi"]["history"]]
        self.assertEqual(dates, ["2026-06-01", "2026-07-01", "2026-08-01"])
        self.assertEqual(results["cpi"]["added"], 2)

    def test_does_not_overwrite_existing_entry(self):
        state = cpi_only_state(
            existing_history=[
                {
                    "date": "2026-07-01",
                    "value": 332.813,
                    "fetched_at": "2026-09-09T00:00:00+00:00",
                }
            ]
        )
        fetch_fn = fake_fetch_factory({"CPIAUCSL": CPI_OBSERVATIONS})

        backfill_history(state, fetch_fn=fetch_fn)

        entry = next(
            e
            for e in state["indicators"]["cpi"]["history"]
            if e["date"] == "2026-07-01"
        )
        self.assertEqual(entry["fetched_at"], "2026-09-09T00:00:00+00:00")

    def test_creates_indicator_entry_if_missing_from_state(self):
        state = {"indicators": {}}
        fetch_fn = fake_fetch_factory({"CPIAUCSL": CPI_OBSERVATIONS})

        results = backfill_history(state, fetch_fn=fetch_fn)

        self.assertIn("cpi", state["indicators"])
        self.assertEqual(len(state["indicators"]["cpi"]["history"]), 3)
        self.assertEqual(results["cpi"]["added"], 3)

    def test_covers_every_configured_indicator(self):
        state = {"indicators": {}}
        fetch_fn = fake_fetch_factory({"CPIAUCSL": CPI_OBSERVATIONS})

        results = backfill_history(state, fetch_fn=fetch_fn)

        self.assertEqual(set(results.keys()), set(INDICATORS.keys()))

    def test_is_idempotent_on_rerun(self):
        state = {"indicators": {}}
        fetch_fn = fake_fetch_factory({"CPIAUCSL": CPI_OBSERVATIONS})

        backfill_history(state, fetch_fn=fetch_fn)
        first_run_history = list(state["indicators"]["cpi"]["history"])
        backfill_history(state, fetch_fn=fetch_fn)
        second_run_history = state["indicators"]["cpi"]["history"]

        self.assertEqual(first_run_history, second_run_history)

    def test_one_indicator_failure_does_not_block_others(self):
        fetch_fn = fake_fetch_factory(
            {"CPIAUCSL": CPI_OBSERVATIONS, "ICSA": FredApiError("outage")}
        )
        state = {"indicators": {}}

        results = backfill_history(state, fetch_fn=fetch_fn)

        self.assertEqual(results["initial_jobless_claims"]["status"], "error")
        self.assertEqual(results["cpi"]["status"], "backfilled")


if __name__ == "__main__":
    unittest.main()
