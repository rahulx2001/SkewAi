"""Retention, erasure, residency (review §7).

Per-pack + per-data-class retention (turns vs cases vs audit differ under
GLBA/TCPA/GDPR/CCPA). DSR erasure keeps hash-chain integrity via
tombstone + redaction (never row delete on agent_actions).
"""

from __future__ import annotations

import os
from typing import Any


# Default days per data class; env-overridable per class.
_DEFAULTS: dict[str, int] = {
    "turns": 90,        # conversational turns (TCPA/GDPR-short)
    "cases": 2555,      # 7y case record (safety/GLBA-long)
    "audit": 2555,      # ledger never early-deleted; tombstone only
    "voice_audio": 30,  # biometric → shortest
    "metrics": 400,
    "alerts": 180,
}


def _env_days(key: str, default: int) -> int:
    raw = (os.getenv(key) or "").strip()
    return int(raw) if raw.isdigit() and int(raw) >= 1 else default


def retention_days(data_class: str, *, pack_id: str | None = None) -> int:
    """Pack override via RETENTION_<PACK>_<CLASS>_DAYS, else class default."""
    dc = str(data_class or "").lower()
    base = _DEFAULTS.get(dc, 365)
    if pack_id:
        pk = "".join(c.upper() if c.isalnum() else "_" for c in pack_id)
        specific = (os.getenv(f"RETENTION_{pk}_{dc.upper()}_DAYS") or "").strip()
        if specific.isdigit() and int(specific) >= 1:
            return int(specific)
    return _env_days(f"RETENTION_{dc.upper()}_DAYS", base)


def retention_table(pack_ids: list[str] | None = None) -> dict[str, Any]:
    packs = pack_ids or ["automotive_nhtsa", "finance_cfpb"]
    return {
        "classes": sorted(_DEFAULTS),
        "defaults": dict(_DEFAULTS),
        "packs": {p: {c: retention_days(c, pack_id=p) for c in _DEFAULTS} for p in packs},
        "merkle_anchor_residency": (os.getenv("MERKLE_ANCHOR_RESIDENCY") or "us-tenant-local").strip(),
        "sub_processors": [
            {"name": "LLM vendor (when FRONTLINE_LLM_ENABLED=1)", "purpose": "optional narration only",
             "data": "de-identified turn text; no audio"},
            {"name": "carrier (Twilio, when configured)", "purpose": "telephony transport",
             "data": "call audio + metadata"},
        ],
    }


def erase_customer(customer_ref_hash: str) -> dict[str, Any]:
    """DSR erasure plan: hash-keyed redaction, ledger tombstoned not deleted."""
    return {
        "customer_ref_hash": customer_ref_hash,
        "turns": "redact text → '[erased]'",
        "cases": "redact PII fields, keep severity/counts",
        "agent_actions": "tombstone (erased=1), keep hash chain",
        "voice_audio": "delete binaries",
        "note": "run via src/frontline/dsr.py + src/data/prune.py; verify with audit export",
    }


__all__ = ["retention_days", "retention_table", "erase_customer"]
