"""Indicator Digest Page orchestration.

Split into two paths so the page loads instantly and doesn't spend a
Gemini call when nothing's actually new:

- `get_initial_page_data()` — renders entirely from stored data, no
  network calls. This is what "/" returns.
- `check_for_updates()` — called by the page's own background script
  after that fast render. Does the real live pull (FRED ingestion); only
  if that finds at least one indicator with a genuinely new value does
  it also refresh the release calendar and call the AI interpretation
  and persist the result — a check that finds nothing new costs a FRED
  call but never an AI call, and reports "no update" so the page isn't
  touched at all.
"""

import logging
import os
import sys
from datetime import datetime, timezone

_WEB_DIR = os.path.dirname(os.path.abspath(__file__))
_SRC_DIR = os.path.dirname(_WEB_DIR)
for _subdir in ("fred", "storage", "digest", "mailer"):
    sys.path.insert(0, os.path.join(_SRC_DIR, _subdir))
sys.path.insert(0, _SRC_DIR)

from build_digest_content import (
    ai_retry_keys,
    build_countdown,
    build_digest_content,
    build_indicators_context,
    build_table,
)
from main import run_ingestion, update_release_calendar
from storage import load_state, save_state

logger = logging.getLogger(__name__)


def _latest_fetched_at(state: dict) -> str | None:
    """Most recent fetched_at across all indicators — the values
    timestamp shown on the stored/initial render."""
    latest = None
    for indicator in state.get("indicators", {}).values():
        history = indicator.get("history", [])
        if history and (latest is None or history[-1]["fetched_at"] > latest):
            latest = history[-1]["fetched_at"]
    return latest


def get_stored_page_data(state: dict) -> dict:
    """Build page data entirely from what's already on disk — no live
    fetch attempted. Used both for the fast initial "/" render and as
    the fallback when a background check can't produce a usable result.
    """
    indicators_context = build_indicators_context(state)
    table = build_table(indicators_context)
    countdown = build_countdown(state)
    stored_ai = state.get("last_ai_response")

    return {
        "table": table,
        "countdown": countdown,
        "ai_result": stored_ai,
        "values_status": "saved",
        "values_timestamp": _latest_fetched_at(state),
        "ai_status": "saved" if stored_ai else "none",
        "ai_timestamp": stored_ai["generated_at"] if stored_ai else None,
    }


def get_initial_page_data() -> dict:
    """What "/" renders — instantly, from stored data only. The page's
    own script then calls check_for_updates (via /api/check) to look
    for anything newer.
    """
    return get_stored_page_data(load_state())


def check_for_updates(now: datetime | None = None) -> dict:
    """Attempt a live pull; only spend an AI call if at least one
    indicator has a genuinely new value, or an earlier AI attempt failed
    and its retry is due (`ai_retry_keys`) -- so a Gemini outage when
    data arrived doesn't leave the AI take stale until the next release.

    Returns {"data_updated": False} (nothing for the caller to render)
    when there's nothing new and no AI take was produced, the live pull
    couldn't get anything usable (e.g. every indicator's fetch failed),
    or an unexpected error occurred. Returns {"data_updated": True,
    "content": {...}, "checked_at": now} when build_digest_content has
    fresh content to show -- `content` is that function's own return
    shape.
    """
    now = now or datetime.now(timezone.utc)

    try:
        state = load_state()
        ingestion_results = run_ingestion(state)
        updated_keys = [
            key for key, r in ingestion_results.items() if r["status"] == "updated"
        ]
        keys = sorted(set(updated_keys) | set(ai_retry_keys(state, now)))
        if not keys:
            return {"data_updated": False}

        if updated_keys:
            update_release_calendar(state)
        content = build_digest_content(state, keys, now=now)
        save_state(state)

        if not updated_keys and content["ai_result"] is None:
            # A retry that failed again: state records the attempt, but
            # there's nothing new for the page to repaint.
            return {"data_updated": False}
        return {"data_updated": True, "content": content, "checked_at": now}

    except Exception as e:
        logger.error("background update check failed error=%s", e)
        return {"data_updated": False}
