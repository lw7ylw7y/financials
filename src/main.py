"""Story 1 orchestrator — pull every v1 indicator from FRED.

Fetches the latest value for each configured indicator, tags it with its
category, skips values already seen (no duplicate processing), and never
lets one indicator's failure stop the others. Persistence and querying
live in storage.py (Story 2).
"""

import logging
from datetime import datetime, timezone

from fetch_fred import FredApiError, fetch_latest_observation
from indicators_config import INDICATORS
from storage import load_state, save_state, trim_history

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger(__name__)


def run_ingestion(state: dict, fetch_fn=fetch_latest_observation) -> dict:
    """Fetch the latest value for every configured indicator.

    Mutates `state` in place (appending new history entries) and returns
    a dict of indicator key -> result:
      {"status": "updated"|"unchanged", "date", "value", "category", "name"}
      {"status": "error", "error": str}
    """
    state.setdefault("indicators", {})
    results = {}

    for key, config in INDICATORS.items():
        try:
            observation = fetch_fn(config["fred_series_id"])
        except FredApiError as e:
            logger.error("fetch failed indicator=%s error=%s", key, e)
            results[key] = {"status": "error", "error": str(e)}
            continue

        stored = state["indicators"].get(key, {})
        history = stored.get("history", [])
        last_entry = history[-1] if history else None

        # "New" means a strictly newer date than what's already stored —
        # not just "different from the last entry". A same-or-older date
        # (a stale/cached response, or a same-date revision) must never
        # be written: Story 2 requires history is never overwritten, and
        # an out-of-order append would corrupt the chronological record.
        is_new = last_entry is None or observation["date"] > last_entry["date"]

        if not is_new:
            is_identical = last_entry is not None and (
                observation["date"] == last_entry["date"]
                and observation["value"] == last_entry["value"]
            )
            if last_entry is not None and not is_identical:
                logger.warning(
                    "ignoring non-newer observation indicator=%s incoming=%s stored=%s",
                    key,
                    observation,
                    last_entry,
                )
            results[key] = {
                "status": "unchanged",
                "date": observation["date"],
                "value": observation["value"],
                "category": config["category"],
                "name": config["name"],
            }
            continue

        new_entry = {
            "date": observation["date"],
            "value": observation["value"],
            "fetched_at": datetime.now(timezone.utc).isoformat(),
        }
        state["indicators"][key] = {
            "name": config["name"],
            "category": config["category"],
            "fred_series_id": config["fred_series_id"],
            "fred_release_id": config.get("fred_release_id"),
            "history": trim_history(history + [new_entry]),
            "next_release_date": stored.get("next_release_date"),
        }
        results[key] = {
            "status": "updated",
            "date": observation["date"],
            "value": observation["value"],
            "category": config["category"],
            "name": config["name"],
        }

    return results


def main() -> dict:
    state = load_state()
    results = run_ingestion(state)
    save_state(state)

    updated = sum(1 for r in results.values() if r["status"] == "updated")
    unchanged = sum(1 for r in results.values() if r["status"] == "unchanged")
    errors = sum(1 for r in results.values() if r["status"] == "error")
    logger.info(
        "ingestion complete: %d updated, %d unchanged, %d errors",
        updated,
        unchanged,
        errors,
    )
    return results


if __name__ == "__main__":
    main()
