"""Dynamic slot skipping (feature #22).

Skip slots already known from entity memory or a prior contact, reducing
turns-to-completion (eval gate ≤12).
"""

from __future__ import annotations

from typing import Any

from src.enterprise.memory import lookup_memory


def known_slots_from_memory(
    pack_id: str,
    *,
    entity_1: str | None = None,
    entity_2: str | None = None,
    entity_3: str | None = None,
) -> dict[str, str]:
    mem = lookup_memory(pack_id, entity_1=entity_1, entity_2=entity_2, entity_3=entity_3)
    if not mem:
        return {}
    out: dict[str, str] = {}
    for k in ("entity_1", "entity_2", "entity_3", "category"):
        v = mem.get(k)
        if v:
            out[k] = str(v)
    # memory table may store last_category
    if not out.get("category") and mem.get("last_category"):
        out["category"] = str(mem["last_category"])
    return out


def merge_slots_skip_known(
    required_slots: list[str],
    current: dict[str, str],
    known: dict[str, str],
) -> dict[str, Any]:
    """Fill empty required slots from known; return remaining to ask."""
    merged = dict(current)
    skipped: list[str] = []
    for name in required_slots:
        if (merged.get(name) or "").strip():
            continue
        if (known.get(name) or "").strip():
            merged[name] = known[name].strip()
            skipped.append(name)
    still_needed = [s for s in required_slots if not (merged.get(s) or "").strip()]
    return {
        "slots": merged,
        "skipped": skipped,
        "still_needed": still_needed,
        "turns_saved": len(skipped),
    }


def apply_dynamic_skip(
    pack_id: str,
    required_slots: list[str],
    current: dict[str, str],
) -> dict[str, Any]:
    known = known_slots_from_memory(
        pack_id,
        entity_1=current.get("entity_1") or None,
        entity_2=current.get("entity_2") or None,
        entity_3=current.get("entity_3") or None,
    )
    # If no entities yet, still try empty lookup (no-op)
    result = merge_slots_skip_known(required_slots, current, known)
    result["known_from_memory"] = known
    return result
