"""Upstash Redis REST API wrapper (Story 9, Section 11.3 of the tech
design). Thin `requests`-based client, no Redis client library needed
-- matches finnhub_client.py/yahoo_client.py's plain-`requests`
convention. Used by ticker_dashboard.py to persist config/tickers.json's
content and the ticker/market-news caches durably across a hosted
deployment's restarts, since Render's free tier has no persistent local
disk.

Only two operations, both storing/returning a JSON-serializable value
under a plain string key: `get_json`/`set_json`. `is_configured()` is
the single switch callers check to decide whether to use Redis at all
(per `UPSTASH_REDIS_REST_URL` being set) -- unset is local development's
default, where this module is never called.

Both raise `KvStoreError` on any request failure or malformed response;
callers decide what that should mean for their own data. (In
ticker_dashboard.py: a failed ticker_config load/save propagates --
Story 9's AC says a broken config load should fail loudly rather than
silently render an empty watchlist -- while the ticker/news caches
catch it and degrade to their existing pending/error states, same as a
missing local file.)
"""

import json
import os

import requests

_TIMEOUT = 10


class KvStoreError(Exception):
    """Raised for any Upstash REST request/response problem."""


def is_configured() -> bool:
    return bool(os.environ.get("UPSTASH_REDIS_REST_URL"))


def _rest_url() -> str:
    url = os.environ.get("UPSTASH_REDIS_REST_URL")
    if not url:
        raise KvStoreError("UPSTASH_REDIS_REST_URL not set")
    return url.rstrip("/")


def _headers() -> dict:
    token = os.environ.get("UPSTASH_REDIS_REST_TOKEN")
    if not token:
        raise KvStoreError("UPSTASH_REDIS_REST_TOKEN not set")
    return {"Authorization": f"Bearer {token}"}


def get_json(key: str) -> dict | None:
    """`None` if `key` doesn't exist yet in Redis."""
    try:
        response = requests.get(f"{_rest_url()}/get/{key}", headers=_headers(), timeout=_TIMEOUT)
        response.raise_for_status()
    except requests.RequestException as e:
        raise KvStoreError(f"get failed for key={key}: {e}") from e

    try:
        result = response.json().get("result")
    except (ValueError, AttributeError) as e:
        raise KvStoreError(f"unexpected response for key={key}: {e}") from e
    if result is None:
        return None

    try:
        return json.loads(result)
    except json.JSONDecodeError as e:
        raise KvStoreError(f"corrupt value for key={key}: {e}") from e


def set_json(key: str, value: dict) -> None:
    """Overwrites `key` with `value`, JSON-encoded."""
    try:
        response = requests.post(
            f"{_rest_url()}/set/{key}",
            headers=_headers(),
            data=json.dumps(value),
            timeout=_TIMEOUT,
        )
        response.raise_for_status()
    except requests.RequestException as e:
        raise KvStoreError(f"set failed for key={key}: {e}") from e
