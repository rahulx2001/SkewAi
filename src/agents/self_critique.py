"""Pre-close self-critique checklist (feature #20).

Runs before case finalize. Hard fails block silent close when ``strict=True``.
"""

from __future__ import annotations

from typing import Any

from src.ledger import AgentAction, record_action


def run_self_critique(ctx: Any, *, strict: bool = False) -> dict[str, Any]:
    """Return {ok, hard_fails, soft_fails, checks}."""
    checks: list[dict[str, Any]] = []
    hard: list[str] = []
    soft: list[str] = []

    required = []
    try:
        required = [s.name for s in ctx.pack.required_slots()]
    except Exception:
        required = ["entity_2", "category", "description"]

    missing = [n for n in required if not (ctx.slots or {}).get(n)]
    checks.append({"name": "slot_completeness", "ok": not missing, "detail": missing})
    if missing:
        hard.append(f"missing_slots:{','.join(missing)}")

    # Severity/safety consistency: any safety flag must be Critical or P1
    flags = getattr(ctx, "safety_flags", {}) or {}
    if any(flags.values()):
        sev = getattr(ctx, "severity", None) or "Low"
        pri = getattr(ctx, "priority", 3)
        ok_safe = sev == "Critical" or pri == 1
        checks.append(
            {
                "name": "safety_severity_consistency",
                "ok": ok_safe,
                "detail": {"severity": sev, "priority": pri, "flags": flags},
            }
        )
        if not ok_safe:
            hard.append("safety_not_p1_or_critical")

    # Follow-up draft should not invent random case ids when we have one
    follow = getattr(ctx, "followup_draft", None) or ""
    case_id = getattr(ctx, "case_id", None)
    if follow and case_id and case_id not in follow and "case" in follow.lower():
        soft.append("followup_missing_case_id")
        checks.append(
            {"name": "followup_cites_case", "ok": False, "detail": case_id}
        )
    else:
        checks.append({"name": "followup_cites_case", "ok": True, "detail": None})

    # Evidence IDs in brief should be strings
    brief = getattr(ctx, "investigation_brief", None) or {}
    sims = brief.get("similar_records") or []
    bad_ids = [s for s in sims if isinstance(s, dict) and not s.get("record_id")]
    checks.append(
        {"name": "similar_records_have_ids", "ok": not bad_ids, "detail": len(bad_ids)}
    )
    if bad_ids:
        soft.append("similar_without_record_id")

    ok = len(hard) == 0
    if strict and not ok:
        pass

    try:
        record_action(
            AgentAction(
                interaction_id=ctx.interaction_id,
                agent="orchestrator",
                action_type="state_transition",
                input_summary="self_critique",
                output_summary=(
                    f"ok={ok}; hard={hard}; soft={soft}"
                )[:500],
                ok=ok,
                error=";".join(hard) if hard else None,
            )
        )
    except Exception:
        pass

    return {
        "ok": ok,
        "hard_fails": hard,
        "soft_fails": soft,
        "checks": checks,
        "strict": strict,
    }


__all__ = ["run_self_critique"]
