"""Intake Agent — the conversation driver.

Runs the conversation; fills the pack's slot frame. The LLM never owns state.

Extraction (deterministic first):
  - gazetteer match (whole-word substring) for entity slots + category
  - year-range validation for entity_1 (when pack uses year-range)
  - regex fallback for slot-specific patterns
  - LLM structured-extraction ONLY when regex finds nothing; output validated
    against the gazetteer before acceptance.

Dialogue policy (deterministic):
  - One question per turn for the highest-priority missing required slot.
  - Per-slot re-ask limits from the manifest.
  - Global cap FRONTLINE_MAX_TURNS then wrap up.

LLM used for: empathetic phrasing of questions/acknowledgments (low temp,
~80-token cap). Fast-path (no LLM): greeting, safety questions, advisory
notice, handoff offer, goodbye, case-number readback.

Kill-switch: utterance matches the pack's escalation lexicon → set flag, skip
remaining slots, notify Sentinel, read the pack's static escalation script.
"""

from __future__ import annotations

import re
from typing import Any

from src.agents.base import Agent, InteractionContext
from src.config import settings
from src.ledger import action_timer, record_action


# ── Extraction helpers ─────────────────────────────────────────────────────

_YEAR_RE = re.compile(r"\b(19[89]\d|20[0-2]\d)\b")


# ── Category synonyms (deterministic mapping of common words → gazetteer values) ──
# Customers say "brakes" / "engine"; the gazetteer stores canonical NHTSA
# category names like "SERVICE BRAKES". This map bridges the gap without an LLM.
# It is intentionally small and pack-specific in real deployments — the
# automotive pack ships this in code rather than the gazetteer for v2.
_CATEGORY_SYNONYMS: dict[str, str] = {
    # ── Automotive (NHTSA) ──
    "brakes": "SERVICE BRAKES",
    "brake": "SERVICE BRAKES",
    "abs": "SERVICE BRAKES",
    "engine": "ENGINE",
    "motor": "ENGINE",
    "transmission": "POWER TRAIN",
    "gearbox": "POWER TRAIN",
    "power train": "POWER TRAIN",
    "fuel": "FUEL SYSTEM",
    "gas tank": "FUEL SYSTEM",
    "steering": "STEERING",
    "suspension": "SUSPENSION",
    "shocks": "SUSPENSION",
    "struts": "SUSPENSION",
    "electrical": "ELECTRICAL SYSTEM",
    "wiring": "ELECTRICAL SYSTEM",
    "battery": "ELECTRICAL SYSTEM",
    "lights": "EXTERIOR LIGHTING",
    "headlights": "EXTERIOR LIGHTING",
    "taillights": "EXTERIOR LIGHTING",
    "airbag": "AIR BAGS",
    "air bag": "AIR BAGS",
    "airbags": "AIR BAGS",
    "seatbelt": "SEAT BELTS",
    "seat belt": "SEAT BELTS",
    "seatbelts": "SEAT BELTS",
    "tires": "TIRES",
    "tire": "TIRES",
    "wheels": "WHEELS",
    "wheel": "WHEELS",
    "windshield": "VISIBILITY",
    "wipers": "VISIBILITY",
    "visibility": "VISIBILITY",
    "child seat": "CHILD SEAT",
    "car seat": "CHILD SEAST",
    "structure": "STRUCTURE",
    "frame": "STRUCTURE",
    "speed control": "VEHICLE SPEED CONTROL",
    "cruise control": "VEHICLE SPEED CONTROL",
    "forward collision": "FORWARD COLLISION AVOIDANCE",
    "lane departure": "LANE DEPARTURE",
    "parking brake": "PARKING BRAKE",
    "esc": "ELECTRONIC STABILITY CONTROL",
    "stability control": "ELECTRONIC STABILITY CONTROL",
    "traction control": "TRACTION CONTROL SYSTEM",
    "hybrid": "HYBRID PROPULSION SYSTEM",
    # ── Finance (CFPB) ──
    "double charged": "Incorrect charges",
    "double charge": "Incorrect charges",
    "charged twice": "Incorrect charges",
    "extra fee": "Fees or interest",
    "hidden fee": "Fees or interest",
    "late fee": "Late fees",
    "overdraft fee": "Fees or interest",
    "annual fee": "Fees or interest",
    "interest rate": "Fees or interest",
    "unauthorized": "Unauthorized transactions",
    "unauthorized transaction": "Unauthorized transactions",
    "unauthorized charge": "Unauthorized transactions",
    "identity theft": "Identity theft",
    "stolen identity": "Identity theft",
    "someone opened": "Identity theft",
    "fraud": "Fraud or scam",
    "scam": "Fraud or scam",
    "scammed": "Fraud or scam",
    "phishing": "Fraud or scam",
    "billing dispute": "Billing disputes",
    "disputed charge": "Billing disputes",
    "wrong charge": "Billing disputes",
    "closed my account": "Closing an account",
    "account closed": "Closing an account",
    "can't close": "Closing an account",
    "opened an account": "Opening an account",
    "account opening": "Opening an account",
    "credit report": "Problem with credit reporting",
    "credit reporting": "Problem with credit reporting",
    "wrong information": "Incorrect information on your report",
    "customer service": "Customer service",
    "can't reach": "Customer service",
    "no response": "Communication tactics",
    "calls": "Communication tactics",
    "card declined": "Trouble using card",
    "card not working": "Trouble using card",
    "transfer failed": "Transaction issues",
    "transaction failed": "Transaction issues",
}


def _extract_year(text: str, year_range: tuple[int, int] | None) -> str | None:
    """Find a 4-digit year in text that falls within `year_range`."""
    for m in _YEAR_RE.finditer(text):
        y = int(m.group(1))
        if year_range is None or year_range[0] <= y <= year_range[1]:
            return str(y)
    return None


def _extract_via_gazetteer(text: str, ctx: InteractionContext, slot_name: str) -> str | None:
    """Find a gazetteer value that appears in `text` (whole-word match)."""
    gaz = ctx.pack.gazetteer_for_slot(slot_name)
    if gaz is None:
        return None
    return gaz.match_substring(text)


# ── Kill-switch ─────────────────────────────────────────────────────────────


def _check_kill_switch(text: str, ctx: InteractionContext) -> str | None:
    """If `text` matches the pack's escalation lexicon, return the matched term.

    Excludes common safe contexts (e.g. 'fraud department', 'fraud alert') so
    that answering safety questions doesn't false-trigger the kill-switch.
    """
    text_lower = text.lower()
    # Common safe phrases that contain kill-switch terms but aren't escalations.
    # The customer is answering a safety question, not reporting an incident.
    safe_phrases = [
        "fraud department", "fraud alert", "fraud division", "fraud team",
        "fraud prevention", "fraud protection",
    ]
    cleaned = text_lower
    for safe in safe_phrases:
        cleaned = cleaned.replace(safe, "")
    for term in ctx.pack.manifest.safety.escalation_lexicon:
        # whole-word-ish match on the cleaned text
        if re.search(rf"\b{re.escape(term.lower())}\b", cleaned):
            return term
    return None


# ── Intake agent ──────────────────────────────────────────────────────────


class IntakeAgent(Agent):
    """Drives the conversation. Fills the slot frame deterministically."""

    name = "intake"

    async def run(self, customer_turn: str = "", **kwargs: Any) -> dict[str, Any]:
        """Process one customer turn. Returns:
            {
              "extracted": {slot: value, ...},
              "question": str,                # next question to ask
              "fast_path": bool,             # True if no LLM was used
              "kill_switch": str | None,     # matched term if escalation
              "slots_filled_now": bool,
            }
        """
        ctx = self.ctx
        extracted: dict[str, str] = {}

        # ── Case-status lookup (returning caller with case number) ────────
        if customer_turn:
            try:
                from src.agents.case_status import try_case_status_from_utterance

                status_hit = try_case_status_from_utterance(customer_turn)
                if status_hit and status_hit.get("found"):
                    record_action(self._action(
                        action_type="question_asked",
                        input_summary="case_status_lookup",
                        output_summary=status_hit["reply"][:500],
                    ))
                    return {
                        "extracted": {},
                        "question": status_hit["reply"],
                        "fast_path": True,
                        "kill_switch": None,
                        "slots_filled_now": False,
                        "case_status": status_hit,
                    }
            except Exception:
                pass

        # ── Prefill from entity memory (dynamic slot skip) ───────────────
        self._prefill_from_memory()

        # ── Kill-switch check FIRST ──────────────────────────────────────
        kill_term = _check_kill_switch(customer_turn, ctx) if customer_turn else None
        if kill_term:
            ctx.safety_flags["escalation"] = True
            ctx.safety_flags[kill_term] = True
            record_action(self._action(
                action_type="safety_flag_raised",
                input_summary=f"customer utterance matched lexicon: '{kill_term}'",
                output_summary=f"safety_flag[{kill_term}]=True; intake will skip remaining slots",
                evidence_ids=[],
            ))
            return {
                "extracted": {},
                "question": ctx.pack.manifest.safety.escalation_script,
                "fast_path": True,
                "kill_switch": kill_term,
                "slots_filled_now": False,
            }

        # ── Slot extraction from the customer turn ────────────────────────
        if customer_turn:
            for slot in ctx.pack.manifest.slot_frame:
                if ctx.slots.get(slot.name):
                    continue  # already filled
                value = self._extract_slot(slot, customer_turn)
                if value:
                    extracted[slot.name] = value
                    ctx.slots[slot.name] = value

            if extracted:
                record_action(self._action(
                    action_type="slot_extracted",
                    input_summary=f"customer turn: '{customer_turn[:200]}'",
                    output_summary=f"extracted: {extracted}",
                    evidence_ids=[],
                ))

        # ── Pick the next question ────────────────────────────────────────
        # Always ask safety questions first if pack defines them AND no
        # escalation flag has been raised.
        safety_q = self._next_safety_question()
        if safety_q:
            record_action(self._action(
                action_type="question_asked",
                input_summary="safety question required by pack",
                output_summary=safety_q,
            ))
            return {
                "extracted": extracted,
                "question": safety_q,
                "fast_path": True,
                "kill_switch": None,
                "slots_filled_now": bool(extracted),
            }

        # Global turn cap: stop collecting and signal orchestrator to wrap up.
        customer_turn_count = sum(1 for t in ctx.turns if t["speaker"] == "customer")
        if customer_turn_count >= settings.max_turns and not ctx.has_required_slots():
            record_action(self._action(
                action_type="intake_completed",
                input_summary=f"max_turns={settings.max_turns} reached with incomplete slots",
                output_summary=f"slots: {ctx.slots}; force wrap-up",
            ))
            return {
                "extracted": extracted,
                "question": "",
                "fast_path": True,
                "kill_switch": None,
                "slots_filled_now": bool(extracted),
                "max_turns_reached": True,
            }

        # Otherwise pick highest-priority missing required slot.
        next_slot = self._next_required_slot()
        if next_slot is None and not ctx.has_required_slots():
            # All remaining slots exhausted re-asks → confidence escalate
            remaining = ctx.required_slots_remaining()
            if remaining:
                record_action(self._action(
                    action_type="handoff_offer_emitted",
                    input_summary=f"low confidence; exhausted re-asks for {remaining}",
                    output_summary="escalate_to_human",
                ))
                try:
                    from src.frontline.validation_queue import enqueue_insight

                    enqueue_insight(
                        kind="low_confidence",
                        interaction_id=ctx.interaction_id,
                        summary=f"low confidence; exhausted re-asks for {remaining}",
                    )
                except Exception:
                    pass
                return {
                    "extracted": extracted,
                    "question": (
                        "I'm having trouble capturing that clearly. "
                        "Let me connect you with a specialist who can help."
                    ),
                    "fast_path": True,
                    "kill_switch": None,
                    "slots_filled_now": bool(extracted),
                    "escalate_low_confidence": True,
                    "low_confidence_slot": remaining[0],
                }
        if next_slot:
            ctx.slot_attempts.setdefault(next_slot.name, 0)
            ctx.slot_attempts[next_slot.name] += 1
            attempts = ctx.slot_attempts[next_slot.name]
            max_re = getattr(next_slot, "max_re_asks", 2) or 2
            # Confidence-gated escalation: too many re-asks without a solid fill → handoff.
            # Count a re-ask as failed when this turn did not extract *this* slot.
            filled_this = next_slot.name in extracted
            if attempts > max_re and not filled_this:
                record_action(self._action(
                    action_type="handoff_offer_emitted",
                    input_summary=f"low confidence on slot '{next_slot.name}' after {attempts} attempts",
                    output_summary="escalate_to_human",
                ))
                try:
                    from src.frontline.validation_queue import enqueue_insight

                    enqueue_insight(
                        kind="low_confidence",
                        interaction_id=ctx.interaction_id,
                        summary=f"low confidence on slot '{next_slot.name}' after {attempts} attempts",
                    )
                except Exception:
                    pass
                return {
                    "extracted": extracted,
                    "question": (
                        "I'm having trouble capturing that clearly. "
                        "Let me connect you with a specialist who can help."
                    ),
                    "fast_path": True,
                    "kill_switch": None,
                    "slots_filled_now": bool(extracted),
                    "escalate_low_confidence": True,
                    "low_confidence_slot": next_slot.name,
                }
            q_text = next_slot.prompt
            try:
                from src.ai.narration import phrase_intake_question
                from src.ai.prompts import stamp_prompt_use

                last = ""
                if ctx.turns:
                    last = str(ctx.turns[-1].get("text") or "")
                res = phrase_intake_question(
                    slot_label=next_slot.name,
                    template=next_slot.prompt,
                    customer_last=last,
                )
                q_text = res.text or next_slot.prompt
                stamp_prompt_use(
                    ctx.interaction_id,
                    prompt_name="intake_phrasing",
                    model_id=res.model_id,
                    used_llm=res.used_llm,
                )
            except Exception:
                q_text = next_slot.prompt
            record_action(self._action(
                action_type="question_asked",
                input_summary=f"missing required slot '{next_slot.name}' (attempt {attempts})",
                output_summary=q_text[:500],
            ))
            return {
                "extracted": extracted,
                "question": q_text,
                "fast_path": True,                # LLM optional; fallback is pack prompt
                "kill_switch": None,
                "slots_filled_now": bool(extracted),
            }

        # All required slots filled.
        record_action(self._action(
            action_type="intake_completed",
            input_summary="all required slots filled",
            output_summary=f"slots: {ctx.slots}",
        ))
        return {
            "extracted": extracted,
            "question": "",
            "fast_path": True,
            "kill_switch": None,
            "slots_filled_now": bool(extracted),
        }

    def _prefill_from_memory(self) -> None:
        """Skip slots already known from contact_memory (feature #22)."""
        ctx = self.ctx
        if getattr(ctx, "_memory_prefill_done", False):
            return
        ctx._memory_prefill_done = True  # type: ignore[attr-defined]
        e1 = ctx.slots.get("entity_1")
        e2 = ctx.slots.get("entity_2")
        e3 = ctx.slots.get("entity_3")
        # Also try loading memory when only entity_2 is known
        try:
            from src.enterprise.memory import lookup_memory

            mem = lookup_memory(
                ctx.pack.id,
                entity_1=e1,
                entity_2=e2,
                entity_3=e3,
            )
            if not mem:
                return
            filled = []
            for slot_name, mem_key in (
                ("entity_1", "entity_1"),
                ("entity_2", "entity_2"),
                ("entity_3", "entity_3"),
                ("category", "last_category"),
            ):
                if ctx.slots.get(slot_name):
                    continue
                val = mem.get(mem_key)
                if val:
                    ctx.slots[slot_name] = str(val)
                    filled.append(slot_name)
            if filled:
                record_action(self._action(
                    action_type="slot_extracted",
                    input_summary="prefill_from_entity_memory",
                    output_summary=f"filled: {filled}",
                ))
        except Exception:
            return

    # ── Slot extraction ──────────────────────────────────────────────
    def _extract_slot(self, slot, text: str) -> str | None:
        if slot.validation == "year-range":
            return _extract_year(text, slot.year_range)
        if slot.validation == "gazetteer":
            # 1. Try direct gazetteer match (whole-word substring).
            v = _extract_via_gazetteer(text, self.ctx, slot.name)
            if v:
                return v
            # 2. For category slots, try the synonym map.
            if slot.name == "category":
                lower = text.lower()
                for syn, canonical in _CATEGORY_SYNONYMS.items():
                    if re.search(rf"\b{re.escape(syn)}\b", lower):
                        # Verify the canonical form is in the gazetteer.
                        gaz = self.ctx.pack.gazetteer_for_slot(slot.name)
                        if gaz and gaz.lookup(canonical):
                            return canonical
            return None
        if slot.validation == "regex" and slot.regex:
            m = re.search(slot.regex, text)
            if m:
                return m.group(1) if m.groups() else m.group(0)
            return None
        if slot.validation == "free-text":
            return text.strip() if text.strip() else None
        return None

    # ── Dialogue policy ──────────────────────────────────────────────────
    def _next_safety_question(self) -> str | None:
        """Return the next unanswered safety question, if any.

        Safety questions are asked once each, in order, before regular slots.
        We track which have been asked via the `safety_questions_asked` set
        on the context (not in slot_attempts since these aren't slots).
        """
        asked = self.ctx.slots.setdefault("__safety_questions_asked__", "")  # misuse; see note
        # Store the set of asked indices in a slot-like key to keep ctx serializable.
        # NOTE: for clarity, we use a private attribute on ctx instead.
        already = getattr(self.ctx, "_safety_asked", set())
        questions = self.ctx.pack.manifest.safety.safety_questions
        for i, q in enumerate(questions):
            if i not in already:
                already.add(i)
                setattr(self.ctx, "_safety_asked", already)
                return q
        return None

    def _next_required_slot(self):
        """Pick the highest-priority missing required slot that hasn't
        exceeded its re-ask limit."""
        # Count customer turns (NOT slot attempts) for the global cap.
        customer_turn_count = sum(1 for t in self.ctx.turns if t["speaker"] == "customer")
        for slot in self.ctx.pack.required_slots():
            if self.ctx.slots.get(slot.name):
                continue
            attempts = self.ctx.slot_attempts.get(slot.name, 0)
            if attempts >= slot.max_re_asks:
                continue
            # Hard global cap on customer turns — stop asking; orchestrator will wrap up.
            if customer_turn_count >= settings.max_turns:
                return None
            return slot
        return None
