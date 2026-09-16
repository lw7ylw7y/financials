"""Story 1/3/4/5/6/11 orchestrator — ingest FRED data, refresh the
release calendar, keep the AI response fresh, and send the one digest
email.

Fetches the latest value for each configured indicator, tags it with its
category, skips values already seen (no duplicate processing), and never
lets one indicator's failure stop the others. Also refreshes each
indicator's next scheduled release date (Story 3) — before building the
digest, so its countdown (Story 6) reflects the latest calendar data.
Ingestion and the calendar refresh run every scheduled check (every 6
hours); as of Story 11, the AI response is refreshed on that same
cadence too, whenever this run found new data
(`post_release.refresh_ai_response_if_updated`) — decoupled from the
digest email, which stays throttled separately
(`post_release.maybe_send_digest_email`) to a weekly rollup (sent only
when the digest's actual content has meaningfully changed since the
last send AND at least a week has passed), since several indicators
update daily and would otherwise trigger near-constant emails.
Persistence and querying live in storage.py (Story 2), Redis-backed on
a hosted deployment (Story 11).
"""

import logging
import os
import sys
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone

_SRC_DIR = os.path.dirname(os.path.abspath(__file__))
for _subdir in ("fred", "storage", "digest", "mailer"):
    sys.path.insert(0, os.path.join(_SRC_DIR, _subdir))

from fetch_fred import FredApiError, fetch_latest_observation, fetch_next_release_date
from indicators_config import INDICATORS
from post_release import maybe_send_digest_email, refresh_ai_response_if_updated
from storage import load_state, save_state, trim_history

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger(__name__)


def _fetch_observation(item: tuple[str, dict], fetch_fn) -> tuple[str, dict | None, Exception | None]:
    key, config = item
    try:
        return key, fetch_fn(config["fred_series_id"]), None
    except FredApiError as e:
        return key, None, e


def run_ingestion(state: dict, fetch_fn=fetch_latest_observation) -> dict:
    """Fetch the latest value for every configured indicator.

    The fetches themselves run concurrently (one thread per indicator —
    only 8 of them, well within FRED's rate limit) since they're
    independent I/O calls; everything after a fetch resolves (dedup
    check, history append) still runs single-threaded, sequentially, so
    `state` is never mutated from more than one thread at a time.

    Mutates `state` in place (appending new history entries) and returns
    a dict of indicator key -> result:
      {"status": "updated"|"unchanged", "date", "value", "category", "name"}
      {"status": "error", "error": str}
    """
    state.setdefault("indicators", {})
    results = {}

    with ThreadPoolExecutor(max_workers=len(INDICATORS)) as executor:
        fetched = list(
            executor.map(lambda item: _fetch_observation(item, fetch_fn), INDICATORS.items())
        )

    for key, observation, error in fetched:
        config = INDICATORS[key]
        if error is not None:
            logger.error("fetch failed indicator=%s error=%s", key, error)
            results[key] = {"status": "error", "error": str(error)}
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

    to_fetch = []
    for key, config in INDICATORS.items():
        release_id = config.get("fred_release_id")
        if release_id is None:
            indicator = state["indicators"].get(key)
            if indicator is not None:
                indicator["next_release_date"] = None
            continue
        to_fetch.append((key, release_id))

    def _fetch(item):
        key, release_id = item
        try:
            return key, release_id, fetch_fn(release_id), None
        except FredApiError as e:
            return key, release_id, None, e

    # Same reasoning as run_ingestion: only the fetches (independent
    # I/O) run concurrently, one thread per indicator that has a
    # release_id -- the state mutation below stays single-threaded.
    with ThreadPoolExecutor(max_workers=max(len(to_fetch), 1)) as executor:
        fetched = list(executor.map(_fetch, to_fetch))

    for key, release_id, next_date, error in fetched:
        config = INDICATORS[key]
        if error is not None:
            logger.error("release date fetch failed indicator=%s error=%s", key, error)
            results[key] = {"status": "error", "error": str(error)}
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

    updated_keys = [key for key, r in results.items() if r["status"] == "updated"]
    refresh_ai_response_if_updated(state, updated_keys)
    digest_result = maybe_send_digest_email(state)

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
