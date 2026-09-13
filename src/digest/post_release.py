"""Story 4/5/6 orchestrator — the one digest email.

Ingestion (main.run_ingestion) runs every scheduled check (every 6 hours)
regardless, keeping data fresh. The digest email is throttled separately:
sent only when at least one indicator has a genuinely new value *since
the last digest*, AND at least MIN_DIGEST_INTERVAL has passed since the
last digest was sent — a weekly rollup, not an alert on every 6-hour
check. Several tracked indicators (e.g. the yield curve spread) update
daily and would otherwise trigger near-constant emails.

The email contains: a holistic AI-generated summary reasoning across all
8 indicators (Story 4), a table of every indicator's latest/prior value
grouped by category (Story 5), and a next-release countdown highlighting
the soonest upcoming release (Story 6). A failed AI call degrades
gracefully to a table-and-countdown-only email rather than blocking the
send.
"""

import logging
from datetime import datetime, timedelta, timezone

from build_digest_content import (
    build_countdown,
    build_digest_content,
    build_indicators_context,
    build_table,
    sparkline_cid,
)
from email_template import render_html, render_subject, render_text
from interpret import interpret
from send_email import EmailSendError, send_email
from sparkline import render_sparkline

logger = logging.getLogger(__name__)

MIN_DIGEST_INTERVAL = timedelta(days=7)


def build_sparkline_images(indicators_context: list[dict]) -> dict[str, bytes]:
    """Render a trend sparkline PNG per indicator, keyed by its Content-ID."""
    return {
        sparkline_cid(ind["key"]): render_sparkline(ind["history_window"])
        for ind in indicators_context
    }


def build_digest_email(
    state: dict, indicators_context: list[dict], updated_keys: list[str], ai_result: dict | None
) -> dict:
    """Build {"subject", "body", "html_body", "images"} for the digest email.

    `body` is the plain-text multipart/alternative fallback; `html_body`
    is the styled version most clients will render, with a per-indicator
    trend sparkline embedded via `<img src="cid:...">`; `images` maps
    each of those cids to its PNG bytes for send_email.py to attach.
    Rendering itself lives in email_template.py / sparkline.py — this
    function only gathers the data.
    """
    updated_names = [
        state["indicators"][key]["name"]
        for key in updated_keys
        if key in state.get("indicators", {})
    ]
    table = build_table(indicators_context)
    countdown = build_countdown(state)

    return {
        "subject": render_subject(updated_names),
        "body": render_text(table, countdown, ai_result),
        "html_body": render_html(table, countdown, ai_result),
        "images": build_sparkline_images(indicators_context),
    }


def indicators_updated_since(state: dict, since: str | None) -> list[str]:
    """Indicator keys with a history entry fetched after `since` (an ISO
    timestamp string), or every indicator with any history if `since` is
    None (no digest has ever been sent). Uses each entry's `fetched_at`
    (set once, when that entry was first appended — never touched again
    by a later "unchanged" ingestion run) rather than `date`, so this
    reflects real new data, not just recency of a release date.
    """
    updated = []
    for key, indicator in state.get("indicators", {}).items():
        history = indicator.get("history", [])
        if not history:
            continue
        if since is None or history[-1]["fetched_at"] > since:
            updated.append(key)
    return updated


def run_post_release(
    state: dict,
    send_fn=send_email,
    interpret_fn=interpret,
    now: datetime | None = None,
) -> dict:
    """Build and send the digest email, gated on updates-since-last-digest
    and the minimum weekly interval.

    Returns {"status": "skipped"|"sent"|"sent_without_ai"|"error", ...}.
    On send, records `state["last_digest_sent_at"]` so future calls know
    what's new and whether the interval has elapsed.
    """
    now = now or datetime.now(timezone.utc)
    last_sent_at = state.get("last_digest_sent_at")

    updated_keys = indicators_updated_since(state, last_sent_at)
    if not updated_keys:
        return {"status": "skipped", "reason": "no updates since last digest"}

    if last_sent_at is not None:
        elapsed = now - datetime.fromisoformat(last_sent_at)
        if elapsed < MIN_DIGEST_INTERVAL:
            return {"status": "skipped", "reason": "last digest sent too recently"}

    content = build_digest_content(state, updated_keys, interpret_fn=interpret_fn, now=now)
    email = build_digest_email(
        state, content["indicators_context"], updated_keys, content["ai_result"]
    )

    try:
        send_fn(
            email["subject"],
            email["body"],
            html_body=email["html_body"],
            images=email["images"],
        )
    except EmailSendError as e:
        logger.error("digest email send failed error=%s", e)
        return {"status": "error", "error": str(e)}

    state["last_digest_sent_at"] = now.isoformat()
    return {"status": "sent" if content["ai_result"] else "sent_without_ai", **email}
