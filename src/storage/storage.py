"""Persistent store for indicator history -- Redis-backed,
unconditionally, via kv_store.py.

Load/save plus a query helper for pulling an indicator's history
within an optional date range. Appending new entries is the ingestion
loop's job (main.run_ingestion); this module only loads, saves,
queries, and trims what it's given.

`UPSTASH_REDIS_REST_URL`/`UPSTASH_REDIS_REST_TOKEN` must be set
wherever this module runs -- there is no local-file fallback.
`kv_store.py` raises a clear `KvStoreError` if they aren't. This keeps
the scheduled GitHub Action and any hosted web app reading/writing the
same state directly, so a live visitor's background check
(`/api/check`) is never lost to a host's ephemeral local disk.

`kv_store.py` lives in `src/web/`, not here -- rather than move it,
this module adds `web/` to its own `sys.path`, matching this project's
per-module `sys.path.insert` convention (no shared package structure to
lean on instead).

A Redis failure here is *not* caught -- unlike the ticker/news caches,
which degrade gracefully to an empty/pending state, indicator state is
core data, not a mere cache; a broken load should fail loudly rather
than silently act as if there were no indicators at all.

A wiped or brand-new Redis key comes back as an empty
`{"indicators": {}}` -- there's no local file to reseed from.
Recovering real history after a wipe is `backfill.py`'s job (pulls
recent readings straight from FRED), not this module's.
"""

import calendar
import os
import sys
from datetime import date

_STORAGE_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(_STORAGE_DIR, "..", "web"))

from kv_store import get_json, set_json  # noqa: E402

HISTORY_WINDOW_MONTHS = 12

_INDICATOR_STATE_KEY = "indicator_state"


def load_state() -> dict:
    state = get_json(_INDICATOR_STATE_KEY)
    return state if state is not None else {"indicators": {}}


def save_state(state: dict) -> None:
    set_json(_INDICATOR_STATE_KEY, state)


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


def history_start_date(as_of: date | None = None) -> str:
    """ISO date of the oldest reading `trim_history` keeps."""
    return _months_before(as_of or date.today(), HISTORY_WINDOW_MONTHS).isoformat()


def trim_history(
    history: list[dict],
    months: int = HISTORY_WINDOW_MONTHS,
    as_of: date | None = None,
) -> list[dict]:
    """Drop history entries older than `months` months before `as_of`.

    Indicator readings beyond about a year old aren't useful for the
    trend/table views and would otherwise grow the stored state forever.
    `as_of` defaults to today; entries exactly on the cutoff date are kept.
    """
    as_of = as_of or date.today()
    cutoff = _months_before(as_of, months)
    return [entry for entry in history if date.fromisoformat(entry["date"]) >= cutoff]
