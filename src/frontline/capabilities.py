"""Capability availability registry (item 40).

Stub capabilities (pilot demos without a real backend) must never be sold
or displayed as production functionality. Every capability is either
``production`` or ``stub``; billing and UI consult this registry.
"""

from __future__ import annotations

from typing import Any

# capability -> {availability, backend, note}
CAPABILITIES: dict[str, dict[str, str]] = {
    "booking": {
        "availability": "stub",
        "backend": "ops appointments table only; no Cal.com, no double-book check",
        "note": "Pilot stub: books into the local ops table. Not a real calendar.",
    },
    "biometrics": {
        "availability": "stub",
        "backend": "ANI/feature hash proxy; no real speaker model",
        "note": "Pilot stub: voiceprint is a hash proxy, not speaker recognition.",
    },
    "cases": {"availability": "production", "backend": "ops warehouse", "note": ""},
    "investigations": {"availability": "production", "backend": "ops warehouse", "note": ""},
    "audits": {"availability": "production", "backend": "qubot auditor", "note": ""},
    "early_warning": {"availability": "production", "backend": "live_risk retriever", "note": ""},
    "simulate": {"availability": "production", "backend": "simulator", "note": ""},
}


def capability_status(name: str) -> dict[str, str]:
    info = CAPABILITIES.get(name, {})
    return {
        "capability": name,
        "availability": info.get("availability", "unknown"),
        "backend": info.get("backend", ""),
        "note": info.get("note", ""),
    }


def is_sellable(name: str) -> bool:
    """False for stubs — billing must never treat these as paid features."""
    return CAPABILITIES.get(name, {}).get("availability") == "production"


def sellable_capabilities() -> list[str]:
    return sorted(n for n, c in CAPABILITIES.items() if c.get("availability") == "production")


def stub_capabilities() -> list[str]:
    return sorted(n for n, c in CAPABILITIES.items() if c.get("availability") == "stub")


def list_capabilities() -> list[dict[str, Any]]:
    return [capability_status(n) for n in sorted(CAPABILITIES)]


__all__ = [
    "CAPABILITIES",
    "capability_status",
    "is_sellable",
    "sellable_capabilities",
    "stub_capabilities",
    "list_capabilities",
]
