"""Orchestrator for the weekly digest email, with AI-response freshness
decoupled from send cadence.

Ingestion (main.run_ingestion) runs every scheduled check (every 6
hours) regardless, keeping data fresh. The AI response
(`state["last_ai_response"]`) is refreshed on that same cadence —
`refresh_ai_response_if_updated` regenerates it whenever *this run*
found at least one genuinely new indicator value, independent of the
email, so the stored AI take (and anything reading it live, like the
web page) never lags behind the data.

The email itself is a weekly rollup: the send-gate
(`maybe_send_digest_email`) hashes the *current* persisted state (every
indicator's latest value/date, plus the AI's directional_read —
deliberately excluding the free-text summary, since Gemini can reword
an unchanged situation differently between calls) into a content
fingerprint, and sends only if that fingerprint differs from what was
last emailed AND at least MIN_DIGEST_INTERVAL has passed since the last
send. This runs every cycle regardless of whether
`refresh_ai_response_if_updated` also ran this same cycle — it never
calls Gemini itself, just reads what's already in `state`, so there's
no duplicate AI call and no coupling between "is the AI response
fresh" and "should we email."

The email contains: a holistic AI-generated summary reasoning across all
8 indicators, a table of every indicator's latest/prior value grouped by
category, and a next-release countdown highlighting the soonest upcoming
release. A failed AI call degrades gracefully to a
table-and-countdown-only email rather than blocking the send.
"""

import hashlib
import json
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


def refresh_ai_response_if_updated(
    state: dict,
    updated_keys: list[str],
    interpret_fn=interpret,
    now: datetime | None = None,
) -> dict | None:
    """Regenerate and persist a fresh AI take whenever `updated_keys`
    (this run's genuinely-new indicators, from `main.run_ingestion`'s
    own result — *not* "since the last email") is non-empty.

    Decoupled from the email's weekly throttle: the stored AI response
    stays as fresh as the data itself, every ingestion cycle, rather
    than only refreshing when an email also happens to be due. Returns
    the built content dict (see
    `build_digest_content`), or `None` if there was nothing new this
    run — the caller passes that content straight to whatever else
    needs it this cycle (e.g. the web page's live-check response)
    without a second Gemini call.
    """
    if not updated_keys:
        return None
    now = now or datetime.now(timezone.utc)
    return build_digest_content(state, updated_keys, interpret_fn=interpret_fn, now=now)


def _digest_fingerprint(state: dict) -> str:
    """A stable hash of the *current* persisted state's bottom line —
    each indicator's `(key, latest value, latest date)` plus the AI's
    `directional_read` — used to decide whether the weekly email's
    content has meaningfully changed since the last send.

    Deliberately excludes the AI summary's free text: Gemini can
    reword an unchanged situation differently between calls, and that
    alone shouldn't be enough to trigger a resend. Reads only what's
    already in `state` — no Gemini call, safe to compute every cycle
    regardless of whether `refresh_ai_response_if_updated` also ran.
    """
    facts = sorted(
        (key, indicator["history"][-1]["value"], indicator["history"][-1]["date"])
        for key, indicator in state.get("indicators", {}).items()
        if indicator.get("history")
    )
    last_ai = state.get("last_ai_response")
    directional_read = last_ai["directional_read"] if last_ai else None
    payload = json.dumps({"facts": facts, "directional_read": directional_read}, sort_keys=True)
    return hashlib.sha256(payload.encode()).hexdigest()


def maybe_send_digest_email(
    state: dict,
    send_fn=send_email,
    now: datetime | None = None,
) -> dict:
    """Decide whether to send the weekly digest email — purely a
    function of the *current* persisted state: sends only
    if the content fingerprint (`_digest_fingerprint`) differs from
    what was last emailed AND at least `MIN_DIGEST_INTERVAL` has passed
    since the last send. Runs every cycle independent of whether
    `refresh_ai_response_if_updated` also ran this same cycle — never
    calls Gemini itself, just reads what's already in `state`, so
    there's no duplicate AI call and no coupling between AI freshness
    and email cadence.

    `indicators_updated_since` is still used here, but only to name
    what's new in the email's subject/content when a send does happen
    — it's no longer the gate deciding *whether* to send.

    Returns {"status": "skipped"|"sent"|"sent_without_ai"|"error", ...}.
    On send, records both `state["last_digest_sent_at"]` and
    `state["last_digest_content_fingerprint"]`.
    """
    now = now or datetime.now(timezone.utc)
    last_sent_at = state.get("last_digest_sent_at")

    fingerprint = _digest_fingerprint(state)
    if fingerprint == state.get("last_digest_content_fingerprint"):
        return {"status": "skipped", "reason": "content unchanged since last digest"}

    if last_sent_at is not None:
        elapsed = now - datetime.fromisoformat(last_sent_at)
        if elapsed < MIN_DIGEST_INTERVAL:
            return {"status": "skipped", "reason": "last digest sent too recently"}

    updated_keys = indicators_updated_since(state, last_sent_at)
    indicators_context = build_indicators_context(state)
    ai_result = state.get("last_ai_response")
    email = build_digest_email(state, indicators_context, updated_keys, ai_result)

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
    state["last_digest_content_fingerprint"] = fingerprint
    return {"status": "sent" if ai_result else "sent_without_ai", **email}
