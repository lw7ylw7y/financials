"""Story 4 orchestrator — post-release email with AI interpretation.

For each indicator whose ingestion result is "updated" (Story 1), builds a
diff against the prior stored reading, gets an AI plain-English summary +
directional read (interpret.py), and sends a post-release email
(send_email.py). A failed AI call degrades gracefully to a raw-data-only
email; a failed send for one indicator is logged and doesn't block others.
"""

import logging

from heuristics import sahm_rule_value, yield_curve_inversion_streak
from interpret import InterpretationError, interpret
from send_email import EmailSendError, send_email

logger = logging.getLogger(__name__)

DISCLAIMER = (
    "This is automated commentary based on indicator trends, "
    "not personalized financial advice."
)
HISTORY_WINDOW = 12


def _heuristic_for(key: str, history: list[dict]) -> dict | None:
    if key == "unemployment_rate":
        value = sahm_rule_value(history)
        return {"sahm_rule_value": value} if value is not None else None
    if key == "yield_curve_spread":
        return {"inversion_streak": yield_curve_inversion_streak(history)}
    return None


def build_diff(history: list[dict]) -> dict:
    """Return the new/prior value+date and the change between them.

    `history` must already include the newly ingested entry as its last
    item. `prior_value`/`prior_date`/`absolute_change`/`percent_change`
    are None when there's no earlier reading to compare against.
    """
    new_entry = history[-1]
    prior_entry = history[-2] if len(history) >= 2 else None

    diff = {
        "new_value": new_entry["value"],
        "new_date": new_entry["date"],
        "prior_value": prior_entry["value"] if prior_entry else None,
        "prior_date": prior_entry["date"] if prior_entry else None,
        "absolute_change": None,
        "percent_change": None,
    }
    if prior_entry is not None:
        diff["absolute_change"] = new_entry["value"] - prior_entry["value"]
        if prior_entry["value"] != 0:
            diff["percent_change"] = (
                diff["absolute_change"] / prior_entry["value"] * 100
            )
    return diff


def build_email(indicator: dict, diff: dict, ai_result: dict | None) -> dict:
    """Build {"subject": str, "body": str} for a post-release email."""
    name = indicator["name"]
    change_str = (
        f" ({diff['absolute_change']:+g})" if diff["absolute_change"] is not None else ""
    )
    subject = f"[Indicator Update] {name}: {diff['new_value']:g}{change_str}"

    lines = [
        f"Indicator: {name} ({indicator['category']})",
        f"New value: {diff['new_value']:g} as of {diff['new_date']}",
    ]
    if diff["prior_value"] is not None:
        lines.append(f"Prior value: {diff['prior_value']:g} as of {diff['prior_date']}")
        lines.append(f"Change: {diff['absolute_change']:+g}")
        if diff["percent_change"] is not None:
            lines.append(f"Percent change: {diff['percent_change']:+.2f}%")
    else:
        lines.append("Prior value: none on record")

    if ai_result is not None:
        lines += [
            "",
            ai_result["summary"],
            f"Directional read: {ai_result['directional_read']}",
            "",
            DISCLAIMER,
        ]

    return {"subject": subject, "body": "\n".join(lines)}


def notify(key: str, indicator: dict, send_fn=send_email, interpret_fn=interpret) -> dict:
    """Build and send the post-release email for one updated indicator.

    Returns {"status": "sent"|"sent_without_ai"|"error", ...}.
    """
    history = indicator.get("history", [])
    if not history:
        return {"status": "error", "error": "no history to notify from"}

    diff = build_diff(history)
    heuristic = _heuristic_for(key, history)
    window = history[-HISTORY_WINDOW:]

    ai_result = None
    try:
        ai_result = interpret_fn(indicator, window, heuristic)
    except InterpretationError as e:
        logger.warning("AI interpretation failed indicator=%s error=%s", key, e)

    email = build_email(indicator, diff, ai_result)

    try:
        send_fn(email["subject"], email["body"])
    except EmailSendError as e:
        logger.error("email send failed indicator=%s error=%s", key, e)
        return {"status": "error", "error": str(e)}

    return {"status": "sent" if ai_result else "sent_without_ai", **email}


def run_post_release(
    state: dict, results: dict, send_fn=send_email, interpret_fn=interpret
) -> dict:
    """Notify for every indicator whose ingestion result is "updated"."""
    outcomes = {}
    for key, result in results.items():
        if result.get("status") != "updated":
            continue
        indicator = state["indicators"][key]
        outcomes[key] = notify(key, indicator, send_fn=send_fn, interpret_fn=interpret_fn)
    return outcomes
