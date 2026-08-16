"""Grounded NL query: plan a lookup, Qubot-verify every cited row before show."""

from __future__ import annotations

import re
from typing import Any

from src.data.warehouse import domain_con, ops_con
from src.qubot.claims import BoundClaim, audit_bound_claims, cited_text_from_snapshot
from src.qubot.evidence_pin import fetch_record_row


def plan_query(question: str) -> dict[str, Any]:
    """Deterministic planner (LLM optional later). Extracts category/entity tokens."""
    q = (question or "").strip()
    ql = q.lower()
    intent = "similar_records"
    if "how many" in ql or "count" in ql:
        intent = "count"
    tokens = re.findall(r"[A-Za-z0-9][A-Za-z0-9_-]{2,40}", q)
    stop = {
        "show", "the", "and", "for", "with", "about", "records", "cases",
        "how", "many", "count", "similar", "complaints", "on", "in",
    }
    kept = [t for t in tokens if t.lower() not in stop]
    return {
        "intent": intent,
        "question": q,
        "tokens": kept[:6],
        "category": next((t for t in kept if t.isupper() or "brake" in t.lower()), None),
        "entity_2": next((t for t in kept if t[:1].isupper() and t.lower() not in {"show"}), None),
    }


def _search_domain(pack_id: str, plan: dict[str, Any], *, limit: int = 5) -> list[dict[str, Any]]:
    token = (plan.get("tokens") or ["brake"])[0]
    try:
        with domain_con(pack_id) as con:
            rows = con.execute(
                """
                SELECT record_id, text, category, entity_2, source, received_at
                FROM records
                WHERE text ILIKE '%' || ? || '%'
                   OR category ILIKE '%' || ? || '%'
                LIMIT ?
                """,
                [token, token, limit],
            ).fetchall()
            cols = [d[0] for d in con.description]
            return [dict(zip(cols, r)) for r in rows]
    except FileNotFoundError:
        return []


def _claim_for_row(row: dict[str, Any], snippet: str) -> BoundClaim | None:
    text = str(row.get("text") or "")
    rid = str(row.get("record_id") or "")
    if not text or not rid:
        return None
    needle = snippet if snippet and snippet.lower() in text.lower() else text[: min(40, len(text))]
    idx = text.lower().find(needle.lower())
    if idx < 0:
        idx = 0
        needle = text[: min(40, len(text))]
    actual = text[idx : idx + len(needle)]
    return BoundClaim(actual, rid, idx, idx + len(actual))


def grounded_query(
    question: str,
    *,
    pack_id: str = "automotive_nhtsa",
    plant: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Return only rows whose cited span is supported. Planted unsupported rows withheld."""
    plan = plan_query(question)
    rows = _search_domain(pack_id, plan)
    shown: list[dict[str, Any]] = []
    withheld: list[dict[str, Any]] = []

    candidates = list(rows)
    if plant:
        candidates.append(plant)

    for row in candidates:
        rid = str(row.get("record_id") or "")
        live = fetch_record_row(pack_id, rid) if rid and not row.get("planted") else None
        text_src = (live or row).get("text") or ""
        snap = {
            "evidence_id": rid,
            "body_json": {"text": text_src, "record_id": rid},
        }
        claim_text = str(row.get("claim_text") or "")
        if row.get("planted") or row.get("unsupported"):
            claim = BoundClaim(
                claim_text or "engine fire that is not in the source",
                rid or "PLANTED",
                int(row.get("span_start") or 0),
                int(row.get("span_end") or 11),
            )
        else:
            claim = _claim_for_row(live or row, (plan.get("tokens") or [""])[0])
        if claim is None:
            withheld.append({"record_id": rid, "reason": "no_text"})
            continue
        audit = audit_bound_claims([claim], [snap])
        item = {
            "record_id": rid,
            "text": text_src[:240],
            "category": (live or row).get("category"),
            "claim": {
                "claim_text": claim.claim_text,
                "span_start": claim.span_start,
                "span_end": claim.span_end,
            },
        }
        if audit.ok:
            shown.append(item)
        else:
            withheld.append({**item, "reason": "unsupported-claim", "rejected": audit.rejected})

    return {
        "question": question,
        "plan": plan,
        "shown": shown,
        "withheld": withheld,
        "shown_count": len(shown),
        "withheld_count": len(withheld),
    }


__all__ = ["plan_query", "grounded_query"]
