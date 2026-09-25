import os
import sys
import unittest
from datetime import date
from unittest import mock

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

from kv_store import KvStoreError
from storage import history_start_date, load_state, query_history, save_state, trim_history


def fake_redis():
    """A tiny in-memory stand-in for the single `indicator_state` key,
    for round-trip tests against load_state/save_state's mocked
    get_json/set_json calls."""
    store = {}

    def fake_get(key):
        return store.get(key)

    def fake_set(key, value):
        store[key] = value

    return fake_get, fake_set


class TestLoadSaveState(unittest.TestCase):
    """Story 11 (Redis-backed) + the later "Redis is the only source of
    truth" simplification: indicator state has no local-file fallback
    at all -- `load_state`/`save_state` always go through
    `kv_store.get_json`/`set_json`, mocked here since these are unit
    tests, not a live Upstash instance. Patched on `storage` itself
    (not `kv_store`) because `storage.py` imports those names directly
    via `from kv_store import ...`, so patching the origin module
    wouldn't affect the already-bound names in storage's namespace.
    """

    def test_write_then_reload_matches(self):
        fake_get, fake_set = fake_redis()
        state = {
            "indicators": {
                "cpi": {
                    "name": "CPI",
                    "category": "lagging",
                    "history": [{"date": "2026-08-01", "value": 314.5}],
                }
            }
        }

        with mock.patch("storage.get_json", side_effect=fake_get), mock.patch(
            "storage.set_json", side_effect=fake_set
        ):
            save_state(state)
            reloaded = load_state()

        self.assertEqual(reloaded, state)

    def test_missing_key_initializes_cleanly(self):
        with mock.patch("storage.get_json", return_value=None):
            state = load_state()

        self.assertEqual(state, {"indicators": {}})

    def test_new_entry_never_overwrites_prior_history(self):
        fake_get, fake_set = fake_redis()
        state = {
            "indicators": {
                "cpi": {
                    "name": "CPI",
                    "category": "lagging",
                    "history": [{"date": "2026-07-01", "value": 312.1}],
                }
            }
        }

        with mock.patch("storage.get_json", side_effect=fake_get), mock.patch(
            "storage.set_json", side_effect=fake_set
        ):
            save_state(state)

            reloaded = load_state()
            reloaded["indicators"]["cpi"]["history"].append(
                {"date": "2026-08-01", "value": 314.5}
            )
            save_state(reloaded)

            final = load_state()

        self.assertEqual(
            [e["date"] for e in final["indicators"]["cpi"]["history"]],
            ["2026-07-01", "2026-08-01"],
        )

    def test_load_failure_propagates_rather_than_degrading(self):
        """Unlike the ticker/news caches, indicator state is core data,
        not a mere cache -- a broken load should fail loudly rather
        than silently act as if there were no indicators at all."""
        with mock.patch("storage.get_json", side_effect=KvStoreError("redis down")):
            with self.assertRaises(KvStoreError):
                load_state()

    def test_save_failure_propagates_rather_than_degrading(self):
        with mock.patch("storage.set_json", side_effect=KvStoreError("redis down")):
            with self.assertRaises(KvStoreError):
                save_state({"indicators": {}})


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


class TestHistoryStartDate(unittest.TestCase):
    def test_is_twelve_months_before_the_given_date(self):
        self.assertEqual(history_start_date(date(2026, 9, 25)), "2025-09-25")

    def test_clamps_to_the_end_of_a_shorter_month(self):
        self.assertEqual(history_start_date(date(2028, 2, 29)), "2027-02-28")


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
