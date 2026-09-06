"""Pilot hardening surfaces — SLOs, retention, fairness, cost, voice, quality.

Authentication and Authorization:
- Gated by `require_api_key` (401 when FRONTLINE_AUTH_REQUIRED=1 and unauthenticated).
- Endpoints enforce per-endpoint RBAC permissions:
  - GET `/slos` -> `ops:read`
  - GET `/retention` -> `ops:read`
  - POST `/fairness` -> `ops:write`
  - POST `/cost` -> `ops:write`
  - Additional diagnostic routes enforce `ops:read`.
- In development open mode (`is_open_mode()`), permissions may be relaxed via
  `open_mode_ok=True`. When `FRONTLINE_AUTH_REQUIRED=1` (production), open mode
  is strictly disabled.
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends

from src.api.auth import require_api_key
from src.api.rbac import get_role, require_perm


def _open_mode_ok() -> bool:
    from src.api.auth import auth_required, is_open_mode

    if auth_required():
        return False
    return is_open_mode()


router = APIRouter(
    prefix="/api/frontline/hardening",
    tags=["frontline"],
    dependencies=[Depends(require_api_key)],
)


@router.get("/health")
async def ops_health(role: str = Depends(get_role)) -> dict[str, Any]:
    from src.observability.health_checks import health_summary

    require_perm(role, "ops:read", open_mode_ok=_open_mode_ok())
    return health_summary()


@router.get("/slos")
async def slos(role: str = Depends(get_role)) -> dict[str, Any]:
    from src.ops.pilot import STAGE_SLOS, queue_ceiling

    require_perm(role, "ops:read", open_mode_ok=_open_mode_ok())
    return {"stages": STAGE_SLOS, "queue": queue_ceiling()}


@router.get("/retention")
async def retention(role: str = Depends(get_role)) -> dict[str, Any]:
    from src.compliance.retention import retention_table

    require_perm(role, "ops:read", open_mode_ok=_open_mode_ok())
    return retention_table()


@router.post("/fairness")
async def fairness(payload: dict[str, Any], role: str = Depends(get_role)) -> dict[str, Any]:
    from src.governance.registry import fairness_report

    require_perm(role, "ops:write", open_mode_ok=_open_mode_ok())
    return fairness_report(payload.get("cases", []))


@router.post("/triage-rank")
async def triage_rank(payload: dict[str, Any], role: str = Depends(get_role)) -> dict[str, Any]:
    from src.ops.pilot import rank_engineer_queue

    require_perm(role, "ops:read", open_mode_ok=_open_mode_ok())
    return {"ranked": rank_engineer_queue(payload.get("items", []))}


@router.post("/voice/readback-check")
async def voice_readback(payload: dict[str, Any], role: str = Depends(get_role)) -> dict[str, Any]:
    from src.voice.policy import EntityHypothesis, low_confidence_entities, readback_prompt

    require_perm(role, "ops:read", open_mode_ok=_open_mode_ok())
    hyps = [
        EntityHypothesis(
            slot=h.get("slot", ""),
            value=h.get("value", ""),
            confidence=float(h.get("confidence", 1.0)),
            token_confidences=list(h.get("token_confidences") or []),
        )
        for h in payload.get("entities", [])
    ]
    low = low_confidence_entities(hyps)
    return {
        "low_confidence": [
            {"slot": h.slot, "value": h.value, "confidence": h.confidence} for h in low
        ],
        "readbacks": [
            readback_prompt(h.slot, h.value, lang=payload.get("lang", "en")) for h in low
        ],
    }


@router.post("/quality/check")
async def quality_check(payload: dict[str, Any], role: str = Depends(get_role)) -> dict[str, Any]:
    from src.quality.guards import (
        cold_start_gate,
        detect_schema_drift,
        null_rate_report,
        partition_quarantine,
    )

    require_perm(role, "ops:read", open_mode_ok=_open_mode_ok())
    rows = payload.get("rows", [])
    return {
        "nulls": null_rate_report(rows),
        "quarantine": partition_quarantine(
            rows, required=payload.get("required", ["entity_1", "category"])
        ),
        "cold_start": cold_start_gate(len(rows)),
        "drift": (
            detect_schema_drift(
                payload.get("expected_schema", []), payload.get("observed_schema", [])
            )
            if payload.get("expected_schema")
            else {"drifted": False}
        ),
    }


@router.post("/stats/robust")
async def stats_robust(payload: dict[str, Any], role: str = Depends(get_role)) -> dict[str, Any]:
    from src.stats.robust import (
        apply_fatigue_budget,
        decompose_seasonal,
        detect_shift,
        spike_on_residual,
    )

    require_perm(role, "ops:read", open_mode_ok=_open_mode_ok())
    series = [float(v) for v in payload.get("series", [])]
    dec = decompose_seasonal(series)
    return {
        "decomposition": dec,
        "spikes": spike_on_residual(dec.get("residual", [])),
        "shift": detect_shift(series),
        "fatigue": apply_fatigue_budget(payload.get("alerts", [])),
    }


@router.post("/cost")
async def cost(payload: dict[str, Any], role: str = Depends(get_role)) -> dict[str, Any]:
    from src.ops.pilot import cost_per_contact, kpi_baseline

    require_perm(role, "ops:write", open_mode_ok=_open_mode_ok())
    return {
        "cost": cost_per_contact(
            llm_usd=float(payload.get("llm_usd", 0.0)),
            asr_usd=float(payload.get("asr_usd", 0.0)),
            tts_usd=float(payload.get("tts_usd", 0.0)),
        ),
        "kpis": kpi_baseline(),
    }

