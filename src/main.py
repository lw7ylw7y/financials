"""Story 1 orchestrator — pull every v1 indicator from FRED.

Fetches the latest value for each configured indicator, tags it with its
category, skips values already seen (no duplicate processing), and never
lets one indicator's failure stop the others. Minimal load/save of
data/indicators.json lives here for now; Story 2 owns the full historical
query API on top of this same file.
"""

import json
import logging
import os
from datetime import datetime, timezone

from fetch_fred import FredApiError, fetch_latest_observation
from indicators_config import INDICATORS

DATA_PATH = os.path.join(os.path.dirname(__file__), "..", "data", "indicators.json")

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger(__name__)


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
        unchanged = (
            last_entry is not None
            and last_entry["date"] == observation["date"]
            and last_entry["value"] == observation["value"]
        )

        if unchanged:
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
            "history": history + [new_entry],
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
