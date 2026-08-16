"""Production / SOC-oriented runtime hardening helpers.

SOC 2 Type II is an auditor attestation over time — this module only enforces
*engineering* fail-closed controls that support Security criteria (CC6, CC7).
"""

from __future__ import annotations

import os
from typing import Any


def _env_bool(name: str, default: bool = False) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


def is_production_like() -> bool:
    """True when deploy should refuse open mode and weak secrets."""
    env = (os.getenv("ENV") or os.getenv("APP_ENV") or "").strip().lower()
    if env in {"production", "prod", "staging", "stage"}:
        return True
    return _env_bool("PILOT_HARDENED", False) or _env_bool("SOC2_MODE", False)


def validate_startup_security() -> dict[str, Any]:
    """Validate security env at process start.

    Returns a status dict. Raises ``RuntimeError`` when production-like deploy
    is misconfigured (fail closed).
    """
    from src.api.auth import _configured_key, auth_required, is_open_mode

    open_mode = is_open_mode()
    key = _configured_key()
    session = (os.getenv("SESSION_SECRET") or "").strip()
    auth_req = auth_required()
    prod = is_production_like()

    status: dict[str, Any] = {
        "production_like": prod,
        "auth_required": auth_req,
        "open_mode": open_mode,
        "api_key_configured": bool(key),
        "session_secret_configured": bool(session) or bool(key),
        "ok": True,
        "warnings": [],
    }

    if prod:
        problems: list[str] = []
        if open_mode or not auth_req:
            problems.append(
                "Open mode is not allowed when ENV=production/staging or "
                "PILOT_HARDENED=1 / SOC2_MODE=1. Set FRONTLINE_AUTH_REQUIRED=1 "
                "and FRONTLINE_API_KEY, and do not set FRONTLINE_OPEN_MODE=1."
            )
        if not key or len(key) < 16:
            problems.append(
                "FRONTLINE_API_KEY must be set (≥16 chars) in hardened/production mode."
            )
        if not session and not key:
            problems.append("SESSION_SECRET or FRONTLINE_API_KEY required for sessions.")
        if session == "dev-only" or key == "dev-only":
            problems.append("Refusing weak secret value 'dev-only' in hardened mode.")
        if problems:
            status["ok"] = False
            status["errors"] = problems
            raise RuntimeError("Security startup check failed:\n- " + "\n- ".join(problems))

    if not prod and open_mode:
        status["warnings"].append(
            "Running in open mode (no API key). Fine for local demos only."
        )
    if auth_req and not session and key:
        status["warnings"].append(
            "SESSION_SECRET unset; sessions fall back to FRONTLINE_API_KEY material."
        )
    return status
