"""Triage agent types and structures."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass
class TriageResult:
    """Outcome of triage classification."""

    severity: str
    priority: str
    sentiment_peak: float = 0.0
    category: str = ""
    reason: str = ""
    safety_flag_tripped: bool = False
