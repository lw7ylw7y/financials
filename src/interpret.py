"""Gemini API call for post-release plain-English interpretation (Story 4).

Uses gemini-3.8-flash, a free-tier model (per ai.google.dev/gemini-api/docs/pricing),
since this is a short, well-specified commentary task with low request
volume — well within the free tier's daily/per-minute limits.

Per Section 6 of v1_technical_design.md: reasons from a 12-reading
historical window (not just the single prior value) plus, where
applicable, a pre-computed named-heuristic value (heuristics.py), and
returns a short plain-English summary plus a bullish/bearish/neutral
directional read. Deliberately excludes the AI's own past interpretations
from the input, to avoid anchoring on earlier reads.
"""

import logging
from typing import Literal

from google import genai
from google.genai import errors, types
from pydantic import BaseModel, ValidationError

logger = logging.getLogger(__name__)

MODEL = "gemini-3.8-flash"
MAX_ATTEMPTS = 4  # 1 initial call + 3 retries, per HttpRetryOptions.attempts

SYSTEM_PROMPT = """You are a macroeconomic commentator writing for a long-term, \
buy-and-hold individual investor who is not a professional trader.

You will be given a newly released economic indicator value, its category \
(leading, coincident, or lagging), its most recent historical readings, and \
sometimes a pre-computed named-heuristic value (e.g. the Sahm Rule, or a \
yield curve inversion streak) — use that computed value as given, don't \
recompute it yourself.

Reason from the historical window and any computed heuristic, not just the \
single most recent change — distinguish a real multi-month trend from a \
one-off noisy blip. Explain in plain English, in 2-4 sentences, what \
changed and why it matters for a long-term buy-and-hold investor. Then give \
a directional read of exactly one of "bullish", "bearish", or "neutral".
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


def build_user_prompt(
    indicator: dict, history_window: list[dict], heuristic: dict | None
) -> str:
    latest = history_window[-1]
    return (
        f"Indicator: {indicator['name']}\n"
        f"Category: {indicator['category']}\n"
        f"New value: {latest['value']} as of {latest['date']}\n\n"
        f"Recent readings (oldest to newest, up to the last 12):\n"
        f"{_format_history(history_window)}\n\n"
        f"Computed heuristic values:\n"
        f"{_format_heuristic(heuristic)}"
    )


def interpret(
    indicator: dict,
    history_window: list[dict],
    heuristic: dict | None = None,
    client: genai.Client | None = None,
) -> dict:
    """Return {"summary": str, "directional_read": "bullish"|"bearish"|"neutral"}.

    Raises InterpretationError on any API failure, missing credentials, or
    unusable response, so callers (post_release.py) can degrade gracefully
    to a raw-data-only email rather than blocking on a broken AI call.
    """
    prompt = build_user_prompt(indicator, history_window, heuristic)

    try:
        client = client or genai.Client(
            http_options=types.HttpOptions(
                retry_options=types.HttpRetryOptions(attempts=MAX_ATTEMPTS)
            )
        )
        response = client.models.generate_content(
            model=MODEL,
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

    if not response.text:
        raise InterpretationError("Gemini returned no text content")

    try:
        parsed = Interpretation.model_validate_json(response.text)
    except ValidationError as e:
        raise InterpretationError(f"could not parse AI response: {e}") from e

    return {"summary": parsed.summary, "directional_read": parsed.directional_read}
