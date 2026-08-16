"""Returning-caller case status lookup by case number (feature #15)."""

from __future__ import annotations

import re
from typing import Any

from src.data.warehouse import ops_con

# Match minted case_ids like case_01HZ... or case_status_demo_1
_CASE_ID_RE = re.compile(r"\b(case_[a-z0-9_]+)\b", re.I)


def extract_case_id_from_text(text: str) -> str | None:
    if not text:
        return None
    m = _CASE_ID_RE.search(text)
    if m:
        return m.group(1)
    # "case 01HZ..." with space
    m2 = re.search(r"\bcase\s+([a-z0-9_]{6,})\b", text, re.I)
    if m2:
        token = m2.group(1)
        return token if token.startswith("case_") else f"case_{token}"
    return None


def get_case_status(case_id: str) -> dict[str, Any] | None:
    """Return case + investigation linkage for a known case_id."""
    cid = (case_id or "").strip()
    if not cid:
        return None
    with ops_con(read_only=True) as con:
        row = con.execute(
            """
            SELECT case_id, interaction_id, pack_id, status, severity, priority,
                   category, description_summary, investigation_id, created_at,
                   followup_draft
            FROM cases WHERE case_id = ?
            """,
            [cid],
        ).fetchone()
        if not row:
            # try with case_ prefix
            if not cid.startswith("case_"):
                row = con.execute(
                    """
                    SELECT case_id, interaction_id, pack_id, status, severity, priority,
                           category, description_summary, investigation_id, created_at,
                           followup_draft
                    FROM cases WHERE case_id = ?
                    """,
                    [f"case_{cid}"],
                ).fetchone()
        if not row:
            return None
        cols = [
            "case_id",
            "interaction_id",
            "pack_id",
            "status",
            "severity",
            "priority",
            "category",
            "description_summary",
            "investigation_id",
            "created_at",
            "followup_draft",
        ]
        d = dict(zip(cols, row))
        inv = None
        if d.get("investigation_id"):
            inv_row = con.execute(
                """
                SELECT investigation_id, title, status, case_count, cluster_id
                FROM investigations WHERE investigation_id = ?
                """,
                [d["investigation_id"]],
            ).fetchone()
            if inv_row:
                inv = {
                    "investigation_id": inv_row[0],
                    "title": inv_row[1],
                    "status": inv_row[2],
                    "case_count": inv_row[3],
                    "cluster_id": inv_row[4],
                }
        d["investigation"] = inv
        if d.get("created_at") is not None:
            d["created_at"] = str(d["created_at"])
    return d


def format_case_status_reply(case: dict[str, Any]) -> str:
    inv = case.get("investigation") or {}
    parts = [
        f"Case {case['case_id']} is currently {case.get('status') or 'unknown'}",
        f"severity {case.get('severity') or 'n/a'}",
        f"priority P{case.get('priority') or '?'}",
    ]
    if case.get("category"):
        parts.append(f"category {case['category']}")
    line = ", ".join(parts) + "."
    if inv:
        line += (
            f" It is linked to investigation {inv.get('investigation_id')} "
            f"({inv.get('status')}, cluster #{inv.get('cluster_id')}, "
            f"{inv.get('case_count')} cases)."
        )
    else:
        line += " No open investigation is linked yet."
    if case.get("followup_draft"):
        line += " A follow-up draft is on file for the operator."
    return line


def try_case_status_from_utterance(text: str) -> dict[str, Any] | None:
    """If utterance references a case id, return status payload + spoken reply."""
    cid = extract_case_id_from_text(text)
    if not cid:
        return None
    case = get_case_status(cid)
    if not case:
        return {
            "found": False,
            "case_id": cid,
            "reply": f"I could not find case {cid} in our system.",
        }
    return {
        "found": True,
        "case_id": case["case_id"],
        "case": case,
        "reply": format_case_status_reply(case),
    }


__all__ = [
    "extract_case_id_from_text",
    "get_case_status",
    "format_case_status_reply",
    "try_case_status_from_utterance",
]
