"""Thin client for the FRED series/observations and release/dates endpoints."""

import os
from datetime import date

import requests

FRED_BASE_URL = "https://api.stlouisfed.org/fred"


class FredApiError(Exception):
    """Raised for any FRED request/response problem for a single series."""


def fetch_latest_observation(series_id: str, api_key: str | None = None) -> dict:
    """Fetch the most recent observation for a FRED series.

    Returns {"date": "YYYY-MM-DD", "value": float}.
    Raises FredApiError on a missing key, request failure, or a response
    with no usable value (FRED uses "." for a not-yet-available reading).
    """
    api_key = api_key or os.environ.get("FRED_API_KEY")
    if not api_key:
        raise FredApiError("FRED_API_KEY not set")

    params = {
        "series_id": series_id,
        "api_key": api_key,
        "file_type": "json",
        "sort_order": "desc",
        "limit": 1,
    }
    try:
        response = requests.get(
            f"{FRED_BASE_URL}/series/observations", params=params, timeout=10
        )
        response.raise_for_status()
    except requests.RequestException as e:
        raise FredApiError(f"request failed for series {series_id}: {e}") from e

    observations = response.json().get("observations") or []
    if not observations:
        raise FredApiError(f"no observations returned for series {series_id}")

    latest = observations[0]
    raw_value = latest.get("value")
    if raw_value is None or raw_value == ".":
        raise FredApiError(
            f"missing value for series {series_id} on {latest.get('date')}"
        )

    try:
        value = float(raw_value)
    except ValueError as e:
        raise FredApiError(
            f"non-numeric value '{raw_value}' for series {series_id}"
        ) from e

    return {"date": latest["date"], "value": value}


def fetch_next_release_date(
    release_id: str, api_key: str | None = None, today: str | None = None
) -> str | None:
    """Fetch the next scheduled date for a FRED release.

    Returns the earliest release date on or after `today` (ISO
    "YYYY-MM-DD", defaults to the current date), or None if the release
    has no such date. The endpoint returns dates spanning the release's
    full history rather than just upcoming ones, so "next" is picked out
    by filtering client-side rather than trusting API ordering.
    """
    api_key = api_key or os.environ.get("FRED_API_KEY")
    if not api_key:
        raise FredApiError("FRED_API_KEY not set")
    today = today or date.today().isoformat()

    params = {
        "release_id": release_id,
        "api_key": api_key,
        "file_type": "json",
        "include_release_dates_with_no_data": "true",
    }
    try:
        response = requests.get(
            f"{FRED_BASE_URL}/release/dates", params=params, timeout=10
        )
        response.raise_for_status()
    except requests.RequestException as e:
        raise FredApiError(f"request failed for release {release_id}: {e}") from e

    release_dates = response.json().get("release_dates") or []
    upcoming = [
        entry["date"] for entry in release_dates if entry.get("date", "") >= today
    ]
    return min(upcoming) if upcoming else None
