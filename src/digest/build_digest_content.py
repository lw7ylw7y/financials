"""Shared table/countdown/AI-assembly logic (Stories 4/5/6), extracted
out of post_release.py so the weekly digest email and the v2
Indicator Digest Page's on-demand live pull build identical content
from identical logic — one code path, not two divergent ones.

`build_digest_content` is the single entry point either caller needs:
given a state and which indicator keys are new this run, it returns the
table, the countdown, and the AI interpretation (or None on failure),
and persists a successful AI result to `state["last_ai_response"]` so a
later fallback (the page's Saved state) has something to show.
"""

import logging
from datetime import date, datetime, timedelta, timezone

from email_template import CATEGORY_ORDER
from heuristics import sahm_rule_value, yield_curve_inversion_streak
from interpret import InterpretationError
from interpret import interpret as default_interpret

logger = logging.getLogger(__name__)

# After a failed AI call, a retry that isn't triggered by genuinely new data
# waits this long, so a page load or scheduled run during an outage doesn't
# spend one request per model every time.
AI_RETRY_COOLDOWN = timedelta(minutes=15)


def _heuristic_for(key: str, history: list[dict]) -> dict | None:
    if key == "unemployment_rate":
        value = sahm_rule_value(history)
        return {"sahm_rule_value": value} if value is not None else None
    if key == "yield_curve_spread":
        return {"inversion_streak": yield_curve_inversion_streak(history)}
    return None


def build_indicators_context(state: dict) -> list[dict]:
    """One entry per indicator with any history, for the AI prompt and table.

    Each entry: {"key", "name", "category", "history_window" (every
    stored reading, i.e. the last 12 months whatever the series'
    frequency), "heuristic"}.
    """
    context = []
    for key, indicator in state.get("indicators", {}).items():
        history = indicator.get("history", [])
        if not history:
            continue
        context.append(
            {
                "key": key,
                "name": indicator["name"],
                "category": indicator["category"],
                "history_window": history,
                "heuristic": _heuristic_for(key, history),
            }
        )
    return context


def sparkline_cid(key: str) -> str:
    return f"spark-{key}"


def build_table(indicators_context: list[dict]) -> dict:
    """Group indicators into Leading/Coincident/Lagging rows for the table.

    Each row: name, latest_value, latest_date, prior_value (None if
    fewer than 2 history entries on file), sparkline_cid (email-only —
    matches a key in post_release.build_sparkline_images's returned
    dict), sparkline_values (the raw history_window values, oldest
    first — used by the web page to draw an inline SVG trend line;
    the email ignores it since it renders sparkline_cid as a CID image
    instead).
    """
    grouped = {category: [] for category in CATEGORY_ORDER}
    for ind in indicators_context:
        history = ind["history_window"]
        latest = history[-1]
        prior = history[-2] if len(history) >= 2 else None
        grouped.setdefault(ind["category"], []).append(
            {
                "name": ind["name"],
                "latest_value": latest["value"],
                "latest_date": latest["date"],
                "prior_value": prior["value"] if prior else None,
                "sparkline_cid": sparkline_cid(ind["key"]),
                "sparkline_values": [entry["value"] for entry in history],
            }
        )
    return grouped


def build_countdown(state: dict, today: date | None = None) -> dict:
    """Return {"entries": [...], "soonest": entry|None} for indicators with
    a next_release_date, sorted soonest-first.
    """
    today = today or date.today()
    entries = []
    for key, indicator in state.get("indicators", {}).items():
        next_date = indicator.get("next_release_date")
        if not next_date:
            continue
        days_until = (date.fromisoformat(next_date) - today).days
        entries.append(
            {
                "key": key,
                "name": indicator["name"],
                "next_release_date": next_date,
                "days_until": days_until,
            }
        )
    entries.sort(key=lambda e: e["days_until"])
    return {"entries": entries, "soonest": entries[0] if entries else None}


def _latest_dates(state: dict) -> dict[str, str]:
    return {
        key: indicator["history"][-1]["date"]
        for key, indicator in state.get("indicators", {}).items()
        if indicator.get("history")
    }


def stale_indicator_keys(state: dict) -> list[str]:
    """Indicators whose latest reading the stored AI take doesn't cover yet.

    `last_ai_response["as_of"]` records each indicator's latest date at
    the time the take was generated. Anything differing from what's
    stored now (or everything, if there's no take or it predates
    `as_of`) is data the AI hasn't seen -- e.g. because every model
    failed when it arrived.
    """
    as_of = (state.get("last_ai_response") or {}).get("as_of") or {}
    return [key for key, latest in _latest_dates(state).items() if as_of.get(key) != latest]


def ai_retry_keys(state: dict, now: datetime) -> list[str]:
    """Stale indicator keys worth another AI attempt right now: none if
    the take is current, or if the last attempt failed within
    `AI_RETRY_COOLDOWN`."""
    keys = stale_indicator_keys(state)
    failed_at = state.get("ai_last_failed_at")
    if keys and failed_at and now - datetime.fromisoformat(failed_at) < AI_RETRY_COOLDOWN:
        return []
    return keys


def build_digest_content(
    state: dict,
    updated_keys: list[str],
    interpret_fn=default_interpret,
    now: datetime | None = None,
) -> dict:
    """Assemble {"indicators_context", "table", "countdown", "ai_result"}.

    On a successful AI call, persists it to `state["last_ai_response"]`
    as `{"summary", "directional_read", "generated_at", "as_of"}`,
    overwriting any previous one. On failure, leaves `last_ai_response`
    untouched, records `state["ai_last_failed_at"]`, and returns
    `ai_result=None` — the caller decides how to degrade (the email drops
    the AI section; the page falls back to the untouched
    `last_ai_response`). `ai_retry_keys` uses both to retry later.
    """
    now = now or datetime.now(timezone.utc)
    indicators_context = build_indicators_context(state)
    table = build_table(indicators_context)
    countdown = build_countdown(state)

    ai_result = None
    try:
        ai_result = interpret_fn(indicators_context, updated_keys)
    except InterpretationError as e:
        logger.warning("AI interpretation failed error=%s", e)
        state["ai_last_failed_at"] = now.isoformat()

    if ai_result is not None:
        state["last_ai_response"] = {
            "summary": ai_result["summary"],
            "directional_read": ai_result["directional_read"],
            "generated_at": now.isoformat(),
            "as_of": _latest_dates(state),
        }
        state.pop("ai_last_failed_at", None)

    return {
        "indicators_context": indicators_context,
        "table": table,
        "countdown": countdown,
        "ai_result": ai_result,
    }
