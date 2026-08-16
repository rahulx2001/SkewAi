"""Optional LLM narration layer (offline-safe).

Public surface: import from here, not the submodules. ``narrate``/the
``phrase_*`` helpers always return usable text — deterministic template on
any miss (no key, spend cap hit, HTTP error) — so agents never block on the
LLM. Gates: ``FRONTLINE_LLM_ENABLED`` + a provider key, plus turn and daily
spend caps enforced in ``provider.can_spend``.
"""

from src.ai.provider import NarrationResult, can_spend, get_spend, llm_enabled, narrate
from src.ai.narration import (
    phrase_followup_draft,
    phrase_intake_question,
    phrase_investigation_brief,
)

__all__ = [
    "NarrationResult",
    "can_spend",
    "get_spend",
    "llm_enabled",
    "narrate",
    "phrase_followup_draft",
    "phrase_intake_question",
    "phrase_investigation_brief",
]
