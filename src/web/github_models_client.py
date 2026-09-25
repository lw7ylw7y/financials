"""Thin client for GitHub Models' OpenAI-compatible chat-completions
endpoint, used as the fallback when a Gemini call fails.

Returns the raw JSON text of the model's reply; callers validate it
against their own pydantic schema, the same as for a Gemini response.
The schema is spelled out in the system prompt rather than passed as a
structured-output parameter, since not every model GitHub hosts
supports the latter.

Auth is a token with the `models` permission: `GITHUB_MODELS_TOKEN`
(a fine-grained personal access token, for a hosted web app), or
`GITHUB_TOKEN` (what GitHub Actions provides when the workflow grants
`models: read`).
"""

import json
import os

import requests
from pydantic import BaseModel

GITHUB_MODELS_URL = "https://models.github.ai/inference/chat/completions"
DEFAULT_MODEL = "openai/gpt-4.1-mini"
REQUEST_TIMEOUT_SECONDS = 60

_session = requests.Session()


class GithubModelsError(Exception):
    """Raised for any GitHub Models request/response problem."""


def _token() -> str:
    token = os.environ.get("GITHUB_MODELS_TOKEN") or os.environ.get("GITHUB_TOKEN")
    if not token:
        raise GithubModelsError("no GITHUB_MODELS_TOKEN or GITHUB_TOKEN configured")
    return token.strip()


def generate_json(system_prompt: str, user_prompt: str, schema: type[BaseModel]) -> str:
    """Return the model's JSON reply text for `user_prompt`, shaped to `schema`."""
    token = _token()
    model = os.environ.get("GITHUB_MODELS_MODEL") or DEFAULT_MODEL
    schema_json = json.dumps(schema.model_json_schema())
    system = (
        f"{system_prompt}\n\nRespond with a single JSON object and nothing else, "
        f"conforming to this JSON Schema:\n{schema_json}"
    )

    try:
        response = _session.post(
            GITHUB_MODELS_URL,
            headers={
                "Authorization": f"Bearer {token}",
                "Accept": "application/vnd.github+json",
                "X-GitHub-Api-Version": "2022-11-28",
            },
            json={
                "model": model,
                "messages": [
                    {"role": "system", "content": system},
                    {"role": "user", "content": user_prompt},
                ],
                "response_format": {"type": "json_object"},
            },
            timeout=REQUEST_TIMEOUT_SECONDS,
        )
        response.raise_for_status()
        content = response.json()["choices"][0]["message"]["content"]
    except (ValueError, KeyError, IndexError, TypeError) as e:
        # `requests`' JSONDecodeError is both a ValueError and a
        # RequestException, so this must precede the request-failure branch.
        raise GithubModelsError(f"unexpected GitHub Models response shape: {e}") from e
    except requests.RequestException as e:
        raise GithubModelsError(f"GitHub Models request failed: {e}") from e

    if not content:
        raise GithubModelsError("GitHub Models returned no text content")
    return content
