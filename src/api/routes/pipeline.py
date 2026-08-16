"""API for data-trust, provenance, queue, commercial, onboarding, analyst/ops."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, File, Header, HTTPException, UploadFile
from fastapi.responses import FileResponse

from src.api.auth import require_api_key
from src.config import REPO_ROOT

router = APIRouter(
    prefix="/api/frontline",
    tags=["pipeline"],
    dependencies=[Depends(require_api_key)],
)


@router.get("/trust/kpis")
async def trust_kpis() -> dict[str, Any]:
    from src.frontline.provenance import list_kpis

    return {"kpis": list_kpis()}


@router.get("/provenance/kpis")
async def provenance_kpis() -> dict[str, Any]:
    from src.frontline.provenance import list_kpis

    return {"kpis": list_kpis()}


@router.get("/provenance/kpis/{kpi_id}")
async def provenance_kpi(kpi_id: str, record_id: str | None = None, pack_id: str | None = None) -> dict[str, Any]:
    from src.frontline.provenance import figure_lineage

    try:
        return figure_lineage(kpi_id, record_id=record_id, pack_id=pack_id)
    except KeyError as e:
        raise HTTPException(404, f"unknown kpi {e}") from e


@router.get("/validation-queue")
async def validation_queue() -> dict[str, Any]:
    from src.frontline.validation_queue import list_queue_all

    items = list_queue_all()
    return {"items": items, "count": len(items)}


@router.post("/sandbox/boot")
async def sandbox_boot(body: dict[str, Any] | None = None) -> dict[str, Any]:
    from src.frontline.sandbox import boot_sandbox

    body = body or {}
    return boot_sandbox(pack_id=str(body.get("pack_id") or "automotive_nhtsa"))


@router.post("/pack-builder/profile")
async def pack_builder_profile(file: UploadFile = File(...)) -> dict[str, Any]:
    """Upload a CSV: save it, propose column mapping, lint."""
    from pathlib import Path
    from src.domains.builder.pack_builder import lint_mapping, profile_csv

    dest_dir = REPO_ROOT / "data" / "uploads"
    dest_dir.mkdir(parents=True, exist_ok=True)
    safe = Path(file.filename or "upload.csv").name or "upload.csv"
    dest = dest_dir / safe
    dest.write_bytes(await file.read())
    profile = profile_csv(dest)
    lint = lint_mapping(profile["proposed_mapping"], profile["columns"])
    return {**profile, "lint": lint, "csv_path": str(dest)}


@router.post("/pack-builder/insight")
async def pack_builder_insight(body: dict[str, Any]) -> dict[str, Any]:
    from pathlib import Path
    from src.domains.builder.pack_builder import first_insight_from_csv

    csv_path = body.get("csv_path")
    if not csv_path:
        raise HTTPException(400, "csv_path required")
    return first_insight_from_csv(
        Path(csv_path),
        mapping=body.get("mapping"),
        pack_id=str(body.get("pack_id") or "builder_preview"),
        display_name=str(body.get("display_name") or "Preview pack"),
        out_root=REPO_ROOT / "data" / "builder_packs",
    )


@router.post("/marketplace/install/{pack_id}")
async def marketplace_install(pack_id: str) -> dict[str, Any]:
    from src.domains.marketplace import install_vertical

    try:
        return install_vertical(pack_id)
    except FileNotFoundError as e:
        raise HTTPException(404, str(e)) from e


@router.get("/usage")
async def usage(tenant_id: str = "default") -> dict[str, Any]:
    from src.frontline.billing import usage_dashboard

    return usage_dashboard(tenant_id)


@router.post("/billing/checkout")
async def billing_checkout(body: dict[str, Any]) -> dict[str, Any]:
    from src.frontline.billing import stripe_checkout

    return stripe_checkout(
        str(body.get("tenant_id") or "default"),
        plan=str(body.get("plan") or "pilot"),
        amount_cents=int(body.get("amount_cents") or 9900),
    )


@router.post("/billing/webhook")
async def billing_webhook(body: dict[str, Any]) -> dict[str, Any]:
    from src.frontline.billing import stripe_webhook

    return stripe_webhook(body)


@router.post("/seats")
async def seats_assign(body: dict[str, Any]) -> dict[str, Any]:
    from src.frontline.billing import assign_seat

    try:
        return assign_seat(
            str(body.get("tenant_id") or "default"),
            str(body.get("user_id") or "user"),
            str(body.get("role") or "agent"),
        )
    except PermissionError as e:
        raise HTTPException(403, str(e)) from e


@router.post("/keys")
async def keys_create(body: dict[str, Any]) -> dict[str, Any]:
    from src.security.scoped_keys import create_scoped_key

    return create_scoped_key(
        list(body.get("scopes") or ["kpi:read"]),
        tenant_id=str(body.get("tenant_id") or "default"),
    )


@router.get("/webhooks/catalog")
async def webhooks_catalog() -> dict[str, Any]:
    from src.frontline.webhook_catalog import list_catalog

    return {"events": list_catalog()}


@router.post("/webhooks/tick")
async def webhooks_tick(body: dict[str, Any] | None = None) -> dict[str, Any]:
    from src.frontline.webhook_catalog import fire_due_tick

    body = body or {}
    return fire_due_tick(force=True, channel=str(body.get("channel") or "slack"))


@router.post("/nl/query")
async def nl_query(body: dict[str, Any]) -> dict[str, Any]:
    from src.enterprise.grounded_nl import grounded_query

    return grounded_query(
        str(body.get("question") or ""),
        pack_id=str(body.get("pack_id") or "automotive_nhtsa"),
        plant=body.get("plant") if isinstance(body.get("plant"), dict) else None,
    )


@router.post("/views")
async def views_save(body: dict[str, Any]) -> dict[str, Any]:
    from src.frontline.saved_views import save_view

    return save_view(str(body.get("name") or "untitled"), body.get("spec") or {})


@router.post("/reports")
async def reports_build(body: dict[str, Any]) -> dict[str, Any]:
    from src.frontline.reports import build_report

    return build_report(str(body.get("title") or "Report"), kpi_ids=body.get("kpi_ids"), notes=str(body.get("notes") or ""))


@router.post("/reports/digest")
async def reports_digest(body: dict[str, Any] | None = None) -> dict[str, Any]:
    from src.frontline.reports import run_scheduled_digest

    body = body or {}
    return run_scheduled_digest(body.get("report_id"))


@router.get("/ops/slo")
async def ops_slo() -> dict[str, Any]:
    from src.observability.slo import job_queue_status, slo_dashboard

    return {"slo": slo_dashboard(), "jobs": job_queue_status()}


@router.get("/ops/workers")
async def ops_workers() -> dict[str, Any]:
    from src.jobs.registry import list_workers

    return {"workers": list_workers()}


@router.post("/compliance/{key}/toggle")
async def compliance_toggle(key: str, body: dict[str, Any] | None = None) -> dict[str, Any]:
    from src.frontline.compliance_packs import toggle_pack

    body = body or {}
    try:
        return toggle_pack(key, bool(body.get("enabled", True)))
    except KeyError as e:
        raise HTTPException(404, str(e)) from e


@router.get("/compliance/{key}/template")
async def compliance_template(key: str) -> dict[str, Any]:
    from src.frontline.compliance_packs import evidence_template

    try:
        return evidence_template(key, record_id="NHTSA-100001", investigation_id="inv_0001", interaction_id="int_demo")
    except KeyError as e:
        raise HTTPException(404, str(e)) from e


@router.get("/copq/rank")
async def copq_rank(window_days: int = 7) -> dict[str, Any]:
    from src.qubot.retrievers import live_risk_by_dollar

    rows = live_risk_by_dollar(window_days)
    return {"clusters": rows}


@router.get("/copq/roi")
async def copq_roi(issues_caught: int = 0, copq_per_issue: float = 0, lead_time_weeks: float = 0) -> dict[str, Any]:
    from src.frontline.copq import roi_attribution

    return roi_attribution(
        issues_caught=issues_caught,
        copq_per_issue=copq_per_issue,
        lead_time_weeks=lead_time_weeks,
    )


@router.get("/analytics/hotspots-map")
async def hotspots_map(pack_id: str | None = None, window_days: int = 90) -> dict[str, Any]:
    from src.frontline.analytics import geographic_hotspots

    return geographic_hotspots(pack_id=pack_id, window_days=window_days)


@router.get("/widget/skew-widget.js")
async def widget_script() -> FileResponse:
    path = REPO_ROOT / "dashboard" / "public" / "skew-widget.js"
    if not path.is_file():
        raise HTTPException(404, "widget missing")
    return FileResponse(path, media_type="application/javascript")


@router.get("/scoped")
async def scoped_probe(x_scoped_key: str | None = Header(default=None, alias="X-Scoped-Key")) -> dict[str, Any]:
    from src.security.scoped_keys import authenticate_scoped

    result = authenticate_scoped(x_scoped_key or "", "kpi:read")
    if not result.get("ok"):
        raise HTTPException(403, result.get("reason") or "denied")
    from src.frontline.provenance import list_kpis

    return {"ok": True, "kpis": list_kpis()}
