"""Thin client for the Anthropic Messages API, used as the last-resort
fallback when both Gemini calls fail.

Returns the raw JSON text of the model's reply; callers validate it
against their own pydantic schema, the same as for a Gemini response.
The schema is spelled out in the system prompt, and the JSON object is
cut out of the reply (models sometimes wrap it in a code fence), since
this avoids depending on structured-output support for a given model.

Needs `ANTHROPIC_API_KEY` from the Anthropic Console -- API access is
billed separately from a claude.ai subscription.
"""

import json
import os

import requests
from pydantic import BaseModel

ANTHROPIC_URL = "https://api.anthropic.com/v1/messages"
ANTHROPIC_VERSION = "2023-06-01"
DEFAULT_MODEL = "claude-haiku-4-5-20251001"
MAX_TOKENS = 4096
REQUEST_TIMEOUT_SECONDS = 60

_session = requests.Session()


class ClaudeApiError(Exception):
    """Raised for any Anthropic request/response problem."""


def _api_key() -> str:
    key = os.environ.get("ANTHROPIC_API_KEY")
    if not key:
        raise ClaudeApiError("no ANTHROPIC_API_KEY configured")
    return key.strip()


def _extract_json_object(text: str) -> str:
    start, end = text.find("{"), text.rfind("}")
    if start == -1 or end < start:
        raise ClaudeApiError("Claude reply contained no JSON object")
    return text[start : end + 1]


def generate_json(system_prompt: str, user_prompt: str, schema: type[BaseModel]) -> str:
    """Return the model's JSON reply text for `user_prompt`, shaped to `schema`."""
    api_key = _api_key()
    model = os.environ.get("CLAUDE_FALLBACK_MODEL") or DEFAULT_MODEL
    schema_json = json.dumps(schema.model_json_schema())
    system = (
        f"{system_prompt}\n\nRespond with a single JSON object and nothing else, "
        f"conforming to this JSON Schema:\n{schema_json}"
    )

    try:
        response = _session.post(
            ANTHROPIC_URL,
            headers={
                "x-api-key": api_key,
                "anthropic-version": ANTHROPIC_VERSION,
                "content-type": "application/json",
            },
            json={
                "model": model,
                "max_tokens": MAX_TOKENS,
                "system": system,
                "messages": [{"role": "user", "content": user_prompt}],
            },
            timeout=REQUEST_TIMEOUT_SECONDS,
        )
        response.raise_for_status()
        blocks = response.json()["content"]
        text = "".join(b.get("text", "") for b in blocks if b.get("type") == "text")
    except (ValueError, KeyError, TypeError, AttributeError) as e:
        # `requests`' JSONDecodeError is both a ValueError and a
        # RequestException, so this must precede the request-failure branch.
        raise ClaudeApiError(f"unexpected Anthropic response shape: {e}") from e
    except requests.RequestException as e:
        raise ClaudeApiError(f"Anthropic request failed: {e}") from e

    return _extract_json_object(text)
