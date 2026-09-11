"""Story 1/3/4/5/6 orchestrator — ingest FRED data, refresh the release
calendar, and send the one digest email.

Fetches the latest value for each configured indicator, tags it with its
category, skips values already seen (no duplicate processing), and never
lets one indicator's failure stop the others. Also refreshes each
indicator's next scheduled release date (Story 3) — before building the
digest, so its countdown (Story 6) reflects the latest calendar data.
Ingestion and the calendar refresh run every scheduled check (every 6
hours); the digest email itself is throttled separately by
post_release.run_post_release to a weekly rollup (sent only when
something's changed since the last digest AND at least a week has
passed), since several indicators update daily and would otherwise
trigger near-constant emails. Persistence and querying live in
storage.py (Story 2).
"""

import logging
from datetime import datetime, timezone

from fetch_fred import FredApiError, fetch_latest_observation, fetch_next_release_date
from indicators_config import INDICATORS
from post_release import run_post_release
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


def update_release_calendar(state: dict, fetch_fn=fetch_next_release_date) -> dict:
    """Refresh next_release_date for every indicator with a fred_release_id.

    Indicators with no fred_release_id (e.g. the yield curve spread,
    which updates continuously, or Fed Funds Rate, whose mapped release
    bundles many series at a cadence unrelated to its own) have no
    meaningful countdown — Story 6's countdown excludes them. Any stale
    next_release_date left over from a previous config is cleared here
    too, so removing an indicator's release_id actually takes effect
    rather than leaving old data behind. Overwrites next_release_date in
    place rather than appending, since it's a single current value, not
    a history.
    """
    state.setdefault("indicators", {})
    results = {}

    for key, config in INDICATORS.items():
        release_id = config.get("fred_release_id")
        if release_id is None:
            indicator = state["indicators"].get(key)
            if indicator is not None:
                indicator["next_release_date"] = None
            continue

        try:
            next_date = fetch_fn(release_id)
        except FredApiError as e:
            logger.error("release date fetch failed indicator=%s error=%s", key, e)
            results[key] = {"status": "error", "error": str(e)}
            continue

        indicator = state["indicators"].setdefault(
            key,
            {
                "name": config["name"],
                "category": config["category"],
                "fred_series_id": config["fred_series_id"],
                "fred_release_id": release_id,
                "history": [],
            },
        )
        indicator["next_release_date"] = next_date
        results[key] = {"status": "updated", "next_release_date": next_date}

    return results


def main() -> dict:
    state = load_state()
    results = run_ingestion(state)
    calendar_results = update_release_calendar(state)
    digest_result = run_post_release(state)
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

    calendar_updated = sum(
        1 for r in calendar_results.values() if r["status"] == "updated"
    )
    calendar_errors = sum(
        1 for r in calendar_results.values() if r["status"] == "error"
    )
    logger.info(
        "release calendar refresh complete: %d updated, %d errors",
        calendar_updated,
        calendar_errors,
    )

    if digest_result["status"] == "skipped":
        logger.info("digest email: skipped (%s)", digest_result["reason"])
    else:
        logger.info("digest email: %s", digest_result["status"])
    return results


if __name__ == "__main__":
    main()
