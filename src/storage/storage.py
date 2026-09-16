"""Persistent store for indicator history (Story 2), Redis-backed on a
hosted deployment (Story 11).

Wraps data/indicators.json: load/save (moved here from main.py, which
needed minimal persistence for Story 1's dedup check) plus a query
helper for pulling an indicator's history within an optional date range.
Appending new entries is the ingestion loop's job (main.run_ingestion);
this module only loads, saves, queries, and trims what it's given.

`load_state`/`save_state` route through `kv_store.py` (the same Upstash
Redis wrapper Story 9 built for ticker data) when `UPSTASH_REDIS_REST_URL`
is set, and use the local `data/indicators.json` file otherwise (local
dev's unchanged default). This replaces the earlier design where
`data/indicators.json` was git-committed by the scheduled GitHub Action
and read from Render's own git checkout (Story 10) -- both the Action
and any hosted web app now read/write the same Redis-backed state
directly, so a live visitor's background check (`/api/check`) is no
longer stuck writing to Render's ephemeral local disk and losing the
result on the next restart. This does mean indicator history no longer
has a git-diffable audit trail the way it used to -- a deliberate
tradeoff, same one Story 9 already made for ticker data.

`kv_store.py` lives in `src/web/`, not here -- rather than move it (and
touch Story 9's already-working ticker code), this module adds `web/`
to its own `sys.path`, matching this project's per-module
`sys.path.insert` convention (no shared package structure to lean on
instead).

A Redis failure here is *not* caught -- unlike the ticker/news caches,
which degrade gracefully to an empty/pending state, indicator state is
core data, not a mere cache; a broken load should fail loudly rather
than silently act as if there were no indicators at all.
"""

import calendar
import json
import os
import sys
from datetime import date

_STORAGE_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(_STORAGE_DIR, "..", "web"))

from kv_store import get_json, is_configured, set_json  # noqa: E402

DATA_PATH = os.path.join(
    os.path.dirname(__file__), "..", "..", "data", "indicators.json"
)
HISTORY_WINDOW_MONTHS = 12

_INDICATOR_STATE_KEY = "indicator_state"


def load_state(path: str = DATA_PATH) -> dict:
    if is_configured():
        state = get_json(_INDICATOR_STATE_KEY)
        return state if state is not None else {"indicators": {}}

    try:
        with open(path) as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return {"indicators": {}}


def save_state(state: dict, path: str = DATA_PATH) -> None:
    if is_configured():
        set_json(_INDICATOR_STATE_KEY, state)
        return

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
