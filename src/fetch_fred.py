"""Thin client for the FRED series/observations endpoint."""

import os

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
