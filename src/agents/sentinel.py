"""Advisory Sentinel — known-issue matcher.

Two triggers:
  1. Entity slots complete → advisory check.
  2. Kill-switch escalation (from Intake).

Advisory check: executes the pack's parameterized read-only SQL template
against `advisories`; on match, injects an `advisory_notice` turn delivered
verbatim (id, scope, remedy — all from SQL, no LLM).

Escalation: marks interaction escalated, case P1, emits an escalation card
and a P1 ops alert. No LLM.
"""

from __future__ import annotations

from typing import Any

from src.agents.base import Agent
from src.data.warehouse import domain_con
from src.ledger import record_action


class SentinelAgent(Agent):
    """Match customer entities against known advisories. No LLM."""

    name = "sentinel"

    async def run(self, trigger: str = "entities_complete", **kwargs: Any) -> dict[str, Any]:
        ctx = self.ctx
        # 6.4: hot-kill without redeploy
        try:
            from src.ops.pilot import agent_enabled
            if not agent_enabled("sentinel"):
                record_action(self._action(
                    action_type="advisory_check",
                    input_summary="flag FRONTLINE_AGENT_SENTINEL_ENABLED=0",
                    output_summary="sentinel disabled by flag; skipped",
                ))
                return {"skipped": True, "reason": "disabled_by_flag", "advisory_match": None}
        except Exception:
            pass

        if trigger == "escalation":
            # Kill-switch from Intake. Mark escalated; Case Agent will P1 it.
            record_action(self._action(
                action_type="escalated",
                input_summary="kill-switch escalation from intake",
                output_summary="interaction escalated; case will be P1",
                evidence_ids=[],
            ))
            return {"escalated": True, "advisory_match": None}

        # trigger == "entities_complete"
        # Need at least entity_2 and entity_3 for a meaningful match.
        entity_2 = ctx.slots.get("entity_2")
        entity_3 = ctx.slots.get("entity_3")
        category = ctx.slots.get("category")
        if not entity_2 and not entity_3 and not category:
            return {"skipped": True, "reason": "no entity slots to match"}

        sql_template = ctx.pack.manifest.advisory_match.sql_template
        params = {
            "entity_1": ctx.slots.get("entity_1"),
            "entity_2": entity_2,
            "entity_3": entity_3,
            "category": category,
        }

        try:
            with domain_con(ctx.pack.id) as con:
                rows = con.execute(sql_template, params).fetchall()
                cols = [d[0] for d in con.description]
        except Exception as e:
            record_action(self._action(
                action_type="advisory_check",
                input_summary=f"params={params}",
                output_summary="",
                ok=False,
                error=f"{type(e).__name__}: {e}",
            ))
            return {"error": str(e), "advisory_match": None}

        if not rows:
            record_action(self._action(
                action_type="advisory_check",
                input_summary=f"params={params}",
                output_summary="no advisories matched",
                evidence_ids=[],
            ))
            # 1.3: no-match is novelty signal, not silence
            try:
                import os as _os
                from src.agents.investigator import _record_novel_candidate as _nov
                _thr = float(_os.getenv("FRONTLINE_NOVELTY_MIN_SCORE", "3.0"))
                _nov(ctx, category, entity_2, entity_3, 0.0)
            except Exception:
                pass
            return {"advisory_match": None, "novel_candidate": True}

        # Take the most recent advisory (rows are already ordered by SQL).
        match = dict(zip(cols, rows[0]))
        ctx.advisory_match = match

        # Build the verbatim notice from the pack's readback fields.
        notice_parts = []
        for field in ctx.pack.manifest.advisory_match.readback_fields:
            v = match.get(field)
            if v is not None and v != "":
                notice_parts.append(f"{field.replace('_', ' ').title()}: {v}")
        notice = "There's a matching known issue. " + " | ".join(notice_parts) + "."

        evidence = [match.get("advisory_id")] if match.get("advisory_id") else []
        record_action(self._action(
            action_type="advisory_check",
            input_summary=f"params={params}",
            output_summary=f"matched {len(rows)} advisories; top: {match.get('advisory_id')}",
            evidence_ids=evidence,
        ))
        record_action(self._action(
            action_type="advisory_notified",
            input_summary=f"advisory_id={match.get('advisory_id')}",
            output_summary=notice,
            evidence_ids=evidence,
        ))

        return {
            "advisory_match": match,
            "notice": notice,
            "evidence_ids": evidence,
        }
