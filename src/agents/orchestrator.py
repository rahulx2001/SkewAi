"""Contact Orchestrator — explicit state machine.

States:
    GREETING → COLLECTING → (SAFETY_ESCALATION | SUPERVISED) → ENRICHING → CLOSING → DONE
    ABANDONED reachable from any state on hangup/timeout.

Guards:
    COLLECTING → SAFETY_ESCALATION:  kill-switch matched.
    COLLECTING → ENRICHING:          required slots filled.
    ENRICHING → CLOSING:             Triage + Sentinel + Investigator done
                                     (or FRONTLINE_ENRICH_TIMEOUT_S).
    SAFETY_ESCALATION → CLOSING:     escalation script delivered.
    CLOSING → DONE:                  case created + goodbye.

SUPERVISED (takeover): reachable from GREETING / COLLECTING / ENRICHING.
AI stops generating turns; enrichment agents keep running; every supervisor
message is ledgered (agent='supervisor', action_type='human_turn') before
delivery. Release → returns to the prior state with slot state intact.

Concurrency: enrichment agents run as asyncio tasks while Intake keeps
talking (Sentinel's entity-only advisory check can fire as soon as entity
slots fill).

Every transition writes an agent_actions row. After DONE: enqueue Qubot
post_contact_audit.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Awaitable, Callable, Optional

from src.agents.base import InteractionContext
from src.agents.case_agent import CaseAgent
from src.agents.intake import IntakeAgent
from src.agents.investigator import InvestigatorAgent
from src.agents.sentiment import SentimentAgent
from src.agents.sentinel import SentinelAgent
from src.agents.triage import TriageAgent
from src.config import settings
from src.domains.loader import LoadedPack, load_pack
from src.ids import new_ulid
from src.ledger import record_action



# ── States ───────────────────────────────────────────────────────────────

GREETING = "GREETING"
COLLECTING = "COLLECTING"
SAFETY_ESCALATION = "SAFETY_ESCALATION"
SUPERVISED = "SUPERVISED"
ENRICHING = "ENRICHING"
CLOSING = "CLOSING"
DONE = "DONE"
ABANDONED = "ABANDONED"

# Allowed transitions (excluding SUPERVISED which has its own enter/exit logic).
_TRANSITIONS = {
    GREETING: {COLLECTING, SUPERVISED, ABANDONED},
    # CLOSING allowed from COLLECTING for max-turns force wrap-up (partial slots).
    COLLECTING: {SAFETY_ESCALATION, ENRICHING, SUPERVISED, ABANDONED, CLOSING},
    SAFETY_ESCALATION: {CLOSING, SUPERVISED, ABANDONED},
    ENRICHING: {CLOSING, SUPERVISED, ABANDONED},
    CLOSING: {DONE, ABANDONED},
    DONE: set(),
    ABANDONED: set(),
    SUPERVISED: set(),                # populated dynamically — see _enter_supervised
}


# ── Hooks (for the channel / API layer) ──────────────────────────────────

@dataclass
class OrchestratorHooks:
    """Callbacks the orchestrator uses to emit output to the customer/console.

    All hooks are async. None are required — defaults are no-ops.
    """
    emit_customer_turn: Optional[Callable[[str, dict[str, Any]], Awaitable[None]]] = None
    emit_activity: Optional[Callable[[dict[str, Any]], Awaitable[None]]] = None
    emit_slots_update: Optional[Callable[[dict[str, str]], Awaitable[None]]] = None
    emit_handoff_offer: Optional[Callable[[], Awaitable[None]]] = None
    emit_interaction_ended: Optional[Callable[[dict[str, Any]], Awaitable[None]]] = None
    emit_frustration_update: Optional[Callable[[float], Awaitable[None]]] = None

    async def _maybe(self, fn: Optional[Callable], *args: Any) -> None:
        if fn is not None:
            await fn(*args)


# ── Orchestrator ──────────────────────────────────────────────────────────


class Orchestrator:
    """Drives a single contact through its state machine."""

    def __init__(
        self,
        interaction_id: str,
        pack: LoadedPack,
        channel: str = "web_text",
        hooks: OrchestratorHooks | None = None,
    ) -> None:
        self.ctx = InteractionContext(
            interaction_id=interaction_id,
            pack=pack,
            channel=channel,
        )
        self.hooks = hooks or OrchestratorHooks()
        self._pre_supervised_state: str | None = None

    # ── Public API ────────────────────────────────────────────────────────
    async def start(self) -> str:
        """Emit the greeting. Returns the greeting text."""
        self._transition(GREETING, COLLECTING)
        greeting = self.ctx.pack.greeting
        try:
            from src.frontline.consent import with_consent

            greeting = with_consent(greeting)
        except Exception:
            pass
        # Ledger the greeting turn BEFORE emitting it (audit-first invariant:
        # no ledger row, no output). The state_transition row above covers the
        # transition; this row covers the customer-visible greeting text.
        record_action(self._orchestrator_action(
            "greeting_emitted",
            input_summary="pack greeting (fast-path, no LLM)",
            output_summary=greeting,
        ))
        await self.hooks._maybe(
            self.hooks.emit_customer_turn,
            greeting,
            {"speaker": "agent", "fast_path": True, "llm_used": False},
        )
        self.ctx.record_turn("agent", greeting, llm_used=False, latency_ms=0)
        self._record_state(COLLECTING)
        return greeting

    async def handle_customer_turn(self, text: str, final: bool = True) -> None:
        """Process a customer turn (text from STT or text input)."""
        if self.ctx.state in (DONE, ABANDONED):
            return

        # If in SUPERVISED, the AI does NOT generate turns.
        if self.ctx.state == SUPERVISED:
            return

        # ── Security: validate input before any agent logic ────────────────
        from src.security import validate_input
        v = validate_input(text)
        if not v.ok:
            record_action(self._orchestrator_action(
                "state_transition",
                input_summary="customer input rejected by security",
                output_summary=f"reason: {v.reason}",
            ))
            # Politely decline and ask for a rephrase; never surface the reason.
            decline = "I'm sorry, I didn't catch that clearly. Could you rephrase?"
            record_action(self._orchestrator_action(
                "goodbye_emitted",  # reuse a customer-turn action type
                input_summary="security rejection; canned rephrase request",
                output_summary=decline,
            ))
            await self.hooks._maybe(
                self.hooks.emit_customer_turn,
                decline,
                {"speaker": "agent", "fast_path": True, "llm_used": False},
            )
            self.ctx.record_turn("agent", decline, llm_used=False)
            return
        text = v.text

        # Record the customer turn
        self.ctx.record_turn("customer", text)

        # Spoken confirmation of a prior diagnostic read-back.
        pending_q = (self.ctx.slots or {}).get("__diag_qid")
        if pending_q:
            from src.frontline.elicitation import (
                looks_like_confirmation,
                record_spoken_confirmation,
            )

            if looks_like_confirmation(text):
                record_spoken_confirmation(
                    self.ctx.interaction_id,
                    text,
                    confirmed=True,
                    question_id=pending_q,
                )
                self.ctx.slots.pop("__diag_qid", None)

        # ── Sentiment (always runs; cheap, deterministic) ───────────────
        sentiment = SentimentAgent(self.ctx)
        sres = await sentiment.run(customer_turn=text)
        # Fan-out live frustration for the supervisor console (H6).
        await self.hooks._maybe(
            getattr(self.hooks, "emit_frustration_update", None),
            float(self.ctx.frustration_score or 0.0),
        )
        if sres.get("threshold_crossed") and not self.ctx.handoff_offered:
            self.ctx.handoff_offered = True
            offer = sres["handoff_offer"]
            # Audit-first: ledger the handoff offer BEFORE emitting it.
            record_action(self._orchestrator_action(
                "handoff_offer_emitted",
                input_summary="frustration threshold crossed; empathy + human offer",
                output_summary=offer,
            ))
            await self.hooks._maybe(
                self.hooks.emit_customer_turn,
                offer,
                {"speaker": "agent", "fast_path": True, "llm_used": False},
            )
            self.ctx.record_turn("agent", offer, llm_used=False)
            await self.hooks._maybe(self.hooks.emit_handoff_offer)

        # ── Intake ────────────────────────────────────────────────────────
        intake = IntakeAgent(self.ctx)
        ires = await intake.run(customer_turn=text)

        # Kill-switch → SAFETY_ESCALATION
        if ires.get("kill_switch"):
            self._transition(self.ctx.state, SAFETY_ESCALATION)
            # Enforce Critical/P1 before CaseAgent (Triage is skipped on this path).
            self.ctx.severity = "Critical"
            self.ctx.severity_source = "rules"
            self.ctx.priority = 1
            # Audit-first: ledger the escalation script BEFORE emitting it.
            record_action(self._orchestrator_action(
                "escalation_script_emitted",
                input_summary=f"kill-switch term: '{ires['kill_switch']}'",
                output_summary=ires["question"],
            ))
            await self.hooks._maybe(
                self.hooks.emit_customer_turn,
                ires["question"],                # the escalation script
                {"speaker": "agent", "fast_path": True, "llm_used": False},
            )
            self.ctx.record_turn("agent", ires["question"], llm_used=False)
            # Sentinel escalation in parallel
            await SentinelAgent(self.ctx).run(trigger="escalation")
            # Fire P1 safety escalation alert (non-blocking)
            try:
                from src.frontline.alerts import alert_safety_escalation
                await alert_safety_escalation(self.ctx.interaction_id, ires["kill_switch"])
            except Exception:
                pass
            await self._move_to_closing()
            return

        # Max customer turns: force wrap-up (case + goodbye), not silent empty questions.
        if ires.get("max_turns_reached"):
            await self._move_to_closing()
            return

        # Confidence-gated escalate → same handoff surface as frustration (not text-only).
        if ires.get("escalate_low_confidence"):
            if not self.ctx.handoff_offered:
                self.ctx.handoff_offered = True
            offer = ires.get("question") or (
                "I'm having trouble capturing that clearly. "
                "Let me connect you with a specialist who can help."
            )
            record_action(self._orchestrator_action(
                "handoff_offer_emitted",
                input_summary=(
                    f"low confidence on slot "
                    f"{ires.get('low_confidence_slot') or 'unknown'}"
                ),
                output_summary=offer[:500],
            ))
            try:
                from src.frontline.validation_queue import enqueue_insight

                enqueue_insight(
                    kind="low_confidence",
                    interaction_id=self.ctx.interaction_id,
                    summary=(
                        f"low confidence on slot "
                        f"{ires.get('low_confidence_slot') or 'unknown'}"
                    ),
                )
            except Exception:
                pass
            await self.hooks._maybe(
                self.hooks.emit_customer_turn,
                offer,
                {
                    "speaker": "agent",
                    "fast_path": True,
                    "llm_used": False,
                    "escalate_low_confidence": True,
                },
            )
            self.ctx.record_turn("agent", offer, llm_used=False)
            await self.hooks._maybe(self.hooks.emit_handoff_offer)
            await self.hooks._maybe(self.hooks.emit_slots_update, dict(self.ctx.slots))
            return

        # Emit the next question (or empty if all slots filled)
        question = ires.get("question", "")
        safety_pending = bool(ires.get("safety_question") or ires.get("kill_switch"))
        if (
            self.ctx.has_required_slots()
            and not self.ctx.slots.get("__diag_asked")
            and not safety_pending
        ):
            from src.frontline.elicitation import next_question
            from src.ledger import record_action as _ra

            dq = next_question(self.ctx.pack.id, self.ctx.slots)
            if dq:
                question = dq["prompt"]
                self.ctx.slots["__diag_qid"] = dq["question_id"]
                self.ctx.slots["__diag_asked"] = "1"
                _ra(
                    self._orchestrator_action(
                        "diagnostic_asked",
                        input_summary=dq["question_id"],
                        output_summary=question[:500],
                    )
                )
        if question:
            await self.hooks._maybe(
                self.hooks.emit_customer_turn,
                question,
                {"speaker": "agent", "fast_path": True, "llm_used": False},
            )
            self.ctx.record_turn("agent", question, llm_used=False)
            await self.hooks._maybe(self.hooks.emit_slots_update, dict(self.ctx.slots))

        # If slots complete AND no question is pending (safety or slot) → ENRICHING.
        # A pending question means the agent is still collecting (e.g. a safety
        # question was just asked and we must wait for the customer's answer
        # before transitioning). This preserves the one-question-per-turn policy.
        if (
            not question
            and self.ctx.has_required_slots()
            and self.ctx.state == COLLECTING
        ):
            await self._enter_enriching()

    async def hangup(self) -> None:
        """Customer hung up. Move to ABANDONED (or DONE if a case was created).

        Either way, persist the turns + interaction row so the audit trail is
        complete — even for abandoned contacts (the customer's last words
        matter for RCA). Customer hangup always leaves SUPERVISED (force-close);
        supervisor-only auto-close still uses ``_move_to_closing`` without force.
        """
        if self.ctx.state == DONE:
            return
        if self.ctx.state == SUPERVISED:
            # Customer left; supervisor control ends so we can finalize.
            self.ctx.supervised = False
            self._pre_supervised_state = None
        if self.ctx.case_id:
            await self._move_to_closing(force=True)
        else:
            self._transition(self.ctx.state, ABANDONED)
            self._record_state(ABANDONED)
            await self._finalize_interaction(outcome="incomplete")

    async def takeover(self) -> None:
        """Supervisor takes over. Save the pre-state; AI stops generating turns."""
        if self.ctx.state == SUPERVISED:
            return
        self._pre_supervised_state = self.ctx.state
        self.ctx.supervised = True
        self._transition(self.ctx.state, SUPERVISED)
        record_action(self._orchestrator_action(
            "takeover_started",
            input_summary=f"prior_state={self._pre_supervised_state}",
            output_summary="supervisor now controls the conversation",
        ))
        # Fire ops alert (non-blocking, deduped per interaction per day)
        try:
            from src.frontline.alerts import alert_takeover_started
            await alert_takeover_started(self.ctx.interaction_id)
        except Exception:
            pass  # alerts must never break a call

    async def release(self) -> None:
        """Supervisor releases. Return to the prior state."""
        if self.ctx.state != SUPERVISED:
            return
        prior = self._pre_supervised_state or COLLECTING
        self._transition(SUPERVISED, prior)
        # Clear the supervised flag so the console / audit reflects that the
        # AI has resumed. (takeover sets this to True; release must reset it.)
        self.ctx.supervised = False
        record_action(self._orchestrator_action(
            "takeover_released",
            input_summary=f"returning to state={prior}",
            output_summary="AI resumes",
        ))
        self._pre_supervised_state = None

    async def human_turn(self, text: str) -> None:
        """Supervisor typed a message. Ledger it BEFORE emitting.

        Supervisor turns pass the same input validation as customer turns
        before broadcast — the audit-first invariant applies to humans too.
        """
        if self.ctx.state != SUPERVISED:
            return
        from src.security import validate_input
        v = validate_input(text)
        if not v.ok:
            record_action(self._orchestrator_action(
                "state_transition",
                input_summary="supervisor input rejected by security",
                output_summary=f"reason: {v.reason}",
            ))
            return  # don't emit; let the console show the rejection
        text = v.text
        record_action(self._orchestrator_action(
            "human_turn",
            input_summary=f"supervisor message",
            output_summary=text,
        ))
        self.ctx.record_turn("supervisor", text)
        await self.hooks._maybe(
            self.hooks.emit_customer_turn,
            text,
            {"speaker": "supervisor", "fast_path": True, "llm_used": False},
        )

    # ── Enrichment ────────────────────────────────────────────────────────
    async def _enter_enriching(self) -> None:
        self._transition(COLLECTING, ENRICHING)
        self._record_state(ENRICHING)

        # Sentinel can fire as soon as entities are present (already true here).
        # Triage + Investigator run after category+description are present.
        try:
            await asyncio.wait_for(
                self._run_enrichment(), timeout=settings.enrich_timeout_s
            )
        except asyncio.TimeoutError:
            record_action(self._orchestrator_action(
                "state_transition",
                input_summary=f"enrichment timeout after {settings.enrich_timeout_s}s",
                output_summary="moving to CLOSING with partial enrichment",
            ))

        await self._move_to_closing()

    async def _run_enrichment(self) -> None:
        """Run independent specialists concurrently (P1: was sequential awaits).

        Sentinel, Triage, and Investigator write distinct ctx fields and do not
        depend on each other's outputs for the pilot path.
        """
        from src.ledger.writer import remember_interaction_pack

        remember_interaction_pack(self.ctx.interaction_id, self.ctx.pack.id)
        sentinel = SentinelAgent(self.ctx)
        triage = TriageAgent(self.ctx)
        inv = InvestigatorAgent(self.ctx)

        sres, tres, ires = await asyncio.gather(
            sentinel.run(trigger="entities_complete"),
            triage.run(),
            inv.run(),
        )

        if sres.get("advisory_match"):
            notice = sres["notice"]
            await self.hooks._maybe(
                self.hooks.emit_customer_turn,
                notice,
                {"speaker": "agent", "fast_path": True, "llm_used": False},
            )
            self.ctx.record_turn("agent", notice, llm_used=False)
            await self.hooks._maybe(self.hooks.emit_activity, {
                "agent": "sentinel",
                "action_type": "advisory_check",
                "summary": notice,
                "evidence_ids": sres.get("evidence_ids", []),
                "ok": True,
            })

        if not tres.get("skipped"):
            await self.hooks._maybe(self.hooks.emit_activity, {
                "agent": "triage",
                "action_type": "severity_scored",
                "summary": f"severity={tres['severity']} (P{tres['priority']})",
                "ok": True,
            })

        if not ires.get("skipped"):
            await self.hooks._maybe(self.hooks.emit_activity, {
                "agent": "investigator",
                "action_type": "brief_written",
                "summary": ires.get("narration", ""),
                "evidence_ids": ires.get("evidence_ids", []),
                "ok": True,
            })

        # Live intercept: re-score this slice; open investigation before close.
        hit: dict = {}
        try:
            from src.frontline.live_intercept import intercept_contact

            hit = await asyncio.to_thread(intercept_contact, self.ctx) or {}
        except Exception:
            hit = {}
        if hit.get("investigation_id"):
            try:
                from src.frontline.alerts import alert_early_warning, alert_investigation_opened

                sl = hit.get("slice") or {}
                cid = 0
                if getattr(self.ctx, "investigation_brief", None):
                    cid = int(self.ctx.investigation_brief.get("cluster_id") or 0)
                await alert_investigation_opened(
                    hit["investigation_id"],
                    cid,
                    f"Live intercept {hit.get('investigation_id')}",
                    pack_id=self.ctx.pack.id,
                )
                risk = hit.get("live_risk") or []
                if risk:
                    top = risk[0]
                    await alert_early_warning(
                        int(top.get("cluster_id") or cid or 0),
                        int(top.get("live_case_count") or 0),
                        top.get("lead_time_weeks"),
                        pack_id=self.ctx.pack.id,
                    )
            except Exception:
                pass
            try:
                from src.frontline.remedy import build_remedy_offer

                pack_name = getattr(self.ctx.pack, "display_name", None) or self.ctx.pack.id
                offer = build_remedy_offer(
                    advisory_match=self.ctx.advisory_match,
                    case_id=self.ctx.case_id,
                    pack_display_name=str(pack_name),
                )
                if offer and offer.get("customer_text"):
                    await self.hooks._maybe(
                        self.hooks.emit_customer_turn,
                        offer["customer_text"],
                        {"speaker": "agent", "fast_path": True, "llm_used": False},
                    )
                    self.ctx.record_turn("agent", offer["customer_text"], llm_used=False)
            except Exception:
                pass

    # ── Closing ───────────────────────────────────────────────────────────
    async def _move_to_closing(self, *, force: bool = False) -> None:
        if self.ctx.state == CLOSING or self.ctx.state == DONE:
            return
        if self.ctx.state == SUPERVISED and not force:
            return  # supervisor controls; don't auto-close mid-call
        if self.ctx.state == SUPERVISED and force:
            self.ctx.supervised = False
        self._transition(self.ctx.state, CLOSING)
        self._record_state(CLOSING)

        # Pre-close self-critique (feature #20) — soft by default
        try:
            from src.agents.self_critique import run_self_critique

            critique = run_self_critique(self.ctx, strict=False)
            self.ctx.self_critique = critique
        except Exception:
            pass

        # Case agent
        case_agent = CaseAgent(self.ctx)
        cres = await case_agent.run()
        case_id = cres["case_id"]

        # Goodbye with case number + investigation mention
        goodbye = self.ctx.pack.manifest.goodbye.replace("{case_id}", case_id)
        if cres.get("investigation_opened"):
            goodbye += " You're not alone — this issue is under active investigation."
        # Customer-facing remedy/next-step when advisory matched
        offer = cres.get("remedy_offer") or getattr(self.ctx, "remedy_offer", None)
        goodbye_evidence: list[str] = []
        if isinstance(offer, dict) and offer.get("customer_text"):
            goodbye = f"{goodbye} {offer['customer_text']}"
            if offer.get("advisory_id"):
                goodbye_evidence.append(str(offer["advisory_id"]))
        linked = cres.get("linked_issues") or []
        if len(linked) > 1:
            goodbye += f" We also opened {len(linked) - 1} linked issue(s) from this contact."

        # Audit-first invariant: ledger the goodbye BEFORE emitting it.
        # Cite advisory IDs present in remedy text so Qubot uncited-ID gate stays green.
        from src.ledger import AgentAction

        record_action(
            AgentAction(
                interaction_id=self.ctx.interaction_id,
                agent="orchestrator",
                action_type="goodbye_emitted",
                input_summary="pack goodbye (fast-path, no LLM)",
                output_summary=goodbye[:500],
                evidence_ids=goodbye_evidence,
                case_id=case_id,
            )
        )
        await self.hooks._maybe(
            self.hooks.emit_customer_turn,
            goodbye,
            {"speaker": "agent", "fast_path": True, "llm_used": False},
        )
        self.ctx.record_turn("agent", goodbye, llm_used=False)

        self._transition(CLOSING, DONE)
        self._record_state(DONE)
        await self._finalize_interaction(outcome=self._outcome())

        await self.hooks._maybe(self.hooks.emit_interaction_ended, {
            "case_id": case_id,
            "investigation_id": cres.get("investigation_id"),
            "investigation_opened": cres.get("investigation_opened"),
            "audit_pending": True,
        })

    # ── Helpers ────────────────────────────────────────────────────────────
    def _transition(self, from_state: str, to_state: str) -> None:
        allowed = _TRANSITIONS.get(from_state, set())
        if from_state == SUPERVISED:
            # Release may return to the pre-takeover state; hangup must always
            # be able to leave SUPERVISED (docstring: ABANDONED from any state).
            resume = {self._pre_supervised_state} if self._pre_supervised_state else {
                COLLECTING, ENRICHING, CLOSING
            }
            allowed = resume | {ABANDONED, CLOSING, DONE}
        if to_state not in allowed and from_state != to_state:
            raise ValueError(f"Illegal transition: {from_state} → {to_state}")
        self.ctx.state = to_state
        record_action(self._orchestrator_action(
            "state_transition",
            input_summary=f"from={from_state}",
            output_summary=f"to={to_state}",
        ))

    def _record_state(self, state: str) -> None:
        # Persist the latest state + slot values + frustration on the interaction row.
        from src.data.warehouse import ops_con
        with ops_con() as con:
            con.execute(
                """
                UPDATE interactions
                SET status = ?, peak_frustration = ?, last_frustration = ?,
                    supervised = ?, entity_1 = ?, entity_2 = ?, entity_3 = ?,
                    category = ?, description = ?
                WHERE interaction_id = ?
                """,
                [
                    "abandoned" if state == ABANDONED else ("active" if state not in (DONE,) else "completed"),
                    self.ctx.peak_frustration,
                    self.ctx.frustration_score,
                    self.ctx.supervised,
                    self.ctx.slots.get("entity_1"),
                    self.ctx.slots.get("entity_2"),
                    self.ctx.slots.get("entity_3"),
                    self.ctx.slots.get("category"),
                    (self.ctx.slots.get("description") or "")[:500],
                    self.ctx.interaction_id,
                ],
            )

    def _outcome(self) -> str:
        if self.ctx.safety_flags.get("escalation"):
            return "escalated_safety"
        if self.ctx.advisory_match:
            return "advisory_notified"
        if self.ctx.case_id:
            return "case_created"
        return "incomplete"

    async def _finalize_interaction(self, outcome: str) -> None:
        from src.data.timeutil import utc_now
        from src.data.warehouse import ops_con
        # Determine final status from outcome: 'incomplete' → 'abandoned',
        # otherwise 'completed'. 'escalated_safety' stays 'escalated' for the
        # console's red-flag view.
        if outcome == "incomplete":
            final_status = "abandoned"
        elif outcome == "escalated_safety":
            final_status = "escalated"
        else:
            final_status = "completed"
        with ops_con() as con:
            con.execute(
                """
                UPDATE interactions
                SET ended_at = ?, status = ?, outcome = ?,
                    peak_frustration = ?, supervised = ?, llm_calls = ?,
                    entity_1 = ?, entity_2 = ?, entity_3 = ?,
                    category = ?, description = ?
                WHERE interaction_id = ?
                """,
                [
                    utc_now(),
                    final_status,
                    outcome,
                    self.ctx.peak_frustration,
                    self.ctx.supervised,
                    self.ctx.llm_calls,
                    self.ctx.slots.get("entity_1"),
                    self.ctx.slots.get("entity_2"),
                    self.ctx.slots.get("entity_3"),
                    self.ctx.slots.get("category"),
                    (self.ctx.slots.get("description") or "")[:500],
                    self.ctx.interaction_id,
                ],
            )
        # Cross-contact entity memory (enterprise) — never raise into contact path.
        try:
            from src.enterprise.memory import upsert_memory_from_interaction

            upsert_memory_from_interaction(self.ctx.interaction_id)
        except Exception:
            pass
        # v3 governance stamp + continuous learning proposal (best-effort).
        try:
            from src.v3.governance import stamp_and_maybe_learn

            stamp_and_maybe_learn(self.ctx.interaction_id)
        except Exception:
            pass
        # Persist any turns not yet flushed mid-contact (idempotent by turn_id).
        try:
            from src.data.turns import persist_turn

            for t in self.ctx.turns:
                persist_turn(self.ctx.interaction_id, t)
        except Exception:
            pass

        # ── Enqueue Qubot post_contact_audit (non-blocking) ────────────────
        # Never await the auditor on the contact/WS hot path (H4 / audit3).
        # Failures are ledgered; retry via `make audit ID=...` if needed.
        try:
            from src.qubot.auditor import audit_interaction

            iid = self.ctx.interaction_id

            async def _run_audit() -> None:
                try:
                    await audit_interaction(iid, write_report=True)
                except Exception as e:
                    try:
                        record_action(self._orchestrator_action(
                            "state_transition",
                            input_summary="post_contact_audit",
                            output_summary=f"audit failed: {type(e).__name__}: {e}",
                        ))
                    except Exception:
                        pass

            try:
                loop = asyncio.get_running_loop()
                # Fire-and-forget: hangup/finalize returns without waiting.
                task = loop.create_task(_run_audit())
                # Prevent "task exception never retrieved" noise if suite exits early.
                task.add_done_callback(lambda t: t.exception() if not t.cancelled() else None)
            except RuntimeError:
                # No running loop (CLI/sync): skip; callers can run audit explicitly.
                pass
        except Exception as e:
            record_action(self._orchestrator_action(
                "state_transition",
                input_summary="post_contact_audit",
                output_summary=f"audit schedule failed: {type(e).__name__}: {e}",
            ))

        # Feature #51: release drain registry slot so deploy can exit when idle.
        try:
            from src.ops.drain import DRAIN

            DRAIN.unregister(self.ctx.interaction_id)
        except Exception:
            pass

    def _orchestrator_action(self, action_type: str, input_summary: str = "", output_summary: str = ""):
        from src.ledger import AgentAction
        return AgentAction(
            interaction_id=self.ctx.interaction_id,
            agent="orchestrator",
            action_type=action_type,
            input_summary=input_summary,
            output_summary=output_summary,
            case_id=self.ctx.case_id,
        )


# ── Factory ───────────────────────────────────────────────────────────────


def new_interaction_id() -> str:
    return "int_" + new_ulid()


async def create_interaction(
    channel: str = "web_text",
    pack_id: str | None = None,
    hooks: OrchestratorHooks | None = None,
) -> tuple[Orchestrator, str]:
    """Create an interaction row + orchestrator. Returns (orchestrator, greeting).

    Feature #51: refuses new contacts while the process is draining (SIGTERM /
    blue-green). Raises ``ServiceDrainingError`` so API callers return 503.
    """
    from src.data.warehouse import ops_con
    from src.domains.active_pack import resolve_active_pack_id
    from src.ops.drain import DRAIN, ServiceDrainingError

    pack = load_pack(pack_id or resolve_active_pack_id())
    interaction_id = new_interaction_id()

    # Register before DB insert so drain rejects never leave orphan rows.
    if not DRAIN.register_active(interaction_id):
        raise ServiceDrainingError()

    from src.data.timeutil import utc_now

    try:
        with ops_con() as con:
            con.execute(
                """
                INSERT INTO interactions
                (interaction_id, pack_id, pack_version, started_at, channel,
                 status, supervised, llm_calls)
                VALUES (?, ?, ?, ?, ?, 'active', FALSE, 0)
                """,
                [
                    interaction_id,
                    pack.id,
                    pack.pack_version,
                    utc_now(),
                    channel,
                ],
            )
        record_action(_build_started_action(interaction_id, pack.id))

        orch = Orchestrator(interaction_id, pack, channel=channel, hooks=hooks)
        greeting = await orch.start()
        return orch, greeting
    except Exception:
        DRAIN.unregister(interaction_id)
        raise


def _build_started_action(interaction_id: str, pack_id: str):
    from src.ledger import AgentAction
    return AgentAction(
        interaction_id=interaction_id,
        agent="orchestrator",
        action_type="interaction_started",
        input_summary=f"pack_id={pack_id}",
        output_summary="interaction created",
    )
