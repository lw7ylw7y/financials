import os
import sys
import tempfile
import unittest
from datetime import date

_SRC = os.path.join(os.path.dirname(__file__), "..", "src")
for _p in (
    _SRC,
    os.path.join(_SRC, "fred"),
    os.path.join(_SRC, "storage"),
    os.path.join(_SRC, "digest"),
    os.path.join(_SRC, "mailer"),
):
    sys.path.insert(0, _p)

from storage import load_state, query_history, save_state, trim_history


class TestLoadSaveState(unittest.TestCase):
    def test_write_then_reload_matches(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            path = os.path.join(tmp_dir, "indicators.json")
            state = {
                "indicators": {
                    "cpi": {
                        "name": "CPI",
                        "category": "lagging",
                        "history": [{"date": "2026-08-01", "value": 314.5}],
                    }
                }
            }

            save_state(state, path)
            reloaded = load_state(path)

            self.assertEqual(reloaded, state)

    def test_missing_file_initializes_cleanly(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            path = os.path.join(tmp_dir, "does_not_exist.json")

            state = load_state(path)

            self.assertEqual(state, {"indicators": {}})

    def test_corrupted_file_initializes_cleanly(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            path = os.path.join(tmp_dir, "indicators.json")
            with open(path, "w") as f:
                f.write("{not valid json")

            state = load_state(path)

            self.assertEqual(state, {"indicators": {}})

    def test_new_entry_never_overwrites_prior_history(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            path = os.path.join(tmp_dir, "indicators.json")
            state = {
                "indicators": {
                    "cpi": {
                        "name": "CPI",
                        "category": "lagging",
                        "history": [{"date": "2026-07-01", "value": 312.1}],
                    }
                }
            }
            save_state(state, path)

            reloaded = load_state(path)
            reloaded["indicators"]["cpi"]["history"].append(
                {"date": "2026-08-01", "value": 314.5}
            )
            save_state(reloaded, path)

            final = load_state(path)
            self.assertEqual(
                [e["date"] for e in final["indicators"]["cpi"]["history"]],
                ["2026-07-01", "2026-08-01"],
            )


class TestQueryHistory(unittest.TestCase):
    def setUp(self):
        self.state = {
            "indicators": {
                "cpi": {
                    "name": "CPI",
                    "category": "lagging",
                    "history": [
                        {"date": "2026-06-01", "value": 310.0},
                        {"date": "2026-07-01", "value": 312.1},
                        {"date": "2026-08-01", "value": 314.5},
                    ],
                }
            }
        }

    def test_no_range_returns_full_history(self):
        result = query_history(self.state, "cpi")
        self.assertEqual(len(result), 3)

    def test_date_range_filters_correctly(self):
        result = query_history(
            self.state, "cpi", start_date="2026-07-01", end_date="2026-07-31"
        )
        self.assertEqual([e["date"] for e in result], ["2026-07-01"])

    def test_start_date_only(self):
        result = query_history(self.state, "cpi", start_date="2026-07-01")
        self.assertEqual([e["date"] for e in result], ["2026-07-01", "2026-08-01"])

    def test_end_date_only(self):
        result = query_history(self.state, "cpi", end_date="2026-07-01")
        self.assertEqual([e["date"] for e in result], ["2026-06-01", "2026-07-01"])

    def test_unknown_indicator_returns_empty_list(self):
        result = query_history(self.state, "does_not_exist")
        self.assertEqual(result, [])


class TestTrimHistory(unittest.TestCase):
    def test_keeps_entries_within_12_months(self):
        history = [
            {"date": "2025-10-01", "value": 1},
            {"date": "2026-03-01", "value": 2},
            {"date": "2026-09-01", "value": 3},
        ]

        result = trim_history(history, as_of=date(2026, 9, 9))

        self.assertEqual([e["date"] for e in result], [
            "2025-10-01", "2026-03-01", "2026-09-01",
        ])

    def test_drops_entries_older_than_12_months(self):
        history = [
            {"date": "2024-01-01", "value": 1},
            {"date": "2025-08-01", "value": 2},
            {"date": "2026-09-01", "value": 3},
        ]

        result = trim_history(history, as_of=date(2026, 9, 9))

        self.assertEqual([e["date"] for e in result], ["2026-09-01"])

    def test_cutoff_boundary_is_inclusive(self):
        history = [{"date": "2025-09-09", "value": 1}]

        result = trim_history(history, as_of=date(2026, 9, 9))

        self.assertEqual(len(result), 1)

    def test_day_past_cutoff_is_dropped(self):
        history = [{"date": "2025-09-08", "value": 1}]

        result = trim_history(history, as_of=date(2026, 9, 9))

        self.assertEqual(result, [])

    def test_does_not_mutate_input_list(self):
        history = [
            {"date": "2020-01-01", "value": 1},
            {"date": "2026-09-01", "value": 2},
        ]

        trim_history(history, as_of=date(2026, 9, 9))

        self.assertEqual(len(history), 2)


if __name__ == "__main__":
    unittest.main()
