"""Tamper-evident hash chain for agent_actions.

Each row stores:
  prev_hash — row_hash of the previous action for this interaction (or GENESIS)
  row_hash  — sha256 of canonical payload + prev_hash

Verification walks the chain and re-computes hashes. Any insert/delete/edit
breaks the chain.
"""

from __future__ import annotations

import hashlib
import json
from typing import Any

GENESIS = "0" * 64


def _canon(action: dict[str, Any]) -> str:
    """Stable string for hashing (order-independent of DB column order)."""
    payload = {
        "action_id": action.get("action_id") or "",
        "interaction_id": action.get("interaction_id") or "",
        "case_id": action.get("case_id") or "",
        "agent": action.get("agent") or "",
        "action_type": action.get("action_type") or "",
        "input_summary": action.get("input_summary") or "",
        "output_summary": action.get("output_summary") or "",
        "evidence_ids": action.get("evidence_ids")
        if isinstance(action.get("evidence_ids"), str)
        else json.dumps(action.get("evidence_ids") or []),
        "ok": bool(action.get("ok", True)),
        "error": action.get("error") or "",
        "duration_ms": action.get("duration_ms"),
        "ts": str(action.get("ts") or ""),
    }
    return json.dumps(payload, sort_keys=True, separators=(",", ":"))


def compute_row_hash(action: dict[str, Any], prev_hash: str) -> str:
    raw = f"{prev_hash}|{_canon(action)}"
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def verify_chain(rows: list[dict[str, Any]]) -> dict[str, Any]:
    """Verify an ordered list of agent_actions rows for one interaction.

    Returns {ok, checked, first_bad_action_id, detail}.
    """
    prev = GENESIS
    for i, row in enumerate(rows):
        expected_prev = row.get("prev_hash") or GENESIS
        if expected_prev != prev and i > 0:
            return {
                "ok": False,
                "checked": i,
                "first_bad_action_id": row.get("action_id"),
                "detail": f"prev_hash mismatch at index {i}",
            }
        expected = compute_row_hash(row, expected_prev)
        actual = row.get("row_hash") or ""
        if actual != expected:
            return {
                "ok": False,
                "checked": i + 1,
                "first_bad_action_id": row.get("action_id"),
                "detail": f"row_hash mismatch at index {i}",
            }
        prev = actual or expected
    return {"ok": True, "checked": len(rows), "first_bad_action_id": None, "detail": "ok"}


__all__ = ["GENESIS", "compute_row_hash", "verify_chain"]
