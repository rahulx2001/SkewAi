"""Pilot operability + economics (review §8 + §10 + parts of §9).

  - per-stage SLOs with error budgets (start/turn/enrich/close/scan latency)
  - feature flags per agent (kill Sentinel without redeploy)
  - config validation at boot (bad mapping.yaml fails startup)
  - queue ceiling + migration path; WS scaling contract (sticky or shared)
  - cost-per-contact (LLM + ASR + TTS + compute) + 3 baselined KPIs
  - value attribution (which contact/source/scan → which fix)
  - engineer triage scoring: expected_cost × confidence × lead_time (one list)
  - mapping-error admin UX: line number + column + suggested fix
"""

from __future__ import annotations

import os
import re
from typing import Any


# ── Per-stage SLOs ────────────────────────────────────────────────────────

STAGE_SLOS: dict[str, dict[str, float]] = {
    "start_latency": {"p95_ms": 800, "objective": 0.99},
    "turn_latency": {"p95_ms": 1200, "objective": 0.99},
    "enrichment_p95": {"p95_ms": 10000, "objective": 0.95},
    "close_p95": {"p95_ms": 3000, "objective": 0.99},
    "scan_duration": {"p95_ms": 60000, "objective": 0.95},
}


def check_stage_slo(stage: str, *, p95_ms: float) -> dict[str, Any]:
    spec = STAGE_SLOS.get(stage)
    if not spec:
        return {"stage": stage, "known": False}
    ok = p95_ms <= spec["p95_ms"]
    budget_left = max(0.0, 1.0 - (p95_ms / spec["p95_ms"]))
    return {"stage": stage, "p95_ms": p95_ms, "slo_ms": spec["p95_ms"],
            "met": ok, "error_budget_left": round(budget_left, 3),
            "objective": spec["objective"]}


# ── Feature flags per agent ───────────────────────────────────────────────

_AGENTS = ("intake", "sentiment", "triage", "sentinel", "investigator", "case")


def agent_enabled(agent: str) -> bool:
    """FRONTLINE_AGENT_<NAME>_ENABLED=0 kills one agent without redeploy."""
    key = f"FRONTLINE_AGENT_{str(agent).upper()}_ENABLED"
    raw = (os.getenv(key) or "").strip().lower()
    if raw in {"0", "false", "no", "off"}:
        return False
    return True


def enabled_agents() -> dict[str, bool]:
    return {a: agent_enabled(a) for a in _AGENTS}


# ── Config validation at boot ─────────────────────────────────────────────

def validate_mapping_config(mapping: dict[str, Any]) -> list[str]:
    """Bad mapping.yaml must fail startup, not first request. Returns errors."""
    errors = []
    if not isinstance(mapping, dict):
        return ["mapping must be a mapping"]
    for col in ("entity_1", "category", "description"):
        if col not in mapping:
            errors.append(f"missing required column mapping: {col}")
    for k, v in (mapping.get("columns") or {}).items() if isinstance(mapping.get("columns"), dict) else []:
        if not isinstance(v, str) or not v.strip():
            errors.append(f"column '{k}' maps to empty source")
    return errors


# ── Queue ceiling / WS scaling contract ───────────────────────────────────

def queue_ceiling() -> dict[str, Any]:
    backend = (os.getenv("JOB_BACKEND") or "db-poll").strip()
    return {
        "backend": backend,
        "db_poll_ceiling": "~50 pending + 10 running before alert (see slo.py)",
        "migration_path": "db-poll → Redis/SQS when sustained depth > ceiling for 7d",
        "ws_scaling": "single_worker only (in-process registry); multi-replica requires sticky sessions or shared registry — see /health single_worker",
    }


# ── Cost per contact + KPIs + attribution ─────────────────────────────────

def cost_per_contact(*, llm_usd: float = 0.0, asr_usd: float = 0.0,
                     tts_usd: float = 0.0, compute_usd: float = 0.001) -> dict[str, Any]:
    total = float(llm_usd) + float(asr_usd) + float(tts_usd) + float(compute_usd)
    return {"llm_usd": llm_usd, "asr_usd": asr_usd, "tts_usd": tts_usd,
            "compute_usd": compute_usd, "total_usd": round(total, 6)}


BASELINE_KPIS = ("lead_time_gain_days", "cost_per_defect_found", "reopen_rate_delta")


def kpi_baseline(*, lead_time_gain_days: float = 0.0,
                 cost_per_defect_found: float = 0.0,
                 reopen_rate_delta: float = 0.0) -> dict[str, Any]:
    return {"lead_time_gain_days": lead_time_gain_days,
            "cost_per_defect_found": cost_per_defect_found,
            "reopen_rate_delta": reopen_rate_delta,
            "note": "baseline at pilot start; delta measured per value_attribution"}


def value_attribution(*, contact_id: str, source: str, fix_id: str) -> dict[str, Any]:
    return {"contact_id": contact_id, "source": source, "fix_id": fix_id,
            "story": f"{source}:{contact_id} → {fix_id}"}


# ── Triage scoring: one ranked list ───────────────────────────────────────

def triage_score(*, expected_cost: float, confidence: float,
                 lead_time_weeks: float) -> float:
    """expected_cost × confidence ÷ (1 + lead_time_weeks): urgent+likely first."""
    return float(expected_cost) * float(confidence) / (1.0 + max(0.0, float(lead_time_weeks)))


def rank_engineer_queue(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    scored = [{**it, "_score": triage_score(
        expected_cost=float(it.get("expected_cost", 0.0)),
        confidence=float(it.get("confidence", 0.5)),
        lead_time_weeks=float(it.get("lead_time_weeks", 0.0)))} for it in items]
    return sorted(scored, key=lambda d: d["_score"], reverse=True)


# ── Mapping-error admin UX ────────────────────────────────────────────────

def mapping_error_hint(*, line: int, column: str, value: str = "",
                       expected: str = "") -> dict[str, Any]:
    suggestion = f"check {column} mapping" + (f"; expected {expected}" if expected else "")
    if value and expected and value.strip().lower() != expected.strip().lower():
        suggestion += f"; got '{value}' — case or synonym? add to gazetteer"
    return {"line": line, "column": column, "value": value,
            "expected": expected, "suggested_fix": suggestion}


__all__ = [
    "STAGE_SLOS", "check_stage_slo", "agent_enabled", "enabled_agents",
    "validate_mapping_config", "queue_ceiling", "cost_per_contact",
    "BASELINE_KPIS", "kpi_baseline", "value_attribution",
    "triage_score", "rank_engineer_queue", "mapping_error_hint",
]
