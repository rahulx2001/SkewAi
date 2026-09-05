"""Cross-pack concept ontology (item 34).

Raw category strings differ per vertical (NHTSA components vs CFPB issues),
so exact string equality makes cross-pack analysis vacuous. This module maps
each pack's taxonomy groups onto a small set of SHARED meta-concepts; only
groups explicitly listed under a concept belong to it. Anything unlisted
stays pack-specific and can never merge with another pack's categories.

The mapping is deliberately conservative: a shared concept means the two
groups describe the same KIND of customer harm (e.g. safety/security
incidents), not the same words.
"""

from __future__ import annotations

from typing import Any


def _slug(name: str) -> str:
    return "_".join("".join(c.lower() if c.isalnum() else " " for c in name).split())


# concept -> {pack_id -> [taxonomy group names]}
CROSS_PACK_CONCEPTS: dict[str, dict[str, list[str]]] = {
    # Customer-safety incidents in any vertical: physical-safety equipment
    # failures (airbags, belts) and financial-safety violations (fraud,
    # identity theft). Both are "the product harmed the customer".
    "safety_security": {
        "automotive_nhtsa": ["Safety equipment"],
        "finance_cfpb": ["Fraud & Identity"],
    },
    # Money the customer should not have paid.
    "billing": {
        "finance_cfpb": ["Billing & Fees"],
    },
    # Core product reliability: the thing itself broke.
    "product_reliability": {
        "automotive_nhtsa": ["Drivetrain", "Braking & Steering", "Electrical"],
    },
    # The customer's record/account representation is wrong or unmanageable.
    "account_information": {
        "finance_cfpb": ["Account Management", "Credit Reporting"],
    },
    # Human service experience around the product.
    "service_experience": {
        "finance_cfpb": ["Customer Service"],
    },
    # Physical structure / visibility of the vehicle.
    "vehicle_body": {
        "automotive_nhtsa": ["Body & Visibility"],
    },
}


def _group_concept(pack_id: str, group_name: str) -> str | None:
    for concept, packs in CROSS_PACK_CONCEPTS.items():
        if group_name in (packs.get(pack_id) or []):
            return concept
    return None


def concept_for(pack_id: str, category: str | None, taxonomy: dict[str, Any] | None = None) -> str:
    """Map a raw category to its cross-pack concept.

    Resolution: pack taxonomy group containing the category -> shared
    concept. Unknown categories (or packs) fall back to a pack-scoped
    concept (``f"{pack_id}:{normalized}"``) which can never merge across
    packs — unrelated categories never produce a false shared signal.
    """
    raw = (category or "").strip()
    if not raw:
        return f"{pack_id}:unknown"
    norm = raw.upper()
    groups: list[dict[str, Any]] = []
    if isinstance(taxonomy, dict):
        groups = taxonomy.get("groups") or []
    for group in groups:
        cats = [str(c).upper() for c in (group.get("categories") or [])]
        if norm in cats:
            concept = _group_concept(pack_id, str(group.get("name") or ""))
            if concept:
                return concept
            return f"{pack_id}:{_slug(str(group.get('name') or raw))}"
    # Not in the pack taxonomy: pack-scoped slug (never cross-pack).
    return f"{pack_id}:{_slug(raw)}"


def is_cross_pack_concept(concept: str) -> bool:
    """True only for shared concepts (no pack prefix)."""
    return ":" not in concept and concept in CROSS_PACK_CONCEPTS


__all__ = [
    "CROSS_PACK_CONCEPTS",
    "concept_for",
    "is_cross_pack_concept",
]
