"""Sentiment Monitor — lexicon-based frustration scoring.

Scores every customer turn with a deterministic VADER-style scorer (no LLM,
no audio ML — text only, so it works identically for voice and text channels).
Stores frustration_score per turn; rolling average of the last 3 customer
turns is the live frustration level; peak stored on the interaction.

Crossing FRONTLINE_FRUSTRATION_THRESHOLD (default 0.65) once per interaction:
Intake delivers a fast-path empathy + handoff offer, the console gets a
frustration_update highlight, and the interaction is marked for supervisor
attention.
"""

from __future__ import annotations

from typing import Any

from src.agents.base import Agent, InteractionContext
from src.config import settings
from src.ledger import record_action


# ── Mini VADER-style lexicon ──────────────────────────────────────────────
# Tuned for support-call frustration. Negative values indicate frustration;
# compound score is normalized to [0, 1] where 1 = maximally frustrated.

_LEXICON: dict[str, float] = {
    # anger / frustration
    "angry": 0.9, "furious": 1.0, "outraged": 1.0, "mad": 0.8,
    "frustrated": 0.85, "frustrating": 0.85, "annoyed": 0.7, "annoying": 0.7,
    "ridiculous": 0.8, "unacceptable": 0.85, "fed up": 0.9, "sick of": 0.9,
    "tired of": 0.7, "done with": 0.8, "enough": 0.6,
    # disappointment / escalation intent
    "lawyer": 0.95, "lawsuit": 0.95, "sue": 0.95, "attorney": 0.9,
    "news": 0.7, "media": 0.7, "twitter": 0.6, "facebook": 0.6,
    "complaint": 0.7, "better business": 0.8, "bbb": 0.8,
    "regulator": 0.85, "regulatory": 0.85, "fca": 0.85, "nhtsa": 0.85,
    "cfpb": 0.85, "consumer affairs": 0.8,
    # safety / urgency
    "dangerous": 0.9, "unsafe": 0.9, "scared": 0.8, "terrified": 0.95,
    "could have died": 1.0, "almost crashed": 0.95, "could have been killed": 1.0,
    # intensifiers (multiplied in scoring)
    "really": 1.15, "very": 1.15, "extremely": 1.2, "absolutely": 1.2,
    "completely": 1.15, "totally": 1.1, "incredibly": 1.2,
    # negation dampeners
    "not happy": 0.7, "not satisfied": 0.75, "not impressed": 0.7,
    # exclamation / caps handled separately
}

# Punctuation / caps multipliers
_EXCLAM_CAPS_BUMP = 0.15
_ALLCAPS_BUMP = 0.1


def score_text(text: str) -> float:
    """Return a frustration score in [0, 1] for a customer utterance.

    Deterministic. No LLM.
    """
    if not text or not text.strip():
        return 0.0
    lower = text.lower()

    # ── Lexicon hit scoring ──────────────────────────────────────────────
    hits: list[float] = []
    for term, score in _LEXICON.items():
        # Count occurrences of the term (whole-word-ish for short terms).
        if " " in term or len(term) > 4:
            count = lower.count(term)
        else:
            # word boundary for single words
            import re
            count = len(re.findall(rf"\b{re.escape(term)}\b", lower))
        if count:
            hits.append(score * count)

    if not hits:
        base = 0.0
    else:
        # Take the max hit and apply a small bonus for multiple distinct hits.
        base = max(hits)
        if len(hits) > 1:
            base = min(1.0, base + 0.05 * (len(hits) - 1))

    # ── Punctuation / caps ─────────────────────────────────────────────────
    excl = text.count("!")
    if excl >= 1:
        base = min(1.0, base + _EXCLAM_CAPS_BUMP * min(excl, 3) / 3)

    # ALL-CAPS words (length >= 4) suggest shouting
    import re
    caps_words = re.findall(r"\b[A-Z]{4,}\b", text)
    if caps_words:
        base = min(1.0, base + _ALLCAPS_BUMP * min(len(caps_words), 3) / 3)

    # ── Profanity proxy ──────────────────────────────────────────────────
    # Crude check: presence of "$", "*", "@", "#" in clusters signals redaction
    # of profanity in customer transcripts. Bump slightly.
    if any(ch in text for ch in ("$*@#")):
        base = min(1.0, base + 0.1)

    return round(base, 3)


# ── Sentiment agent ────────────────────────────────────────────────────────


class SentimentAgent(Agent):
    """Scores customer turns and tracks rolling frustration."""

    name = "sentiment"

    async def run(self, customer_turn: str, **kwargs: Any) -> dict[str, Any]:
        score = score_text(customer_turn)

        # Record on the context (for the rolling window)
        ctx = self.ctx
        # Attach to the most recent customer turn
        for turn in reversed(ctx.turns):
            if turn["speaker"] == "customer":
                turn["frustration_score"] = score
                break

        # Rolling avg of last 3 customer turns
        recent_scores = [
            t.get("frustration_score", 0.0)
            for t in ctx.turns
            if t["speaker"] == "customer" and "frustration_score" in t
        ][-3:]
        rolling = sum(recent_scores) / len(recent_scores) if recent_scores else 0.0
        ctx.frustration_score = round(rolling, 3)
        if rolling > ctx.peak_frustration:
            ctx.peak_frustration = round(rolling, 3)

        # Threshold crossing — fires once per interaction
        triggered = (
            not ctx.frustration_flagged
            and rolling >= settings.frustration_threshold
        )
        if triggered:
            ctx.frustration_flagged = True
            record_action(self._action(
                action_type="frustration_flagged",
                input_summary=f"rolling frustration {rolling:.2f} >= threshold {settings.frustration_threshold}",
                output_summary="handoff offer will be emitted by orchestrator",
                evidence_ids=[],
            ))
        else:
            # Only ledger threshold-relevant scoring to avoid noise
            record_action(self._action(
                action_type="turn_scored",
                input_summary=f"customer turn scored",
                output_summary=f"score={score}, rolling={rolling:.2f}, peak={ctx.peak_frustration:.2f}",
                evidence_ids=[],
            ))

        return {
            "score": score,
            "rolling": round(rolling, 3),
            "peak": ctx.peak_frustration,
            "threshold_crossed": triggered,
            "handoff_offer": (
                "I can flag this for a human specialist right away — meanwhile let me make sure I have the details right."
                if triggered else None
            ),
        }
