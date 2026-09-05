"""Pilot hardening surfaces — SLOs, retention, fairness, cost, voice, quality.

All read-only + hermetic; safe to expose in pilot. Auth follows the same
FRONTLINE_API_KEY gate as other frontline routes via dependencies in main app.
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter

router = APIRouter(prefix="/api/frontline/hardening", tags=["frontline"])


@router.get("/slos")
async def slos() -> dict[str, Any]:
    from src.ops.pilot import STAGE_SLOS, queue_ceiling
    return {"stages": STAGE_SLOS, "queue": queue_ceiling()}


@router.get("/retention")
async def retention() -> dict[str, Any]:
    from src.compliance.retention import retention_table
    return retention_table()


@router.post("/fairness")
async def fairness(payload: dict[str, Any]) -> dict[str, Any]:
    from src.governance.registry import fairness_report
    return fairness_report(payload.get("cases", []))


@router.post("/triage-rank")
async def triage_rank(payload: dict[str, Any]) -> dict[str, Any]:
    from src.ops.pilot import rank_engineer_queue
    return {"ranked": rank_engineer_queue(payload.get("items", []))}


@router.post("/voice/readback-check")
async def voice_readback(payload: dict[str, Any]) -> dict[str, Any]:
    from src.voice.policy import EntityHypothesis, low_confidence_entities, readback_prompt
    hyps = [EntityHypothesis(slot=h.get("slot", ""), value=h.get("value", ""),
                             confidence=float(h.get("confidence", 1.0)),
                             token_confidences=list(h.get("token_confidences") or []))
            for h in payload.get("entities", [])]
    low = low_confidence_entities(hyps)
    return {"low_confidence": [{"slot": h.slot, "value": h.value, "confidence": h.confidence} for h in low],
            "readbacks": [readback_prompt(h.slot, h.value, lang=payload.get("lang", "en")) for h in low]}


@router.post("/quality/check")
async def quality_check(payload: dict[str, Any]) -> dict[str, Any]:
    from src.quality.guards import (cold_start_gate, detect_schema_drift,
                                    null_rate_report, partition_quarantine)
    rows = payload.get("rows", [])
    return {
        "nulls": null_rate_report(rows),
        "quarantine": partition_quarantine(rows, required=payload.get("required", ["entity_1", "category"])),
        "cold_start": cold_start_gate(len(rows)),
        "drift": detect_schema_drift(payload.get("expected_schema", []), payload.get("observed_schema", []))
        if payload.get("expected_schema") else {"drifted": False},
    }


@router.post("/stats/robust")
async def stats_robust(payload: dict[str, Any]) -> dict[str, Any]:
    from src.stats.robust import (apply_fatigue_budget, decompose_seasonal,
                                  detect_shift, spike_on_residual)
    series = [float(v) for v in payload.get("series", [])]
    dec = decompose_seasonal(series)
    return {"decomposition": dec,
            "spikes": spike_on_residual(dec.get("residual", [])),
            "shift": detect_shift(series),
            "fatigue": apply_fatigue_budget(payload.get("alerts", []))}


@router.post("/cost")
async def cost(payload: dict[str, Any]) -> dict[str, Any]:
    from src.ops.pilot import cost_per_contact, kpi_baseline
    return {"cost": cost_per_contact(
        llm_usd=float(payload.get("llm_usd", 0.0)),
        asr_usd=float(payload.get("asr_usd", 0.0)),
        tts_usd=float(payload.get("tts_usd", 0.0))),
        "kpis": kpi_baseline()}
