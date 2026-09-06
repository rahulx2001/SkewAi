"""REST routes for Frontline ops features.

Endpoints:
  GET    /api/frontline/early-warning           → clusters re-scored with live-contact counts
  POST   /api/frontline/simulate                 → replay corpus records as simulated interactions
  GET    /api/frontline/audits                   → list contact audit reports
  GET    /api/frontline/audits/{interaction_id}  → rerun / fetch a contact audit report
  GET    /api/frontline/metrics                  → pilot ops snapshot
  GET    /api/frontline/cases                    → list cases (status/severity/q)
  GET    /api/frontline/cases/export             → CSV export of cases
  GET    /api/frontline/cases/{id}               → case detail + notes
  PATCH  /api/frontline/cases/{id}              → status / followup_draft
  GET    /api/frontline/cases/{id}/notes         → operator notes
  POST   /api/frontline/cases/{id}/notes        → add operator note
  GET    /api/frontline/investigations           → list investigations
  PATCH  /api/frontline/investigations/{id}     → open|monitoring|closed
  GET    /api/frontline/digest                   → generate / fetch the daily digest
  GET    /api/frontline/connectors/status        → outbound connector config + counts
  PUT    /api/frontline/connectors/config        → enable / webhook URL / shared secret
  GET    /api/frontline/connectors/deliveries    → delivery log
  POST   /api/frontline/connectors/deliveries/{id}/replay
  POST   /api/frontline/connectors/export/{case_id}
"""

from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query, Request

from src.api.auth import check_api_key, require_api_key, require_api_key_strict
from src.api.export import build_audit_export
from src.api.limiter import limiter
from src.api.rbac import get_actor, get_role, require_perm, require_perm_dep
from src.config import settings
from src.data.warehouse import ops_con, ops_in_thread
from src.frontline.simulator import simulate as run_simulate
from src.qubot.auditor import REPORTS_DIR, DIGESTS_DIR, audit_interaction, write_daily_digest
from src.qubot.retrievers import (
    case_funnel,
    investigation_status,
    live_risk,
)

router = APIRouter(
    prefix="/api/frontline",
    tags=["frontline"],
    # Cases, audits, digests, early-warning: auth when FRONTLINE_API_KEY is set.
    dependencies=[Depends(require_api_key)],
)


# ── Early warning ────────────────────────────────────────────────────────────


@router.get("/early-warning")
async def early_warning(window_days: int = 7, include_simulated: bool = True) -> dict[str, Any]:
    """Clusters re-scored with live-contact counts joined to backtest lead-time stats."""

    def _load() -> dict[str, Any]:
        risk = live_risk(window_days=window_days)
        funnel = case_funnel(window_days=window_days)
        if not include_simulated:
            with ops_con(read_only=True) as con:
                row = con.execute(
                    """
                    SELECT COUNT(*) FROM interactions
                    WHERE channel = 'simulated'
                      AND started_at >= now() - INTERVAL (? || ' days')
                    """,
                    [str(window_days)],
                ).fetchone()
                funnel["simulated_count"] = row[0] if row else 0
        return {"live_risk": risk, "funnel": funnel}

    return await ops_in_thread(_load)


# ── Simulate ──────────────────────────────────────────────────────────────────


def _simulate_in_thread(count: int, speed: str, pack_id: str | None = None):
    """Run the async simulator in a fresh event loop (off the API loop)."""
    import asyncio as _aio

    return _aio.run(run_simulate(count=count, speed=speed, pack_id=pack_id or None))


@router.post("/simulate")
@limiter.limit("5 per minute")
async def simulate(
    request: Request,
    count: int = 25,
    speed: str = "instant",
    pack_id: str | None = None,
    _auth: bool = Depends(require_api_key),
) -> dict[str, Any]:
    """Replay corpus records as simulated interactions.

    Offloaded via ``asyncio.to_thread`` so blocking DuckDB work does not stall
    live WebSocket contacts on the main event loop (H4).
    Optional ``pack_id`` overrides the active pack (e2e / multi-pack pilots).

    Idempotent (item 45): repeat POSTs with the same ``Idempotency-Key``
    return the stored result instead of re-simulating.
    """
    if count > 100:
        count = 100  # cap to avoid abuse
    from src.api.idempotency import check_idempotency, store_idempotent_result

    material = f"count={count}&speed={speed}&pack_id={pack_id or ''}"
    replay = check_idempotency(request, "simulate", material)
    if replay is not None:
        return replay
    result = await asyncio.to_thread(_simulate_in_thread, count, speed, pack_id)
    out = {
        "completed": result.completed,
        "abandoned": result.abandoned,
        "escalated": result.escalated,
        "cases_created": result.cases_created,
        "investigations_opened": result.investigations_opened,
        "errors": result.errors,
        "pack_id": pack_id,
    }
    store_idempotent_result(request, "simulate", out)
    return out


# ── Ops metrics ──────────────────────────────────────────────────────────────


@router.get("/metrics")
async def frontline_metrics(window_days: int = 7) -> dict[str, Any]:
    """Pilot ops snapshot: open cases, investigations, dead-letters, connectors."""
    from src.frontline.ops import ops_metrics

    return ops_metrics(window_days=window_days)


# ── Cases ────────────────────────────────────────────────────────────────────


def _scrub_or_authorize(
    role: str, scrub_pii: bool, *, surface: str
) -> bool:
    """Default privacy-preserving reads (item 16).

    Returns True when the response must be PII-scrubbed. ``scrub_pii=False``
    is an explicit opt-out that requires the ``dsr:export`` permission —
    ordinary case readers cannot turn redaction off.
    """
    if scrub_pii:
        return True
    require_perm(role, "dsr:export")
    return False


@router.get("/cases/export")
async def export_cases(
    request: Request,
    status: str | None = None,
    severity: str | None = None,
    q: str | None = None,
    limit: int = Query(default=500, ge=1, le=2000),
    scrub_pii: bool = Query(default=True),
    _role: str = Depends(get_role),
    _actor: str = Depends(get_actor),
):
    """CSV export of cases (filters match list endpoint).

    PII is redacted by default; ``scrub_pii=false`` requires ``dsr:export``.
    """
    from fastapi.responses import Response

    from src.api.export import build_manifest
    from src.frontline.dsr import (
        check_dsr_export_rate_limit,
        log_dsr_export_audit,
    )
    from src.frontline.ops import build_cases_csv

    require_perm(_role, "case:read")
    scrub = _scrub_or_authorize(_role, scrub_pii, surface="cases/export")
    if not scrub:
        allowed, retry_after = check_dsr_export_rate_limit(_actor)
        if not allowed:
            raise HTTPException(
                status_code=429,
                detail="DSR export rate limit exceeded",
                headers={"Retry-After": str(retry_after)},
            )
    csv_text, count = build_cases_csv(
        status=status, severity=severity, q=q, limit=limit, scrub_pii=scrub
    )
    if not scrub:
        log_dsr_export_audit(
            principal=_actor,
            scope=f"cases_export:status={status or '*'}:q={q or '*'}",
            record_count=count,
            ip=request.client.host if request.client else None,
        )
    body = csv_text.encode("utf-8")
    manifest = build_manifest(body, count=count)
    return Response(
        content=body,
        media_type="text/csv; charset=utf-8",
        headers={
            "Content-Disposition": 'attachment; filename="cases_export.csv"',
            "X-Export-Count": str(manifest["count"]),
            "X-Export-Sha256": manifest["sha256"],
        },
    )


@router.get("/cases")
@limiter.limit("60 per minute")
async def list_cases(
    request: Request,
    _role: str = Depends(require_perm_dep("case:read")),
    status: str | None = None,
    severity: str | None = None,
    q: str | None = None,
    limit: int = Query(default=50, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
    cursor: str | None = None,
    scrub_pii: bool = Query(default=True),
) -> dict[str, Any]:
    """List cases (filter by status / severity / free-text q).

    Pagination: ``limit``, ``offset`` or opaque ``cursor``; response includes
    ``pagination`` (``has_more``, ``next_offset``, ``next_cursor``).

    Free-text fields are PII-redacted by default; ``scrub_pii=false`` is an
    explicit opt-out requiring ``dsr:export``.
    """
    from src.api.jsonutil import json_safe
    from src.api.pagination import (
        InvalidCursor,
        clamp_limit,
        page_meta,
        resolve_offset_strict,
    )
    from src.security.pii import redact_dict

    scrub = _scrub_or_authorize(_role, scrub_pii, surface="cases")
    try:
        lim = clamp_limit(limit)
        off = resolve_offset_strict(offset=offset, cursor=cursor)
    except InvalidCursor as e:
        raise HTTPException(status_code=400, detail=f"invalid cursor: {e}") from e

    sql = "SELECT * FROM cases"
    params: list[Any] = []
    clauses = []
    if status:
        clauses.append("status = ?")
        params.append(status)
    if severity:
        clauses.append("severity = ?")
        params.append(severity)
    if q and q.strip():
        like = f"%{q.strip()}%"
        clauses.append(
            "(case_id ILIKE ? OR interaction_id ILIKE ? OR category ILIKE ? "
            "OR description_summary ILIKE ? OR investigation_id ILIKE ?)"
        )
        params.extend([like, like, like, like, like])
    if clauses:
        sql += " WHERE " + " AND ".join(clauses)
    # Fetch one extra row to detect has_more without a separate COUNT.
    sql += " ORDER BY created_at DESC LIMIT ? OFFSET ?"
    params.extend([lim + 1, off])

    def _load_cases() -> list[dict[str, Any]]:
        import json

        with ops_con(read_only=True) as con:
            cur = con.execute(sql, params)
            cols = [d[0] for d in con.description]
            out: list[dict[str, Any]] = []
            for r in cur.fetchall():
                d = dict(zip(cols, r))
                for k in ("safety_flags",):
                    v = d.get(k)
                    if isinstance(v, str):
                        try:
                            d[k] = json.loads(v)
                        except Exception:
                            pass
                out.append(json_safe(d))
            return out

    # P1: offload sync DuckDB from the event loop on hot list path.
    import asyncio

    rows = await asyncio.to_thread(_load_cases)
    has_extra = len(rows) > lim
    page = rows[:lim]
    if scrub:
        page = [redact_dict(r) for r in page]
    # Exact total for small tables (item 44): same filters, COUNT(*) — cheap
    # at pilot scale and lets UIs render real page counts.
    total: int | None = None
    if not has_extra:
        total = off + len(page)
    else:
        try:
            def _count() -> int:
                with ops_con(read_only=True) as con:
                    base = sql.split(" ORDER BY ")[0]
                    from_idx = base.upper().find(" FROM ")
                    c = con.execute(
                        "SELECT COUNT(*) " + base[from_idx:], params[:-2]
                    ).fetchone()
                    return int(c[0]) if c else off + len(page)

            total = await asyncio.to_thread(_count)
        except Exception:
            total = None
    return {
        "cases": page,
        "count": len(page),
        "q": q or "",
        "pagination": page_meta(limit=lim, offset=off, returned=len(page), total=total),
    }

@router.get("/cases/{case_id}")
@limiter.limit("120 per minute")
async def get_case(
    request: Request,
    case_id: str,
    _role: str = Depends(require_perm_dep("case:read")),
    scrub_pii: bool = Query(default=True),
) -> dict[str, Any]:
    """Get a single case + its audit report path + notes.

    Free-text fields are PII-redacted by default (``scrub_pii=false`` needs
    ``dsr:export``).
    """
    from src.api.jsonutil import json_safe
    from src.frontline.ops import list_case_notes
    from src.security.pii import redact_dict

    scrub = _scrub_or_authorize(_role, scrub_pii, surface="cases/{id}")

    def _load():
        with ops_con(read_only=True) as con:
            cur = con.execute("SELECT * FROM cases WHERE case_id = ?", [case_id])
            cols = [d[0] for d in con.description]
            return cols, cur.fetchone()

    cols, row = await ops_in_thread(_load)
    if not row:
        raise HTTPException(status_code=404, detail=f"case not found: {case_id}")
    case = dict(zip(cols, row))
    for k in ("safety_flags",):
        v = case.get(k)
        if isinstance(v, str):
            import json
            try:
                case[k] = json.loads(v)
            except Exception:
                pass
    case = json_safe(case)
    # Look up audit report path
    iid = case.get("interaction_id")
    if iid:
        report_path = REPORTS_DIR / f"{iid}.md"
        case["audit_report_path"] = str(report_path) if report_path.exists() else None
        case["audit_report_url"] = f"/api/frontline/audits/{iid}"
    case["notes"] = list_case_notes(case_id)
    if scrub:
        case = redact_dict(case)
        case["notes"] = [
            redact_dict(n) if isinstance(n, dict) else n
            for n in (case.get("notes") or [])
        ]
    return case


@router.patch("/cases/{case_id}")
async def patch_case(
    case_id: str,
    body: dict[str, Any],
    actor: str = Depends(get_actor),
    _role: str = Depends(require_perm_dep("case:write", open_mode_ok=True)),
) -> dict[str, Any]:
    """Update case status and/or follow-up draft (operator lifecycle)."""
    from src.api.jsonutil import json_safe
    from src.frontline.ops import update_case

    if not isinstance(body, dict):
        raise HTTPException(status_code=400, detail="JSON object required")
    try:
        updated = update_case(
            case_id,
            status=body.get("status") if "status" in body else None,
            followup_draft=body.get("followup_draft") if "followup_draft" in body else None,
            author=actor,  # M7: never trust body.author
        )
    except LookupError as e:
        raise HTTPException(status_code=404, detail=str(e)) from e
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    return json_safe(updated)


@router.get("/cases/{case_id}/notes")
async def get_case_notes(
    case_id: str,
    limit: int = 50,
    scrub_pii: bool = Query(default=True),
    _role: str = Depends(require_perm_dep("case:read")),
) -> dict[str, Any]:
    from src.frontline.ops import get_case_row, list_case_notes
    from src.security.pii import redact_dict

    if get_case_row(case_id) is None:
        raise HTTPException(status_code=404, detail=f"case not found: {case_id}")
    notes = list_case_notes(case_id, limit=limit)
    if _scrub_or_authorize(_role, scrub_pii, surface="cases/notes"):
        notes = [redact_dict(n) if isinstance(n, dict) else n for n in notes]
    return {"case_id": case_id, "notes": notes, "count": len(notes)}


@router.post("/cases/{case_id}/notes")
async def post_case_note(
    request: Request,
    case_id: str,
    body: dict[str, Any],
    actor: str = Depends(get_actor),
    _role: str = Depends(require_perm_dep("case:write", open_mode_ok=True)),
) -> dict[str, Any]:
    """Add an operator note on a case.

    Idempotent (item 45): retries with the same ``Idempotency-Key`` return
    the original note instead of duplicating it.
    """
    import json as _json

    from src.api.idempotency import check_idempotency, store_idempotent_result
    from src.frontline.ops import add_case_note

    if not isinstance(body, dict):
        raise HTTPException(status_code=400, detail="JSON object required")
    material = f"{case_id}\n{_json.dumps(body, sort_keys=True, default=str)}"
    replay = check_idempotency(request, "case_note", material)
    if replay is not None:
        return replay
    try:
        note = add_case_note(
            case_id,
            str(body.get("body") or ""),
            author=actor,  # M7: never trust body.author
        )
    except LookupError as e:
        raise HTTPException(status_code=404, detail=str(e)) from e
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    if isinstance(note, dict):
        store_idempotent_result(request, "case_note", note)
    return note


# ── Investigations ───────────────────────────────────────────────────────────


@router.get("/investigations")
async def list_investigations(
    status: str | None = None,
    window_days: int = 30,
    limit: int = Query(default=50, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
    cursor: str | None = None,
) -> dict[str, Any]:
    """List investigations (optionally filter by status). Paginated."""
    from src.api.pagination import paginate_list

    invs = investigation_status(window_days=window_days)
    if status:
        invs = [i for i in invs if i.get("status") == status]
    page, meta = paginate_list(invs, limit=limit, offset=offset, cursor=cursor)
    return {"investigations": page, "count": len(page), "pagination": meta}


@router.get("/investigations/{investigation_id}")
async def get_investigation(investigation_id: str) -> dict[str, Any]:
    """Get a single investigation + linked cases + cluster trend."""
    invs = investigation_status(investigation_id=investigation_id)
    if not invs:
        raise HTTPException(status_code=404, detail=f"investigation not found: {investigation_id}")
    return invs[0]


@router.get("/investigations/{investigation_id}/comments")
async def list_investigation_comments(
    investigation_id: str,
    _role: str = Depends(require_perm_dep("case:read")),
) -> dict[str, Any]:
    """Engineer discussion on an investigation, oldest first."""
    from src.enterprise.investigation_workspace import get_investigation as _get_inv

    try:
        inv = _get_inv(investigation_id)
    except LookupError as e:
        raise HTTPException(status_code=404, detail=str(e)) from e
    comments = inv.get("comments", [])
    return {"investigation_id": investigation_id, "comments": comments, "count": len(comments)}


@router.post("/investigations/{investigation_id}/comments")
@limiter.limit("60 per minute")
async def post_investigation_comment(
    request: Request,
    investigation_id: str,
    body: dict[str, Any],
    actor: str = Depends(get_actor),
    _role: str = Depends(require_perm_dep("case:write", open_mode_ok=True)),
) -> dict[str, Any]:
    """Append an engineer comment. Idempotent via Idempotency-Key."""
    import json as _json

    from src.api.idempotency import check_idempotency, store_idempotent_result
    from src.enterprise.investigation_workspace import add_comment

    if not isinstance(body, dict):
        raise HTTPException(status_code=400, detail="JSON object required")
    material = f"{investigation_id}\n{_json.dumps(body, sort_keys=True, default=str)}"
    replay = check_idempotency(request, "inv_comment", material)
    if replay is not None:
        return replay
    try:
        inv = add_comment(investigation_id, str(body.get("body") or ""), author=actor)
    except LookupError as e:
        raise HTTPException(status_code=404, detail=str(e)) from e
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    out = {"investigation_id": investigation_id, "comments": inv.get("comments", [])}
    store_idempotent_result(request, "inv_comment", out)
    return out


@router.post("/clusters/{cluster_id}/feedback")
async def post_cluster_feedback(
    cluster_id: int,
    body: dict[str, Any],
    actor: str = Depends(get_actor),
    _role: str = Depends(require_perm_dep("case:write", open_mode_ok=True)),
) -> dict[str, Any]:
    """Engineer label correction (board #9): 'this assignment is wrong'.

    verdict ∈ wrong | novel | correct. Stored with author + timestamp;
    clustering jobs consume open 'wrong' rows as cannot-link signals.
    """
    from src.data.warehouse import domain_con, ops_con
    from src.domains.active_pack import resolve_active_pack_id
    from src.ids import new_ulid

    if not isinstance(body, dict):
        raise HTTPException(status_code=400, detail="JSON object required")
    verdict = str(body.get("verdict") or "").strip().lower()
    if verdict not in ("wrong", "novel", "correct"):
        raise HTTPException(status_code=400, detail="verdict must be wrong|novel|correct")
    pack_id = str(body.get("pack_id") or resolve_active_pack_id())
    uid = None
    try:
        with domain_con(pack_id) as con:
            row = con.execute(
                "SELECT cluster_uid FROM clusters WHERE cluster_id = ? AND pack_id = ?",
                [int(cluster_id), pack_id],
            ).fetchone()
            uid = str(row[0]) if row and row[0] else None
    except Exception:
        uid = None
    from src.data.timeutil import utc_now

    fid = "cfb_" + new_ulid()
    with ops_con() as con:
        con.execute(
            """
            INSERT INTO cluster_feedback
            (feedback_id, cluster_id, cluster_uid, pack_id, verdict, note, author, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            [fid, int(cluster_id), uid, pack_id, verdict,
             str(body.get("note") or "")[:2000], actor[:80], utc_now()],
        )
    return {"feedback_id": fid, "cluster_id": int(cluster_id),
            "cluster_uid": uid, "verdict": verdict}


@router.get("/clusters/{cluster_id}/feedback")
async def list_cluster_feedback(
    cluster_id: int,
    pack_id: str | None = None,
    _role: str = Depends(require_perm_dep("case:read")),
) -> dict[str, Any]:
    """List engineer labels for a cluster, newest last."""
    from src.data.warehouse import ops_con
    from src.domains.active_pack import resolve_active_pack_id

    pid = pack_id or resolve_active_pack_id()
    with ops_con(read_only=True) as con:
        try:
            cur = con.execute(
                """
                SELECT feedback_id, verdict, note, author, created_at
                FROM cluster_feedback
                WHERE cluster_id = ? AND pack_id = ?
                ORDER BY created_at
                """,
                [int(cluster_id), pid],
            )
            cols = [d[0] for d in cur.description]
            rows = [dict(zip(cols, r)) for r in cur.fetchall()]
        except Exception:
            rows = []
    return {"cluster_id": int(cluster_id), "pack_id": pid,
            "feedback": rows, "count": len(rows)}


@router.patch("/investigations/{investigation_id}")
async def patch_investigation(
    investigation_id: str,
    body: dict[str, Any],
    actor: str = Depends(get_actor),
    _role: str = Depends(require_perm_dep("case:write", open_mode_ok=True)),
) -> dict[str, Any]:
    """Set investigation status: open | monitoring | closed."""
    from src.frontline.ops import update_investigation

    if not isinstance(body, dict) or "status" not in body:
        raise HTTPException(status_code=400, detail="body.status required")
    try:
        return update_investigation(
            investigation_id,
            status=str(body["status"]),
            author=actor,
        )
    except LookupError as e:
        raise HTTPException(status_code=404, detail=str(e)) from e
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e

# ── Audits ───────────────────────────────────────────────────────────────────


@router.get("/audits/export")
@limiter.limit("10 per minute")
async def export_audits(
    request: Request,
    _role: str = Depends(require_perm_dep("audit:read", open_mode_ok=True)),
    start: str | None = Query(default=None, description="Inclusive start date YYYY-MM-DD"),
    end: str | None = Query(default=None, description="Inclusive end date YYYY-MM-DD"),
    interaction_ids: str | None = Query(
        default=None, description="Comma-separated interaction ids (overrides dates)"
    ),
    limit: int = Query(default=50, ge=1, le=500),
    include_markdown: bool = False,
    format: str = Query(default="json", description="json | csv"),
    _auth: bool = Depends(require_api_key),
) -> dict[str, Any]:
    """Export contacts + ledger actions + groundedness verdicts for a date range.

    Pilot compliance deliverable: JSON or CSV + SHA256 manifest.
    Requires ``FRONTLINE_API_KEY`` when that env var is set.
    """
    from src.api.export import build_audit_export_csv

    ids = None
    if interaction_ids:
        ids = [x.strip() for x in interaction_ids.split(",") if x.strip()]
    fmt = (format or "json").strip().lower()
    try:
        if fmt == "csv":
            return await build_audit_export_csv(
                start=start,
                end=end,
                interaction_ids=ids,
                limit=limit,
                run_auditor=True,
            )
        return await build_audit_export(
            start=start,
            end=end,
            interaction_ids=ids,
            limit=limit,
            include_markdown=include_markdown,
            run_auditor=True,
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e


@router.get("/audits")
@limiter.limit("60 per minute")
async def list_audits(
    request: Request,
    limit: int = Query(default=50, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
    cursor: str | None = None,
    _role: str = Depends(require_perm_dep("audit:read", open_mode_ok=True)),
) -> dict[str, Any]:
    """List available contact audit reports (from disk). Paginated."""
    from src.api.pagination import (
        InvalidCursor,
        clamp_limit,
        page_meta,
        resolve_offset_strict,
    )

    if not REPORTS_DIR.exists():
        return {
            "audits": [],
            "count": 0,
            "pagination": page_meta(limit=limit, offset=0, returned=0, total=0),
        }
    lim = clamp_limit(limit)
    try:
        off = resolve_offset_strict(offset=offset, cursor=cursor)
    except InvalidCursor as e:
        raise HTTPException(status_code=400, detail=f"invalid cursor: {e}") from e
    files = sorted(REPORTS_DIR.glob("*.md"), reverse=True)
    total = len(files)
    slice_files = files[off : off + lim]

    def _rows() -> list[dict[str, str]]:
        out = []
        for f in slice_files:
            iid = f.stem
            with ops_con(read_only=True) as con:
                con.execute(
                    "SELECT outcome FROM interactions WHERE interaction_id = ?", [iid]
                ).fetchone()
            out.append({
                "interaction_id": iid,
                "report_path": str(f),
                "report_url": f"/api/frontline/audits/{iid}",
            })
        return out

    audits = await ops_in_thread(_rows)
    return {
        "audits": audits,
        "count": len(audits),
        "pagination": page_meta(
            limit=lim, offset=off, returned=len(audits), total=total
        ),
    }


@router.get("/audits/{interaction_id}")
@limiter.limit("60 per minute")
async def get_audit(
    request: Request,
    interaction_id: str,
    rerun: bool = False,
    _role: str = Depends(require_perm_dep("audit:read", open_mode_ok=True)),
) -> dict[str, Any]:
    """Get (or rerun) a contact audit report. Rerun requires API key when configured."""
    if rerun:
        # Treat rerun as a write: enforce pilot secret when set.
        check_api_key(
            authorization=request.headers.get("authorization"),
            x_api_key=request.headers.get("x-api-key"),
            api_key=request.query_params.get("api_key"),
        )
        result = await audit_interaction(interaction_id, write_report=True)
        return {
            "interaction_id": interaction_id,
            "overall_verdict": result.overall_verdict,
            "total_actions": result.total_actions,
            "grounded_actions": result.grounded_actions,
            "unverifiable_actions": result.unverifiable_actions,
            "mismatch_actions": result.mismatch_actions,
            "severity_sane": result.severity_sane,
            "peak_frustration": result.peak_frustration,
            "report_path": str(result.report_path) if result.report_path else None,
        }
    # Just return the existing report path (or 404)
    report_path = REPORTS_DIR / f"{interaction_id}.md"
    if not report_path.exists():
        raise HTTPException(status_code=404, detail=f"audit report not found: {report_path}")
    return {
        "interaction_id": interaction_id,
        "report_path": str(report_path),
        "report_markdown": report_path.read_text(encoding="utf-8"),
    }


# ── Digest ───────────────────────────────────────────────────────────────────


@router.get("/digest")
async def get_digest(window_days: int = 1, regenerate: bool = False) -> dict[str, Any]:
    """Generate or fetch the daily digest."""
    if regenerate:
        path = write_daily_digest(window_days=window_days)
    else:
        from datetime import datetime, timezone
        today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        path = DIGESTS_DIR / f"daily_{today}.md"
        if not path.exists():
            path = write_daily_digest(window_days=window_days)
    return {
        "digest_path": str(path),
        "digest_markdown": path.read_text(encoding="utf-8") if path.exists() else "",
    }


@router.post("/digest/run")
async def run_digest_scheduled(
    window_days: int = 1,
    post_webhook: bool = False,
) -> dict[str, Any]:
    """Schedule entrypoint: regenerate digest and optionally post to alert webhook."""
    path = write_daily_digest(window_days=window_days)
    md = path.read_text(encoding="utf-8") if path.exists() else ""
    posted = False
    if post_webhook and md:
        try:
            from src.frontline.alerts import fire_alert

            await fire_alert(
                event="early_warning_threshold",
                summary=f"Daily digest ready ({path.name})",
                ref_id=f"digest:{path.name}",
                extra={"digest_path": str(path), "chars": len(md)},
            )
            posted = True
        except Exception:
            posted = False
    return {
        "ok": True,
        "digest_path": str(path),
        "digest_markdown": md[:2000],
        "webhook_posted": posted,
    }


@router.get("/wallboard")
async def wallboard(pack_id: str | None = None) -> dict[str, Any]:
    """Ops wallboard: live contacts, P1 counts, top risk clusters."""
    from src.frontline.wallboard import build_wallboard

    return build_wallboard(pack_id=pack_id)


@router.get("/insights/csat")
async def insights_csat(
    window_days: int = 7,
    pack_id: str | None = None,
) -> dict[str, Any]:
    """Satisfaction proxy + top themes from real contacts (not survey NPS)."""
    from src.frontline.insights import build_csat_themes

    return build_csat_themes(window_days=window_days, pack_id=pack_id)


@router.get("/insights/product-gap")
async def insights_product_gap(
    window_days: int = 14,
    pack_id: str | None = None,
    limit: int = 8,
) -> dict[str, Any]:
    """Top product issues + severity mix + getting-worse drift."""
    from src.frontline.insights import build_product_gap_board

    return build_product_gap_board(
        window_days=window_days, pack_id=pack_id, limit=limit
    )


@router.get("/explain/{interaction_id}")
@limiter.limit("60 per minute")
async def explain_decision(
    request: Request,
    interaction_id: str,
    _role: str = Depends(require_perm_dep("ledger:read", open_mode_ok=True)),
) -> dict[str, Any]:
    """Why decisions happened: slots, severity source, advisory, cluster, evidence."""
    from src.frontline.explainability import explain_interaction

    out = explain_interaction(interaction_id)
    if not out.get("found"):
        raise HTTPException(status_code=404, detail=f"interaction not found: {interaction_id}")
    return out


@router.get("/cases/status/{case_id}")
async def case_status_lookup(case_id: str) -> dict[str, Any]:
    from src.agents.case_status import format_case_status_reply, get_case_status

    case = get_case_status(case_id)
    if not case:
        raise HTTPException(status_code=404, detail=f"case not found: {case_id}")
    return {"case": case, "reply": format_case_status_reply(case)}


@router.post("/alert-rules")
async def create_alert_rule(body: dict[str, Any]) -> dict[str, Any]:
    from src.frontline.alert_rules import create_rule

    return create_rule(
        name=str(body.get("name") or "rule"),
        pack_id=body.get("pack_id"),
        min_cases=int(body.get("min_cases") or 5),
        window_days=int(body.get("window_days") or 7),
        min_severity=str(body.get("min_severity") or "Medium"),
        action=str(body.get("action") or "alert"),
        enabled=bool(body.get("enabled", True)),
    )


@router.get("/alert-rules")
async def list_alert_rules(pack_id: str | None = None) -> dict[str, Any]:
    from src.frontline.alert_rules import list_rules

    rows = list_rules(pack_id=pack_id)
    return {"rules": rows, "count": len(rows)}


@router.post("/alert-rules/evaluate")
async def evaluate_alert_rule(body: dict[str, Any]) -> dict[str, Any]:
    from src.frontline.alert_rules import (
        apply_triggered_rule,
        evaluate_cluster_rule,
        get_rule,
    )

    rule = body.get("rule") or get_rule(str(body.get("rule_id") or ""))
    if not rule:
        raise HTTPException(status_code=404, detail="rule not found")
    ev = evaluate_cluster_rule(
        rule,
        pack_id=str(body.get("pack_id") or rule.get("pack_id") or "automotive_nhtsa"),
        cluster_id=int(body.get("cluster_id") or 0),
        case_count=int(body.get("case_count") or 0),
        max_severity=str(body.get("max_severity") or "Low"),
    )
    applied = None
    if ev.get("triggered") and body.get("apply"):
        applied = await apply_triggered_rule(ev, title=str(body.get("title") or ""))
    return {"evaluation": ev, "applied": applied}


@router.get("/embedding-shadow/{interaction_id}")
async def embedding_shadow(interaction_id: str) -> dict[str, Any]:
    from src.ml_runtime.embedding_runtime import embedding_mode, shadow_enabled, shadow_kill_switch
    from src.ml_runtime.embedding_shadow import latest_shadow

    row = latest_shadow(interaction_id)
    if not row:
        return {
            "interaction_id": interaction_id,
            "present": False,
            "mode": embedding_mode(),
            "shadow_enabled": shadow_enabled(),
            "shadow_killed": shadow_kill_switch(),
        }
    agree = row.get("hash_cluster_id") == row.get("semantic_cluster_id")
    return {
        "interaction_id": interaction_id,
        "present": True,
        "agree": agree,
        "active": {
            "cluster_id": row.get("hash_cluster_id"),
            "top_score": row.get("hash_top_score"),
            "novel": row.get("hash_novel"),
            "top_ids": row.get("hash_top_ids"),
        },
        "shadow": {
            "cluster_id": row.get("semantic_cluster_id"),
            "top_score": row.get("semantic_top_score"),
            "novel": row.get("semantic_novel"),
            "top_ids": row.get("semantic_top_ids"),
            "status": row.get("semantic_status"),
        },
        "rank_overlap": row.get("rank_overlap"),
        "mode": embedding_mode(),
        "shadow_killed": shadow_kill_switch(),
    }


@router.post("/embedding-shadow/{interaction_id}/flag")
async def flag_embedding_shadow(interaction_id: str, body: dict[str, Any] | None = None) -> dict[str, Any]:
    from src.ml_runtime.embedding_shadow import flag_shadow_wrong

    body = body or {}
    fid = flag_shadow_wrong(
        interaction_id,
        reviewer=str(body.get("reviewer") or "human-supervisor"),
        comment=str(body.get("comment") or ""),
    )
    return {"flag_id": fid, "queued_for_eval": True}


@router.get("/eval/labels/next")
async def eval_next(annotator_id: str = Query(..., min_length=7)) -> dict[str, Any]:
    from src.eval.embedding_labels import LABEL_CLASSES, next_unlabeled_item as _next

    item = _next(annotator_id)
    if item is None:
        return {"item": None}
    return {"item": item, "classes": list(LABEL_CLASSES)}


@router.post("/eval/labels")
async def eval_submit(body: dict[str, Any]) -> dict[str, Any]:
    from src.eval.embedding_labels import submit_label

    rid = submit_label(
        eval_id=str(body.get("eval_id") or ""),
        annotator_id=str(body.get("annotator_id") or ""),
        label=str(body.get("label") or ""),
        source_record_id=body.get("source_record_id"),
        notes=str(body.get("notes") or ""),
    )
    return {"label_row_id": rid}


@router.post("/eval/labels/adjudicate")
async def eval_adjudicate(body: dict[str, Any]) -> dict[str, Any]:
    from src.eval.embedding_labels import adjudicate

    rid = adjudicate(
        eval_id=str(body.get("eval_id") or ""),
        adjudicator_id=str(body.get("adjudicator_id") or ""),
        label=str(body.get("label") or ""),
        notes=str(body.get("notes") or ""),
    )
    return {"label_row_id": rid}


@router.get("/eval/labels/agreement")
async def eval_agreement() -> dict[str, Any]:
    from src.eval.embedding_gates import acceptance_eligibility
    from src.eval.embedding_labels import agreement_report

    return {"agreement": agreement_report(), "eligibility": acceptance_eligibility()}


@router.post("/sentiment-disagreements")
async def sentiment_disagree(body: dict[str, Any]) -> dict[str, Any]:
    from src.frontline.sentiment_review import log_sentiment_disagreement, revisit_ready

    rid = log_sentiment_disagreement(
        interaction_id=str(body.get("interaction_id") or ""),
        human_decision=str(body.get("human_decision") or "wrong"),
        system_sentiment_score=body.get("system_sentiment_score"),
        system_handoff_decision=body.get("system_handoff_decision"),
        reviewer_comment=str(body.get("reviewer_comment") or ""),
    )
    return {"review_id": rid, "revisit_ready": revisit_ready()}


@router.post("/clusters/rebuild")
async def rebuild_clusters_api(pack_id: str = "automotive_nhtsa", k: int = 5) -> dict[str, Any]:
    from src.ml_runtime.clustering import rebuild_clusters

    return rebuild_clusters(pack_id, k=k)


@router.get(
    "/dsr/{interaction_id}",
    dependencies=[Depends(require_api_key_strict)],
)
@limiter.limit("30 per minute")
async def dsr_export(
    request: Request,
    interaction_id: str,
    role: str = Depends(get_role),
    actor: str = Depends(get_actor),
) -> dict[str, Any]:
    """Export ops rows for one interaction (always auth — FIND-004)."""
    from src.api.rbac import require_perm
    from src.frontline.dsr import (
        check_dsr_export_rate_limit,
        export_interaction,
        log_dsr_export_audit,
    )
    from src.security.audit_log import security_event

    require_perm(role, "dsr:export")
    allowed, retry_after = check_dsr_export_rate_limit(actor)
    if not allowed:
        raise HTTPException(
            status_code=429,
            detail="DSR export rate limit exceeded",
            headers={"Retry-After": str(retry_after)},
        )
    try:
        out = export_interaction(interaction_id)
        rec_count = len(out.get("turns") or []) + len(out.get("cases") or [])
        log_dsr_export_audit(
            principal=actor,
            scope=f"interaction:{interaction_id}",
            record_count=rec_count,
            ip=request.client.host if request.client else None,
        )
        security_event(
            "dsr.export",
            outcome="success",
            role=role,
            resource=interaction_id,
            ip=request.client.host if request.client else None,
        )
        return out
    except Exception as e:
        security_event(
            "dsr.export",
            outcome="failure",
            role=role,
            resource=interaction_id,
            detail={"error": type(e).__name__},
            ip=request.client.host if request.client else None,
        )
        raise


@router.delete(
    "/dsr/{interaction_id}",
    dependencies=[Depends(require_api_key_strict)],
)
@limiter.limit("10 per minute")
async def dsr_delete(
    request: Request,
    interaction_id: str,
    role: str = Depends(get_role),
    mode: str = Query(default="tombstone"),
) -> dict[str, Any]:
    """Erase ops rows for one interaction (admin only — FIND-004).

    Modes (audit 7.3): ``tombstone`` (default) preserves hash-chain
    verifiability while removing PII content; ``erase`` is the legacy hard
    delete (chain segment for the contact cannot be re-verified after).
    """
    from src.api.rbac import require_perm
    from src.frontline.dsr import delete_interaction
    from src.security.audit_log import security_event

    require_perm(role, "dsr:delete")
    if mode not in ("tombstone", "erase"):
        raise HTTPException(status_code=400, detail="mode must be 'tombstone' or 'erase'")
    try:
        out = delete_interaction(interaction_id, mode=mode)
        security_event(
            "dsr.delete",
            outcome="success",
            role=role,
            resource=interaction_id,
            ip=request.client.host if request.client else None,
        )
        return out
    except Exception as e:
        security_event(
            "dsr.delete",
            outcome="failure",
            role=role,
            resource=interaction_id,
            detail={"error": type(e).__name__},
            ip=request.client.host if request.client else None,
        )
        raise


@router.post("/archives/{interaction_id}")
async def create_archive(interaction_id: str) -> dict[str, Any]:
    from src.frontline.archive import build_audit_archive

    return build_audit_archive(interaction_id)


# ── Alert dead-letter admin (L3) ─────────────────────────────────────────────


@router.get("/alerts/dead-letter")
async def list_alert_dead_letters(
    status: str = "pending",
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    cursor: str | None = None,
) -> dict[str, Any]:
    """List failed webhook deliveries (requires FRONTLINE_API_KEY when set)."""
    from src.api.pagination import paginate_list
    from src.frontline.alerts import list_dead_letters

    rows = list_dead_letters(limit=200, status=status)
    page, meta = paginate_list(rows, limit=limit, offset=offset, cursor=cursor)
    return {"dead_letters": page, "count": len(page), "pagination": meta}


@router.post("/alerts/dead-letter/{dead_letter_id}/replay")
async def replay_alert_dead_letter(dead_letter_id: str) -> dict[str, Any]:
    """Re-POST a pending dead-letter payload once."""
    from src.frontline.alerts import replay_dead_letter

    ok = await replay_dead_letter(dead_letter_id)
    if not ok:
        raise HTTPException(
            status_code=404,
            detail=f"dead-letter not found, not pending, or replay failed: {dead_letter_id}",
        )
    return {"ok": True, "dead_letter_id": dead_letter_id}


# ── Outbound connector (generic HTTP + dry-run outbox; not CRM) ─────────────


@router.get("/connectors/status")
async def connector_status() -> dict[str, Any]:
    """Connector config (secrets redacted) + delivery counts."""
    from src.frontline.connectors import delivery_counts, get_connector_config

    cfg = get_connector_config(include_secret=False)
    return {
        "enabled": cfg.get("enabled", False),
        "webhook_url_redacted": cfg.get("webhook_url_redacted", ""),
        "shared_secret_set": cfg.get("shared_secret_set", False),
        "sink": "outbox+http" if cfg.get("webhook_url") or cfg.get("webhook_url_redacted") else "outbox",
        "note": (
            "Generic outbound HTTP + dry-run outbox only. "
            "Not Salesforce/ServiceNow/Twilio product integration."
        ),
        "delivery_counts": delivery_counts(),
    }


@router.put("/connectors/config")
async def connector_config_put(body: dict[str, Any]) -> dict[str, Any]:
    """Enable/disable connector and set webhook URL + optional shared secret."""
    from src.frontline.connectors import get_connector_config, set_connector_config

    if not isinstance(body, dict):
        raise HTTPException(status_code=400, detail="JSON object required")
    enabled = body.get("enabled")
    webhook_url = body.get("webhook_url")
    shared_secret = body.get("shared_secret")
    # Allow partial updates; treat explicit null shared_secret as clear.
    kwargs: dict[str, Any] = {}
    if "enabled" in body:
        kwargs["enabled"] = bool(enabled)
    if "webhook_url" in body:
        kwargs["webhook_url"] = "" if webhook_url is None else str(webhook_url)
    if "shared_secret" in body:
        kwargs["shared_secret"] = "" if shared_secret is None else str(shared_secret)
    if not kwargs:
        return get_connector_config(include_secret=False)
    try:
        return set_connector_config(**kwargs)
    except ValueError as e:
        # SSRF / URL guard failures → 400 (H6), not unhandled 500
        raise HTTPException(status_code=400, detail=str(e)) from e


@router.get("/connectors/deliveries")
async def connector_deliveries_list(
    status: str | None = None,
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    cursor: str | None = None,
) -> dict[str, Any]:
    """List outbound connector deliveries (newest first). Paginated."""
    from src.api.pagination import paginate_list
    from src.frontline.connectors import list_deliveries

    rows = list_deliveries(limit=200, status=status)
    page, meta = paginate_list(rows, limit=limit, offset=offset, cursor=cursor)
    return {"deliveries": page, "count": len(page), "pagination": meta}


@router.post("/connectors/deliveries/{delivery_id}/replay")
async def connector_delivery_replay(delivery_id: str) -> dict[str, Any]:
    """Re-POST a pending/failed connector delivery once."""
    from src.frontline.connectors import replay_delivery

    ok = await replay_delivery(delivery_id)
    if not ok:
        raise HTTPException(
            status_code=404,
            detail=(
                f"delivery not found, not re-playable, or replay failed: {delivery_id}"
            ),
        )
    return {"ok": True, "delivery_id": delivery_id}


@router.post("/connectors/export/{case_id}")
async def connector_export_case(case_id: str) -> dict[str, Any]:
    """Manually export one case: audited outbox + ledger linkage."""
    from src.frontline.connectors import build_case_payload_from_db, export_audited_signal

    payload = build_case_payload_from_db(case_id)
    if payload is None:
        raise HTTPException(status_code=404, detail=f"case not found: {case_id}")
    return export_audited_signal(
        "manual_export",
        case_id=case_id,
        interaction_id=payload.get("interaction_id"),
        investigation_id=payload.get("investigation_id"),
        pack_id=payload.get("pack_id"),
        cluster_id=payload.get("cluster_id"),
        severity=payload.get("severity"),
        priority=payload.get("priority"),
        category=payload.get("category"),
        payload=payload,
    )


__all__ = ["router"]
