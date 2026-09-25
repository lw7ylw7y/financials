"""The Gemini models tried, in order, after the primary one fails.

Free-tier capacity and quota are tracked per model, and which models are
overloaded shifts through the day (a newer model can return 503 while
an older one answers instantly), so a longer list survives more of those
spells. The lighter, faster models come before the slower one. Overridable
with GEMINI_FALLBACK_MODELS, a comma-separated list.
"""

import os

DEFAULT_FALLBACK_MODELS = (
    "gemini-3.7-flash",
    "gemini-3.6-flash",
    "gemini-3.5-flash-lite",
    "gemini-3.5-flash",
)


def fallback_models() -> list[str]:
    configured = os.environ.get("GEMINI_FALLBACK_MODELS") or ""
    names = [name.strip() for name in configured.split(",") if name.strip()]
    return names or list(DEFAULT_FALLBACK_MODELS)
