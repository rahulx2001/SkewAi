"""Interactive incident timeline — ordered replay events from ops warehouse.

Distinct from Qubot audit markdown: this is a structured event stream with
step indices for UI playback (turns, agent_actions, risk-relevant markers).
"""

from __future__ import annotations

import json
from datetime import datetime
from typing import Any

from src.data.warehouse import ops_con


def _iso(v: Any) -> Any:
    if isinstance(v, datetime):
        return v.isoformat()
    return v


def build_incident_timeline(interaction_id: str) -> dict[str, Any]:
    """Build a complete ordered timeline for one interaction.

    Events: interaction_header, turn, agent_action, case_linked.
    Each event has step, ts, kind, label, detail, agent (optional).
    """
    with ops_con(read_only=True) as con:
        header = con.execute(
            "SELECT * FROM interactions WHERE interaction_id = ?",
            [interaction_id],
        ).fetchone()
        if not header:
            raise LookupError(f"interaction not found: {interaction_id}")
        hcols = [d[0] for d in con.description]
        interaction = dict(zip(hcols, header))

        turns = con.execute(
            """
            SELECT turn_id, seq, speaker, text, ts, latency_ms, frustration_score
            FROM interaction_turns
            WHERE interaction_id = ?
            ORDER BY seq
            """,
            [interaction_id],
        ).fetchall()
        tcols = [d[0] for d in con.description]

        actions = con.execute(
            """
            SELECT action_id, agent, action_type, input_summary, output_summary,
                   evidence_ids, ok, error, duration_ms, ts, case_id
            FROM agent_actions
            WHERE interaction_id = ?
            ORDER BY ts
            """,
            [interaction_id],
        ).fetchall()
        acols = [d[0] for d in con.description]

        case = con.execute(
            "SELECT case_id, severity, priority, status, created_at FROM cases WHERE interaction_id = ?",
            [interaction_id],
        ).fetchone()
        ccols = [d[0] for d in con.description] if case else []

    events: list[dict[str, Any]] = []

    events.append(
        {
            "kind": "interaction_started",
            "ts": _iso(interaction.get("started_at")),
            "label": f"Contact started ({interaction.get('channel')})",
            "detail": {
                "pack_id": interaction.get("pack_id"),
                "status": interaction.get("status"),
                "outcome": interaction.get("outcome"),
            },
            "agent": "orchestrator",
        }
    )

    for row in turns:
        t = dict(zip(tcols, row))
        events.append(
            {
                "kind": "turn",
                "ts": _iso(t.get("ts")),
                "label": f"{t.get('speaker')} turn #{t.get('seq')}",
                "detail": {
                    "text": (t.get("text") or "")[:500],
                    "frustration_score": t.get("frustration_score"),
                    "latency_ms": t.get("latency_ms"),
                    "seq": t.get("seq"),
                },
                "agent": t.get("speaker"),
            }
        )

    for row in actions:
        a = dict(zip(acols, row))
        evidence = a.get("evidence_ids")
        if isinstance(evidence, str):
            try:
                evidence = json.loads(evidence)
            except Exception:
                pass
        events.append(
            {
                "kind": "agent_action",
                "ts": _iso(a.get("ts")),
                "label": f"{a.get('agent')}: {a.get('action_type')}",
                "detail": {
                    "action_id": a.get("action_id"),
                    "input_summary": a.get("input_summary"),
                    "output_summary": a.get("output_summary"),
                    "ok": a.get("ok"),
                    "error": a.get("error"),
                    "duration_ms": a.get("duration_ms"),
                    "evidence_ids": evidence,
                    "case_id": a.get("case_id"),
                },
                "agent": a.get("agent"),
            }
        )

    if case:
        c = dict(zip(ccols, case))
        events.append(
            {
                "kind": "case_linked",
                "ts": _iso(c.get("created_at")),
                "label": f"Case {c.get('case_id')} ({c.get('severity')} P{c.get('priority')})",
                "detail": c,
                "agent": "case",
            }
        )

    if interaction.get("ended_at"):
        events.append(
            {
                "kind": "interaction_ended",
                "ts": _iso(interaction.get("ended_at")),
                "label": f"Contact ended → {interaction.get('outcome') or interaction.get('status')}",
                "detail": {
                    "status": interaction.get("status"),
                    "outcome": interaction.get("outcome"),
                    "supervised": interaction.get("supervised"),
                    "peak_frustration": interaction.get("peak_frustration"),
                },
                "agent": "orchestrator",
            }
        )

    # Stable sort: null ts last; then by ts string
    def _sort_key(e: dict[str, Any]) -> tuple:
        ts = e.get("ts") or ""
        return (ts == "", str(ts), e.get("kind", ""))

    events.sort(key=_sort_key)
    for i, e in enumerate(events):
        e["step"] = i

    for k, v in list(interaction.items()):
        interaction[k] = _iso(v)

    return {
        "interaction_id": interaction_id,
        "interaction": interaction,
        "events": events,
        "event_count": len(events),
        "playback": {
            "first_step": 0,
            "last_step": max(0, len(events) - 1),
            "kinds": sorted({e["kind"] for e in events}),
        },
    }
