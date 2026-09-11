"""One-time backfill — seed each indicator's history with FRED's recent
real observations.

Not part of the regular scheduled run (main.py) — run manually
(`python3 src/backfill.py`) when history is too sparse for good AI
interpretation (Story 4 needs a real trend window, not 1-2 readings).
Safe to re-run: only adds observations for dates not already present,
never overwrites or removes existing entries (preserves Story 2's
append-only invariant).
"""

import logging
from datetime import datetime, timezone

from fetch_fred import FredApiError, fetch_recent_observations
from indicators_config import INDICATORS
from storage import load_state, save_state, trim_history

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger(__name__)

BACKFILL_LIMIT = 12


def backfill_history(
    state: dict, fetch_fn=fetch_recent_observations, limit: int = BACKFILL_LIMIT
) -> dict:
    """Seed missing history for every indicator from FRED's recent observations.

    For each indicator, fetches the last `limit` real observations and
    adds any whose date isn't already in stored history — existing
    entries (and their original fetched_at) are left untouched.
    """
    state.setdefault("indicators", {})
    results = {}

    for key, config in INDICATORS.items():
        try:
            observations = fetch_fn(config["fred_series_id"], limit=limit)
        except FredApiError as e:
            logger.error("backfill fetch failed indicator=%s error=%s", key, e)
            results[key] = {"status": "error", "error": str(e)}
            continue

        indicator = state["indicators"].setdefault(
            key,
            {
                "name": config["name"],
                "category": config["category"],
                "fred_series_id": config["fred_series_id"],
                "fred_release_id": config.get("fred_release_id"),
                "history": [],
                "next_release_date": None,
            },
        )
        existing_dates = {entry["date"] for entry in indicator["history"]}
        added = [
            {
                "date": obs["date"],
                "value": obs["value"],
                "fetched_at": datetime.now(timezone.utc).isoformat(),
            }
            for obs in observations
            if obs["date"] not in existing_dates
        ]

        indicator["history"] = trim_history(
            sorted(indicator["history"] + added, key=lambda e: e["date"])
        )
        results[key] = {"status": "backfilled", "added": len(added)}

    return results


def main() -> dict:
    state = load_state()
    results = backfill_history(state)
    save_state(state)

    added_total = sum(
        r.get("added", 0) for r in results.values() if r["status"] == "backfilled"
    )
    errors = sum(1 for r in results.values() if r["status"] == "error")
    logger.info(
        "backfill complete: %d entries added across all indicators, %d errors",
        added_total,
        errors,
    )
    return results


if __name__ == "__main__":
    main()
