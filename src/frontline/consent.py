"""Recording / contact consent disclosure (Phase 2-light for pilots)."""

from __future__ import annotations

import os


def consent_enabled() -> bool:
    # Opt-in: default off so hermetic tests match pack greeting text.
    # Set FRONTLINE_CONSENT_DISCLOSURE=1 for pilots.
    raw = os.getenv("FRONTLINE_CONSENT_DISCLOSURE", "0").strip().lower()
    return raw in {"1", "true", "yes", "on"}


def consent_preamble() -> str:
    """One-line disclosure prepended to greetings when enabled."""
    if not consent_enabled():
        return ""
    custom = os.getenv("FRONTLINE_CONSENT_TEXT", "").strip()
    if custom:
        return custom
    return (
        "This contact may be monitored or recorded for quality and safety. "
        "By continuing you consent to processing for support and product-safety analysis."
    )


def with_consent(greeting: str) -> str:
    pre = consent_preamble()
    if not pre:
        return greeting
    g = (greeting or "").strip()
    if pre.lower() in g.lower():
        return g
    return f"{pre} {g}".strip()


__all__ = ["consent_enabled", "consent_preamble", "with_consent"]
