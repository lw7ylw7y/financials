"""Gemini API call for the digest's holistic AI interpretation.

Uses gemini-3.8-flash, a free-tier model (per ai.google.dev/gemini-api/docs/pricing),
since this is a short, well-specified commentary task with low request
volume — well within the free tier's daily/per-minute limits.

One call per digest, reasoning across *all 8* indicators' 12-reading
historical windows together (not one call per updated indicator) plus,
where applicable, pre-computed named-heuristic values (heuristics.py),
and returns a short plain-English summary plus one overall
bullish/bearish/neutral directional read. Deliberately excludes the
AI's own past interpretations from the input, to avoid anchoring on
earlier reads.
"""

import logging
import os
import sys
from typing import Literal

from google import genai
from google.genai import errors, types
from pydantic import BaseModel, ValidationError

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "web"))

import claude_client

logger = logging.getLogger(__name__)

MODEL = "gemini-3.8-flash"
# Free-tier quotas and serving capacity are tracked per model, so a
# different model often still answers while `MODEL` is overloaded or
# out of quota. Overridable via GEMINI_FALLBACK_MODEL.
DEFAULT_FALLBACK_MODEL = "gemini-3.7-flash"
# No retries: the free tier's 20-requests/day cap counts every attempt,
# including failed ones, so retrying against a sustained backend outage
# (the observed real-world failure mode) burns through the day's whole
# quota for zero successes rather than helping with a one-off blip.
MAX_ATTEMPTS = 1

SYSTEM_PROMPT = """You are a macroeconomic commentator writing for a long-term, \
buy-and-hold individual investor who is not a professional trader.

You will be given all 8 tracked economic indicators (grouped as leading, \
coincident, or lagging), each with its recent historical readings, which \
one(s) published a new value this run, and sometimes a pre-computed \
named-heuristic value (e.g. the Sahm Rule, or a yield curve inversion \
streak) — use that computed value as given, don't recompute it yourself.

Reason across all 8 indicators together, not just the one(s) that just \
updated — connect indicators to each other where relevant (e.g. \
unemployment ticking up while inflation cools), and reason from each \
one's historical window, not just its single most recent change, to \
distinguish a real multi-month trend from a one-off noisy blip. Explain \
in plain English, in 3-6 sentences, what changed and why it matters for a \
long-term buy-and-hold investor. Then give ONE overall directional read \
of exactly one of "bullish", "bearish", or "neutral" for the picture as a \
whole — not one per indicator.
"""


class Interpretation(BaseModel):
    summary: str
    directional_read: Literal["bullish", "bearish", "neutral"]


class InterpretationError(Exception):
    """Raised for any failure to obtain a usable AI interpretation."""


def _format_history(history_window: list[dict]) -> str:
    return "\n".join(f"- {entry['date']}: {entry['value']}" for entry in history_window)


def _format_heuristic(heuristic: dict | None) -> str:
    if not heuristic:
        return "(none)"
    return "\n".join(f"- {key}: {value}" for key, value in heuristic.items())


def build_user_prompt(indicators_context: list[dict], updated_keys: list[str]) -> str:
    """`indicators_context`: one entry per indicator with data to report —
    {"key", "name", "category", "history_window", "heuristic"}. `updated_keys`
    names which of those published a new value this run.
    """
    updated_names = [
        ind["name"] for ind in indicators_context if ind["key"] in updated_keys
    ]

    sections = []
    for ind in indicators_context:
        marker = " — NEW VALUE THIS RUN" if ind["key"] in updated_keys else ""
        sections.append(
            f"### {ind['name']} ({ind['category']}){marker}\n"
            f"Recent readings (oldest to newest, up to the last 12):\n"
            f"{_format_history(ind['history_window'])}\n"
            f"Computed heuristic values:\n"
            f"{_format_heuristic(ind['heuristic'])}"
        )

    return (
        f"Indicators with a new value this run: {', '.join(updated_names) or '(none)'}\n\n"
        + "\n\n".join(sections)
    )


def _parse(text: str | None, source: str) -> dict:
    if not text:
        raise InterpretationError(f"{source} returned no text content")
    try:
        parsed = Interpretation.model_validate_json(text)
    except ValidationError as e:
        raise InterpretationError(f"could not parse {source} response: {e}") from e
    return {"summary": parsed.summary, "directional_read": parsed.directional_read}


def _interpret_with_gemini(prompt: str, client: genai.Client | None, model: str = MODEL) -> dict:
    try:
        client = client or genai.Client(
            http_options=types.HttpOptions(
                retry_options=types.HttpRetryOptions(attempts=MAX_ATTEMPTS)
            )
        )
        response = client.models.generate_content(
            model=model,
            contents=prompt,
            config=types.GenerateContentConfig(
                system_instruction=SYSTEM_PROMPT,
                response_mime_type="application/json",
                response_schema=Interpretation,
            ),
        )
    except errors.APIError as e:
        raise InterpretationError(f"Gemini API call failed: {e}") from e
    except ValueError as e:
        # genai.Client() raises a bare ValueError (not an APIError) when no
        # API key is configured — still a "the AI call is unusable" case
        # that must degrade gracefully, not crash the run.
        raise InterpretationError(f"Gemini client not configured: {e}") from e
    return _parse(response.text, "Gemini")


def _interpret_with_claude(prompt: str) -> dict:
    try:
        text = claude_client.generate_json(SYSTEM_PROMPT, prompt, Interpretation)
    except claude_client.ClaudeApiError as e:
        raise InterpretationError(str(e)) from e
    return _parse(text, "Claude")


def _run_with_fallbacks(prompt: str, client: genai.Client | None) -> dict:
    """Gemini, then a second Gemini model, then Claude; the first
    usable result wins. An explicitly injected `client` is used alone."""
    fallback_model = os.environ.get("GEMINI_FALLBACK_MODEL") or DEFAULT_FALLBACK_MODEL
    sources = [("Gemini", lambda: _interpret_with_gemini(prompt, client))]
    if client is None:
        sources += [
            (f"Gemini {fallback_model}", lambda: _interpret_with_gemini(prompt, None, fallback_model)),
            ("Claude", lambda: _interpret_with_claude(prompt)),
        ]

    failures = []
    for name, attempt in sources:
        try:
            return attempt()
        except InterpretationError as e:
            logger.warning("%s interpretation failed: %s", name, e)
            failures.append(str(e))
    raise InterpretationError("; ".join(failures))


def interpret(
    indicators_context: list[dict],
    updated_keys: list[str],
    client: genai.Client | None = None,
) -> dict:
    """Return {"summary": str, "directional_read": "bullish"|"bearish"|"neutral"}.

    Tries Gemini first, then a second Gemini model, then Claude
    if each fails for any reason (the free tier's sustained 503s are
    the usual cause). An explicitly injected `client` is used alone,
    with no fallback.

    Raises InterpretationError when every source fails, so the caller
    (post_release.py) can degrade gracefully to a table-and-countdown-only
    digest rather than blocking on a broken AI call.
    """
    prompt = build_user_prompt(indicators_context, updated_keys)

    return _run_with_fallbacks(prompt, client)
