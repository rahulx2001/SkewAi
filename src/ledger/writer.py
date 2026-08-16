"""Action Ledger — the v2 audit spine.

Every agent action writes a row to `agent_actions` **before** the output is
emitted to the customer or console. This is the architecture's core invariant:

    No ledger row, no output.

The ledger is the single source of truth for:
  - What the AI did
  - On whose data (evidence_ids)
  - Whether the action succeeded
  - How long it took (duration_ms)
  - Whether a human took over (agent='supervisor')

Qubot v2's post-contact audit reads this ledger to verify groundedness and
produce the contact audit report.
"""

from __future__ import annotations

import json
import time
from src.ids import new_ulid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

from src.data.warehouse import ops_con


def _now() -> datetime:
    from src.data.timeutil import utc_now

    return utc_now()


def _ts_for_storage(ts: datetime | None) -> datetime:
    from src.data.timeutil import to_naive_utc

    return to_naive_utc(ts) if ts is not None else _now()


def _ulid() -> str:
    return new_ulid()


# ── Action type vocabulary ──────────────────────────────────────────────────
# These are the canonical action_type values. The orchestrator and agents
# MUST use these so Qubot's retrievers can aggregate them deterministically.

ACTION_TYPES = {
    # Orchestrator lifecycle
    "interaction_started",
    "greeting_emitted",
    "goodbye_emitted",
    "handoff_offer_emitted",
    "escalation_script_emitted",
    "state_transition",
    "interaction_ended",
    "interaction_abandoned",
    "takeover_started",
    "takeover_released",
    "human_turn",                      # supervisor turn (also ledgered)
    "alert_sent",
    "connector_dispatched",
    "signal_exported",
    # Intake
    "slot_extracted",
    "question_asked",
    "safety_flag_raised",
    "intake_completed",
    # Sentiment
    "turn_scored",
    "frustration_flagged",
    # Triage
    "severity_scored",
    "priority_assigned",
    # Sentinel
    "advisory_check",
    "advisory_notified",
    "escalated",
    # Investigator
    "similar_search",
    "cluster_matched",
    "spike_checked",
    "brief_written",
    # Case
    "case_created",
    "followup_drafted",
    "investigation_linked",
    "investigation_opened",
    "case_status_updated",
    "case_note_added",
    "followup_saved",
    "investigation_status_updated",
    # Multi-issue / four-eyes / coach (platform extensions)
    "multi_issue_attach_failed",
    "approval_requested",
    "approval_decided",
    "callback_scheduled",
    "appointment_booked",
    "coach_whisper",
    "spoken_confirmation",
    "diagnostic_asked",
    "live_intercept",
    "reproduced",
}


# ── Public dataclass ────────────────────────────────────────────────────────


@dataclass
class AgentAction:
    """A single auditable agent action.

    Use `record_action()` to write one of these to the ledger.
    """

    interaction_id: str
    agent: str                       # intake | sentiment | triage | sentinel | investigator | case | orchestrator | supervisor
    action_type: str                 # one of ACTION_TYPES
    input_summary: str = ""
    output_summary: str = ""
    evidence_ids: list[str] = field(default_factory=list)
    claims: list[Any] = field(default_factory=list)
    case_id: str | None = None
    ok: bool = True
    error: str | None = None
    duration_ms: int | None = None
    action_id: str = field(default_factory=_ulid)
    ts: datetime = field(default_factory=_now)


# ── Writer ──────────────────────────────────────────────────────────────────


def _insert_action_row(con, action: AgentAction) -> str:
    """Insert one agent_actions row on an existing connection (no open/close)."""
    if action.action_type not in ACTION_TYPES:
        raise ValueError(
            f"unknown action_type {action.action_type!r}; "
            f"must be one of the ledger ACTION_TYPES vocabulary"
        )
    from src.ledger.chain import GENESIS, compute_row_hash

    evidence_json = json.dumps(action.evidence_ids)
    ts_stored = _ts_for_storage(action.ts)
    # Hash chain: previous row for this interaction (append-only order by ts/action_id).
    prev_row = con.execute(
        """
        SELECT row_hash FROM agent_actions
        WHERE interaction_id = ?
        ORDER BY ts DESC, action_id DESC
        LIMIT 1
        """,
        [action.interaction_id],
    ).fetchone()
    prev_hash = (prev_row[0] if prev_row and prev_row[0] else GENESIS) or GENESIS
    row_payload = {
        "action_id": action.action_id,
        "interaction_id": action.interaction_id,
        "case_id": action.case_id,
        "agent": action.agent,
        "action_type": action.action_type,
        "input_summary": (action.input_summary or "")[:500],
        "output_summary": (action.output_summary or "")[:500],
        "evidence_ids": evidence_json,
        "ok": action.ok,
        "error": action.error,
        "duration_ms": action.duration_ms,
        "ts": str(ts_stored),
    }
    row_hash = compute_row_hash(row_payload, prev_hash)
    con.execute(
        """
        INSERT INTO agent_actions (
            action_id, interaction_id, case_id, agent, action_type,
            input_summary, output_summary, evidence_ids,
            ok, error, duration_ms, ts, prev_hash, row_hash
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        [
            action.action_id,
            action.interaction_id,
            action.case_id,
            action.agent,
            action.action_type,
            (action.input_summary or "")[:500],
            (action.output_summary or "")[:500],
            evidence_json,
            action.ok,
            action.error,
            action.duration_ms,
            ts_stored,
            prev_hash,
            row_hash,
        ],
    )
    return row_hash


_PACK_BY_INTERACTION: dict[str, str] = {}


def remember_interaction_pack(interaction_id: str, pack_id: str) -> None:
    if interaction_id and pack_id:
        _PACK_BY_INTERACTION[interaction_id] = pack_id


def record_action(action: AgentAction) -> str:
    """Write an action to the ledger. Returns the action_id.

    This is the ONLY way an agent may produce a side effect. The row is
    written BEFORE any output (text turn, console card) is emitted — this is
    the trust invariant Qubot v2 audits.

    Insert, Merkle leaf, pins, and optional claim rows share one ops connection
    so concurrent enrichment agents are not serialized on extra DuckDB locks.
    """
    pack_id = _PACK_BY_INTERACTION.get(action.interaction_id)
    snaps: dict[str, dict[str, Any]] = {}
    if action.evidence_ids and pack_id:
        try:
            from src.qubot.evidence_pin import fetch_record_rows

            snaps = fetch_record_rows(pack_id, [str(e) for e in action.evidence_ids])
        except Exception:
            snaps = {}
    with ops_con() as con:
        row_hash = _insert_action_row(con, action)
        try:
            from src.ledger.merkle import append_action_leaf_on_con

            append_action_leaf_on_con(
                con, action.interaction_id, action.action_id, str(row_hash)
            )
        except Exception:
            pass
        if getattr(action, "claims", None):
            try:
                from src.qubot.claims import store_bound_claims_on_con

                store_bound_claims_on_con(con, action.action_id, action.claims)
            except Exception:
                pass
        if action.evidence_ids and not pack_id:
            row = con.execute(
                "SELECT pack_id FROM interactions WHERE interaction_id = ?",
                [action.interaction_id],
            ).fetchone()
            if row and row[0]:
                pack_id = str(row[0])
                remember_interaction_pack(action.interaction_id, pack_id)
        if snaps and pack_id:
            try:
                from src.qubot.evidence_pin import insert_pins_on_con

                insert_pins_on_con(
                    con,
                    action_id=action.action_id,
                    interaction_id=action.interaction_id,
                    pack_id=str(pack_id),
                    rows=snaps,
                )
            except Exception:
                pass
    if action.evidence_ids and pack_id and not snaps:
        _pin_cited_best_effort(action, pack_id=str(pack_id))
    return action.action_id


def _pin_cited_best_effort(action: AgentAction, *, pack_id: str | None = None) -> None:
    if not action.evidence_ids:
        return
    try:
        if not pack_id:
            with ops_con(read_only=True) as con:
                row = con.execute(
                    "SELECT pack_id FROM interactions WHERE interaction_id = ?",
                    [action.interaction_id],
                ).fetchone()
                if row:
                    pack_id = row[0]
        if not pack_id:
            return
        from src.qubot.evidence_pin import pin_cited_records

        pin_cited_records(
            action_id=action.action_id,
            interaction_id=action.interaction_id,
            pack_id=str(pack_id),
            evidence_ids=list(action.evidence_ids),
        )
    except Exception:
        return


def record_action_on_con(con, action: AgentAction) -> str:
    """Write an action on a caller-owned ops connection (same transaction)."""
    _insert_action_row(con, action)
    return action.action_id


class action_timer:
    """Context manager that times a block and records the action.

    Usage:
        with action_timer(interaction_id, "sentinel", "advisory_check",
                          input_summary="...", evidence_ids=[...]) as act:
            ... do work ...
            act.output_summary = "Matched advisory 19V-XXX"
            act.evidence_ids = ["19V-XXX"]
            # on exit, the action is written to the ledger.

    If the block raises, ok=False, error=str(exc) is recorded (and the
    exception re-raised).
    """

    def __init__(
        self,
        interaction_id: str,
        agent: str,
        action_type: str,
        input_summary: str = "",
        case_id: str | None = None,
    ) -> None:
        self._action = AgentAction(
            interaction_id=interaction_id,
            agent=agent,
            action_type=action_type,
            case_id=case_id,
            input_summary=input_summary,
        )
        self._start = 0.0

    def __enter__(self) -> "action_timer":
        self._start = time.perf_counter()
        return self

    def __exit__(self, exc_type, exc, tb) -> bool:
        self._action.duration_ms = int((time.perf_counter() - self._start) * 1000)
        if exc is not None:
            self._action.ok = False
            self._action.error = f"{type(exc).__name__}: {exc}"
        record_action(self._action)
        return False  # don't suppress

    @property
    def action(self) -> AgentAction:
        return self._action

    @property
    def output_summary(self) -> str:
        return self._action.output_summary

    @output_summary.setter
    def output_summary(self, v: str) -> None:
        self._action.output_summary = v

    @property
    def evidence_ids(self) -> list[str]:
        return self._action.evidence_ids

    @evidence_ids.setter
    def evidence_ids(self, v: list[str]) -> None:
        self._action.evidence_ids = v


# ── Reader ──────────────────────────────────────────────────────────────────


def list_actions(interaction_id: str) -> list[dict[str, Any]]:
    """Return all actions for an interaction, ordered by ts."""
    with ops_con(read_only=True) as con:
        cur = con.execute(
            "SELECT * FROM agent_actions WHERE interaction_id = ? ORDER BY ts, action_id",
            [interaction_id],
        )
        cols = [d[0] for d in cur.description]
        rows = cur.fetchall()
    out = []
    for r in rows:
        d = dict(zip(cols, r))
        # parse JSON columns
        if d.get("evidence_ids"):
            try:
                d["evidence_ids"] = json.loads(d["evidence_ids"])
            except (json.JSONDecodeError, TypeError):
                d["evidence_ids"] = []
        else:
            d["evidence_ids"] = []
        out.append(d)
    return out


__all__ = [
    "AgentAction",
    "action_timer",
    "record_action",
    "list_actions",
    "ACTION_TYPES",
]
