"""Upstash Redis REST API wrapper. Thin `requests`-based client, no
Redis client library needed -- matches finnhub_client.py's
plain-`requests` convention. Used by ticker_dashboard.py and storage.py
to persist config/tickers.json, data/indicators.json, and the
ticker/market-news caches durably across a hosted deployment's
restarts, since Render's free tier has no persistent local disk.

Two pairs of operations: `get_json`/`set_json` store/return a whole
JSON-serializable value under a plain string key; `hset_json`/
`hget_json`/`hgetall_json`/`hdel_json` do the same per-field within a
Redis hash, for data (like the ticker cache and the ticker config's
per-group entries) that needs many independent, concurrently-writable
slots under one logical key rather than one big blob that a writer has
to read, modify, and write back as a whole -- see ticker_dashboard.py's
`save_ticker_snapshot`/`delete_ticker_snapshot` and
`add_ticker_to_group`/`remove_ticker_from_group`. `is_configured()` is
the single switch callers check to decide whether to use Redis at all
(per `UPSTASH_REDIS_REST_URL` being set) -- unset is local development's
default, where this module is never called.

All six raise `KvStoreError` on any request failure or malformed
response; callers decide what that should mean for their own data. (In
ticker_dashboard.py: a failed ticker_config load/save propagates -- a
broken config load should fail loudly rather than silently render an
empty watchlist -- while the ticker/news caches catch it and degrade to
their existing pending/error states, same as a missing local file.)
"""

import json
import os

import requests
from requests.adapters import HTTPAdapter

_TIMEOUT = 10

# Shared across every call -- Story 12's per-symbol ticker-cache writes
# mean up to one HSET per ticker per group-check request (e.g. 15 for
# the largest config group), each otherwise paying a fresh DNS+TCP+TLS
# handshake to the same Upstash host. See finnhub_client.py's identical
# _session for the full reasoning; Session objects are documented
# thread-safe for this kind of concurrent reuse.
#
# Those HSET writes themselves run sequentially (see
# ticker_dashboard.check_for_ticker_updates's docstring -- only the
# fetch phase is concurrent), but Section 11.13's sector-peer P/E
# lookup (`ticker_dashboard._sector_benchmark`) calls `hget_json`
# *from inside* that concurrent fetch phase, one per individual-company
# ticker, gated by the same up-to-25-concurrent
# `ticker_dashboard._fetch_concurrency_limit` semaphore finnhub_client.py's
# calls are. `requests`' default HTTPAdapter caps a host's pool at 10,
# below that ceiling -- raised here for the same reason and to the same
# value as finnhub_client.py's, confirmed live via urllib3's "Connection
# pool is full, discarding connection" warning once this pattern was
# actually exercised concurrently.
_session = requests.Session()
_session.mount("https://", HTTPAdapter(pool_maxsize=25))


class KvStoreError(Exception):
    """Raised for any Upstash REST request/response problem."""


def _clean_env_value(value: str) -> str:
    """Strips whitespace and a single matching pair of surrounding
    quote characters. Defensive against a value pasted into a host's
    env var UI (e.g. Render's) with literal quotes still attached --
    those fields aren't shell-parsed, so quotes typed/pasted around a
    value become part of the literal string rather than being stripped
    the way `source .env` would, which otherwise surfaces as `requests`
    raising `InvalidSchema` on an oddly-quoted URL.
    """
    value = value.strip()
    if len(value) >= 2 and value[0] == value[-1] and value[0] in "\"'":
        value = value[1:-1]
    return value


def is_configured() -> bool:
    return bool(os.environ.get("UPSTASH_REDIS_REST_URL"))


def _rest_url() -> str:
    url = os.environ.get("UPSTASH_REDIS_REST_URL")
    if not url:
        raise KvStoreError("UPSTASH_REDIS_REST_URL not set")
    return _clean_env_value(url).rstrip("/")


def _headers() -> dict:
    token = os.environ.get("UPSTASH_REDIS_REST_TOKEN")
    if not token:
        raise KvStoreError("UPSTASH_REDIS_REST_TOKEN not set")
    return {"Authorization": f"Bearer {_clean_env_value(token)}"}


def get_json(key: str) -> dict | None:
    """`None` if `key` doesn't exist yet in Redis."""
    try:
        response = _session.get(f"{_rest_url()}/get/{key}", headers=_headers(), timeout=_TIMEOUT)
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
        response = _session.post(
            f"{_rest_url()}/set/{key}",
            headers=_headers(),
            data=json.dumps(value),
            timeout=_TIMEOUT,
        )
        response.raise_for_status()
    except requests.RequestException as e:
        raise KvStoreError(f"set failed for key={key}: {e}") from e


def hset_json(key: str, field: str, value: dict) -> None:
    """Sets one field of the hash at `key` to `value`, JSON-encoded --
    an atomic per-field write, unlike set_json's whole-key replace.
    Never reads or touches any other field of the same hash, so
    concurrent callers writing different fields (e.g. different ticker
    symbols sharing one cache key) can't clobber each other's unrelated
    data the way a read-modify-write of a single JSON blob could.
    """
    try:
        response = _session.post(
            f"{_rest_url()}/hset/{key}/{field}",
            headers=_headers(),
            data=json.dumps(value),
            timeout=_TIMEOUT,
        )
        response.raise_for_status()
    except requests.RequestException as e:
        raise KvStoreError(f"hset failed for key={key} field={field}: {e}") from e


def hdel_json(key: str, field: str) -> None:
    """Removes one field of the hash at `key`. A no-op if the field
    (or the hash itself) doesn't exist -- used to clean up a hash
    field that's no longer needed at all, e.g. a ticker's cached
    snapshot once it's been removed from every watchlist group (see
    ticker_dashboard.remove_ticker_from_group), rather than leaving an
    orphaned entry sitting in the cache indefinitely.
    """
    try:
        response = _session.post(f"{_rest_url()}/hdel/{key}/{field}", headers=_headers(), timeout=_TIMEOUT)
        response.raise_for_status()
    except requests.RequestException as e:
        raise KvStoreError(f"hdel failed for key={key} field={field}: {e}") from e


def hget_json(key: str, field: str) -> dict | None:
    """One field of the hash at `key`, JSON-decoded. `None` if the
    field (or the hash itself) doesn't exist -- lets a caller read
    (and later write back) just one field without ever fetching every
    other field the way `hgetall_json` does, e.g. checking one group
    exists before mutating just its own ticker list.
    """
    try:
        response = _session.get(f"{_rest_url()}/hget/{key}/{field}", headers=_headers(), timeout=_TIMEOUT)
        response.raise_for_status()
    except requests.RequestException as e:
        raise KvStoreError(f"hget failed for key={key} field={field}: {e}") from e

    try:
        result = response.json()["result"]
    except (ValueError, KeyError) as e:
        raise KvStoreError(f"unexpected response for key={key} field={field}: {e}") from e
    if result is None:
        return None

    try:
        return json.loads(result)
    except json.JSONDecodeError as e:
        raise KvStoreError(f"corrupt hash field value for key={key} field={field}: {e}") from e


def hgetall_json(key: str) -> dict:
    """Every field of the hash at `key`, JSON-decoded, as {field: value}.
    `{}` if the hash doesn't exist or has no fields -- Redis's HGETALL
    itself makes no distinction between those two, and callers here
    don't need one either.
    """
    try:
        response = _session.get(f"{_rest_url()}/hgetall/{key}", headers=_headers(), timeout=_TIMEOUT)
        response.raise_for_status()
    except requests.RequestException as e:
        raise KvStoreError(f"hgetall failed for key={key}: {e}") from e

    try:
        flat = response.json()["result"]
    except (ValueError, KeyError) as e:
        raise KvStoreError(f"unexpected response for key={key}: {e}") from e

    try:
        return {flat[i]: json.loads(flat[i + 1]) for i in range(0, len(flat), 2)}
    except (json.JSONDecodeError, IndexError, TypeError) as e:
        raise KvStoreError(f"corrupt hash value for key={key}: {e}") from e
