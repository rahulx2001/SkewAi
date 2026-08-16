"""Multi-key entity identity: VIN/serial + make + model.

A pair matches only when the strong key (VIN or serial) and make and model
all agree. Sharing make (or make+model without VIN) is not enough.
"""

from __future__ import annotations

from typing import Any


def _norm(val: Any) -> str:
    return str(val or "").strip().upper()


def identity_key(record: dict[str, Any]) -> str:
    """VIN or serial, stripped/uppercased. Empty if missing."""
    return _norm(record.get("vin") or record.get("serial") or record.get("identity_key"))


def same_entity(a: dict[str, Any], b: dict[str, Any]) -> bool:
    """True iff VIN/serial, make (entity_2), and model (entity_3) all match."""
    vin = identity_key(a)
    if not vin or vin != identity_key(b):
        return False
    make_a = _norm(a.get("entity_2") or a.get("make"))
    make_b = _norm(b.get("entity_2") or b.get("make"))
    model_a = _norm(a.get("entity_3") or a.get("model"))
    model_b = _norm(b.get("entity_3") or b.get("model"))
    if not make_a or make_a != make_b:
        return False
    if not model_a or model_a != model_b:
        return False
    return True


def resolve_matches(records: list[dict[str, Any]]) -> list[tuple[int, int]]:
    """Index pairs (i, j), i < j, that resolve as the same entity."""
    pairs: list[tuple[int, int]] = []
    for i in range(len(records)):
        for j in range(i + 1, len(records)):
            if same_entity(records[i], records[j]):
                pairs.append((i, j))
    return pairs


__all__ = ["identity_key", "same_entity", "resolve_matches"]
