"""Triage Agent — severity + priority.

Fires mid-contact once category + description are known. Severity via the
pack's configured path:
  - ML runtime artifact (automotive keeps the v1 XGBoost model), OR
  - the pack's ordered rule list.

Priority via the pack's priority matrix (any safety flag → P1 always).
No LLM.
"""

from __future__ import annotations

from typing import Any

from src.agents.base import Agent
from src.ledger import record_action


def _eval_condition(cond: str, ctx: Any) -> bool:
    """Evaluate a pack severity rule's `when` condition against the context.

    Supported:
      - "safety.any" — any safety flag set
      - "safety.<key>" — specific safety flag
      - "category in [A, B, C]" — category match
      - "description_matches_<term>" — substring match on description
      - "default" / "always" / "true" — always true
    """
    cond = cond.strip()
    if cond.lower() in ("default", "always", "true", "else"):
        return True

    if cond == "safety.any":
        return any(ctx.safety_flags.values())
    if cond.startswith("safety."):
        key = cond.split(".", 1)[1]
        return bool(ctx.safety_flags.get(key))

    if cond.startswith("category in"):
        # parse [A, B, C]
        import re
        m = re.search(r"\[(.*)\]", cond)
        if not m:
            return False
        cats = [c.strip().strip("'\"") for c in m.group(1).split(",")]
        return ctx.slots.get("category", "").upper() in [c.upper() for c in cats]

    if cond.startswith("description_matches"):
        # description_matches_fire|smoke|crash|injury
        terms_part = cond.split("description_matches", 1)[1].strip()
        # may start with _ or whitespace
        terms_part = terms_part.lstrip("_").strip()
        if not terms_part:
            return False
        desc = (ctx.slots.get("description") or "").lower()
        import re
        for term in terms_part.split("|"):
            term = term.strip().strip("'\"")
            if not term:
                continue
            # Word-boundary match so 'fire' doesn't match 'misfires'.
            # Use a regex with case-insensitive flag.
            if re.search(rf"\b{re.escape(term.lower())}\b", desc):
                return True
        return False

    return False


def _apply_rule_severity(ctx: Any) -> tuple[str, str, str]:
    """Returns (severity, source, reason). Uses the pack's ordered rules."""
    for rule in ctx.pack.manifest.severity.rules:
        if _eval_condition(rule.when, ctx):
            return rule.severity, "rules", rule.reason
    return "Low", "rules", "No rule matched; default to Low"


def _apply_model_severity(ctx: Any) -> tuple[str, str, str]:
    """Use the pack's ML runtime artifact for severity.

    Falls back to rules if the model isn't loaded (clean degradation).
    """
    artifact_ref = ctx.pack.manifest.severity.model_artifact
    if not artifact_ref:
        return _apply_rule_severity(ctx)

    # Lazy import to avoid the heavy ml_runtime dependency at module load time.
    try:
        from src.ml_runtime.registry import predict_severity
        severity, reason = predict_severity(artifact_ref, {
            "entity_1": ctx.slots.get("entity_1"),
            "entity_2": ctx.slots.get("entity_2"),
            "entity_3": ctx.slots.get("entity_3"),
            "category": ctx.slots.get("category"),
            "description": ctx.slots.get("description"),
            "safety_flags": ctx.safety_flags,
        })
        return severity, "model", reason or "ML artifact prediction"
    except Exception as e:
        # Clean fallback to rules — never break the call over severity scoring.
        sev, _, _ = _apply_rule_severity(ctx)
        return sev, "rules", f"model fallback ({type(e).__name__}: {e})"


def score_severity(ctx: Any) -> tuple[str, str, str]:
    """Same path TriageAgent.run uses. REPRODUCE must call this, not rules-only."""
    if ctx.pack.manifest.severity.model_artifact:
        return _apply_model_severity(ctx)
    return _apply_rule_severity(ctx)


def _priority_from_matrix(severity: str, ctx: Any) -> int:
    """Compute priority (1=highest) via the pack's priority matrix.

    Hardcoded invariant: any safety flag → P1 always (the matrix value for
    `safety` is 1 by default but we enforce the floor here too).
    """
    matrix = ctx.pack.manifest.severity.priority_matrix
    if any(ctx.safety_flags.values()):
        return 1
    return matrix.get(severity, matrix.get("Low", 3))


class TriageAgent(Agent):
    """Severity + priority. No LLM."""

    name = "triage"

    async def run(self, **kwargs: Any) -> dict[str, Any]:
        ctx = self.ctx

        # Precondition: need category + description to triage
        if not ctx.slots.get("category") or not ctx.slots.get("description"):
            return {"skipped": True, "reason": "category + description not yet known"}

        severity, source, reason = score_severity(ctx)

        ctx.severity = severity
        ctx.severity_source = source
        ctx.priority = _priority_from_matrix(severity, ctx)

        record_action(self._action(
            action_type="severity_scored",
            input_summary=f"slots={ctx.slots}, safety_flags={ctx.safety_flags}",
            output_summary=f"severity={severity} (source={source}); reason={reason}",
        ))
        record_action(self._action(
            action_type="priority_assigned",
            input_summary=f"severity={severity}, safety_flags={ctx.safety_flags}",
            output_summary=f"priority=P{ctx.priority}",
        ))

        return {
            "severity": severity,
            "severity_source": source,
            "reason": reason,
            "priority": ctx.priority,
        }
