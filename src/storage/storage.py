"""Persistent JSON-backed store for indicator history (Story 2).

Wraps data/indicators.json: load/save (moved here from main.py, which
needed minimal persistence for Story 1's dedup check) plus a query
helper for pulling an indicator's history within an optional date range.
Appending new entries is the ingestion loop's job (main.run_ingestion);
this module only loads, saves, queries, and trims what it's given.
"""

import calendar
import json
import os
from datetime import date

DATA_PATH = os.path.join(
    os.path.dirname(__file__), "..", "..", "data", "indicators.json"
)
HISTORY_WINDOW_MONTHS = 12


def load_state(path: str = DATA_PATH) -> dict:
    try:
        with open(path) as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return {"indicators": {}}


def save_state(state: dict, path: str = DATA_PATH) -> None:
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w") as f:
        json.dump(state, f, indent=2)
        f.write("\n")


def query_history(
    state: dict,
    key: str,
    start_date: str | None = None,
    end_date: str | None = None,
) -> list[dict]:
    """Return an indicator's history entries, optionally filtered to a date range.

    `start_date`/`end_date` are inclusive ISO "YYYY-MM-DD" strings, which
    sort lexicographically the same as chronologically, so plain string
    comparison is enough. Returns [] for an unknown indicator key.
    """
    indicator = state.get("indicators", {}).get(key)
    if indicator is None:
        return []

    history = indicator.get("history", [])
    if start_date is None and end_date is None:
        return list(history)

    return [
        entry
        for entry in history
        if (start_date is None or entry["date"] >= start_date)
        and (end_date is None or entry["date"] <= end_date)
    ]


def _months_before(d: date, months: int) -> date:
    total_months = d.year * 12 + (d.month - 1) - months
    year, month = divmod(total_months, 12)
    month += 1
    day = min(d.day, calendar.monthrange(year, month)[1])
    return date(year, month, day)


def trim_history(
    history: list[dict],
    months: int = HISTORY_WINDOW_MONTHS,
    as_of: date | None = None,
) -> list[dict]:
    """Drop history entries older than `months` months before `as_of`.

    Indicator readings beyond about a year old aren't useful for the
    trend/table views and would otherwise grow the stored file forever.
    `as_of` defaults to today; entries exactly on the cutoff date are kept.
    """
    as_of = as_of or date.today()
    cutoff = _months_before(as_of, months)
    return [entry for entry in history if date.fromisoformat(entry["date"]) >= cutoff]
