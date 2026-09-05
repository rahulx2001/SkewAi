"""Frontline intake structures and slot models."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class IntakeSlots:
    """Standard slot model for complaint intake across voice and text channels."""

    entity_1: str = ""  # Model Year
    entity_2: str = ""  # Make
    entity_3: str = ""  # Model
    category: str = ""  # Primary system category
    description: str = ""  # Reported symptom / concern
    vin: str | None = None  # 17-character VIN if observed/confirmed
    subcategories: list[str] = field(default_factory=list)
    confidence: dict[str, float] = field(default_factory=dict)
    is_confirmed: bool = False

    def to_dict(self) -> dict[str, Any]:
        return {
            "entity_1": self.entity_1,
            "entity_2": self.entity_2,
            "entity_3": self.entity_3,
            "category": self.category,
            "description": self.description,
            "vin": self.vin,
            "subcategories": self.subcategories,
            "confidence": self.confidence,
            "is_confirmed": self.is_confirmed,
        }
