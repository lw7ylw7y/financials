"""Google sign-in (OAuth 2.0 authorization-code flow) for the hosted
dashboard: builds the consent URL, and exchanges the returned code for
the signed-in user's verified email.

The email comes from Google's userinfo endpoint, called server-to-server
over TLS with the access token just issued, so the ID token's signature
never needs verifying locally. Uses plain `requests`, matching the other
clients, rather than an OAuth library.
"""

import os
from urllib.parse import urlencode

import requests

AUTHORIZE_URL = "https://accounts.google.com/o/oauth2/v2/auth"
TOKEN_URL = "https://oauth2.googleapis.com/token"
USERINFO_URL = "https://openidconnect.googleapis.com/v1/userinfo"
SCOPES = "openid email"
REQUEST_TIMEOUT_SECONDS = 15

_session = requests.Session()


class GoogleAuthError(Exception):
    """Raised for any failure to complete Google sign-in."""


def client_id() -> str | None:
    return os.environ.get("GOOGLE_CLIENT_ID") or None


def is_enabled() -> bool:
    """Sign-in is required as soon as a client ID is set, even if the rest
    of the configuration is missing (see `missing_config`), so a typo'd
    env var name locks the dashboard rather than opening it."""
    return client_id() is not None


def missing_config() -> list[str]:
    return [
        name
        for name in ("GOOGLE_CLIENT_SECRET", "ALLOWED_EMAIL", "SECRET_KEY")
        if not os.environ.get(name)
    ]


def allowed_email() -> str:
    return (os.environ.get("ALLOWED_EMAIL") or "").strip().lower()


def build_authorize_url(redirect_uri: str, state: str) -> str:
    params = {
        "client_id": client_id(),
        "redirect_uri": redirect_uri,
        "response_type": "code",
        "scope": SCOPES,
        "state": state,
        "prompt": "select_account",
    }
    return f"{AUTHORIZE_URL}?{urlencode(params)}"


def fetch_verified_email(code: str, redirect_uri: str) -> str | None:
    """Exchange an authorization `code` for the user's email, lowercased,
    or None if Google reports the address as unverified. Raises
    GoogleAuthError on any request or response problem."""
    try:
        token_response = _session.post(
            TOKEN_URL,
            data={
                "code": code,
                "client_id": client_id(),
                "client_secret": os.environ.get("GOOGLE_CLIENT_SECRET"),
                "redirect_uri": redirect_uri,
                "grant_type": "authorization_code",
            },
            timeout=REQUEST_TIMEOUT_SECONDS,
        )
        token_response.raise_for_status()
        access_token = token_response.json()["access_token"]

        info_response = _session.get(
            USERINFO_URL,
            headers={"Authorization": f"Bearer {access_token}"},
            timeout=REQUEST_TIMEOUT_SECONDS,
        )
        info_response.raise_for_status()
        info = info_response.json()
    except (ValueError, KeyError, TypeError) as e:
        raise GoogleAuthError(f"unexpected Google response: {e}") from e
    except requests.RequestException as e:
        raise GoogleAuthError(f"Google request failed: {e}") from e

    email = info.get("email")
    if not email or info.get("email_verified") is not True:
        return None
    return email.strip().lower()
