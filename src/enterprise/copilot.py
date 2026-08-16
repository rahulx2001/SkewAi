"""Supervisor Copilot — deterministic intent router over the ops warehouse.

Not a generative LLM. Maps natural-language-ish queries to fixed intents and
runs warehouse SQL. Honest offline answers for pilot supervisors.
"""

from __future__ import annotations

import re
from datetime import datetime
from typing import Any

from src.data.warehouse import ops_con

COPILOT_SUGGESTIONS = [
    "Which customers are most frustrated?",
    "Show open critical cases",
    "Which agent is causing the most escalations?",
    "Show conversations similar to case_…",
    "Show high risk contacts",
    "Show entity memory for Toyota Camry",
    "Show pending connector deliveries",
    "Why are contacts taking longer?",
    "Show open cases",
    "Show active contacts",
]


def _iso(v: Any) -> Any:
    if isinstance(v, datetime):
        return v.isoformat()
    return v


def _detect_intent(q: str) -> tuple[str, dict[str, str]]:
    ql = (q or "").strip().lower()
    params: dict[str, str] = {}

    m = re.search(r"case[_\s#:-]*([a-z0-9_]+)", ql)
    if m and ("similar" in ql or "like" in ql):
        raw = m.group(1)
        params["case_id"] = raw if raw.startswith("case_") else "case_" + raw
        params["case_raw"] = raw
        return "similar_to_case", params

    # Entity memory: "memory for Toyota" / "entity memory 2019 Camry"
    if "memory" in ql or ("previous" in ql and ("issue" in ql or "contact" in ql)):
        # pull last 1–3 tokens that look like entities
        tokens = re.findall(r"[A-Za-z0-9][A-Za-z0-9_-]{1,40}", q or "")
        # drop stopwords
        stop = {
            "show", "memory", "entity", "for", "the", "a", "an", "me", "about",
            "previous", "issues", "contacts", "lookup", "get", "find",
        }
        ents = [t for t in tokens if t.lower() not in stop][:3]
        if ents:
            params["entity_1"] = ents[0] if len(ents) > 0 else ""
            params["entity_2"] = ents[1] if len(ents) > 1 else ""
            params["entity_3"] = ents[2] if len(ents) > 2 else ""
            return "entity_memory", params

    if "connector" in ql or "outbox" in ql or "delivery" in ql:
        return "connector_pending", params
    if ("critical" in ql and "case" in ql) or "p1" in ql or "severity critical" in ql:
        return "critical_cases", params
    if ("high risk" in ql or "risk score" in ql or "risky" in ql
            or ("risk" in ql and ("contact" in ql or "call" in ql or "active" in ql))):
        return "high_risk", params
    if "frustrat" in ql or "angry" in ql or "upset" in ql:
        return "most_frustrated", params
    if "escalat" in ql and ("agent" in ql or "who" in ql or "causing" in ql):
        return "escalation_by_agent", params
    if "escalat" in ql:
        return "recent_escalations", params
    if "longer" in ql or "duration" in ql or "slow" in ql:
        return "long_contacts", params
    if "finance" in ql or "cfpb" in ql:
        params["pack"] = "finance_cfpb"
        return "pack_stats", params
    if "automotive" in ql or "nhtsa" in ql:
        params["pack"] = "automotive_nhtsa"
        return "pack_stats", params
    if "open case" in ql or "cases open" in ql or "open cases" in ql:
        return "open_cases", params
    if "active" in ql and ("call" in ql or "contact" in ql or "interaction" in ql):
        return "active_contacts", params
    if "help" in ql or "what can" in ql:
        return "help", params
    return "help", params


def list_copilot_suggestions() -> list[str]:
    return list(COPILOT_SUGGESTIONS)


def answer_supervisor_query(query: str, *, limit: int = 10) -> dict[str, Any]:
    """Answer a supervisor question via deterministic intents."""
    intent, params = _detect_intent(query)
    limit = min(max(int(limit), 1), 50)
    rows: list[dict[str, Any]] = []
    answer = ""

    if intent == "help":
        answer = (
            "I answer ops questions from the warehouse (no live LLM). Try: "
            + "; ".join(COPILOT_SUGGESTIONS[:6])
            + "."
        )
        return {
            "query": query,
            "intent": intent,
            "answer": answer,
            "rows": [],
            "row_count": 0,
            "suggestions": list(COPILOT_SUGGESTIONS),
            "engine": "deterministic_intent_router",
            "note": "Not a generative LLM; answers are warehouse SQL via intent routing.",
        }

    with ops_con(read_only=True) as con:
        if intent == "most_frustrated":
            cur = con.execute(
                """
                SELECT interaction_id, pack_id, peak_frustration, last_frustration,
                       status, category, entity_1, entity_2, entity_3, started_at
                FROM interactions
                WHERE peak_frustration IS NOT NULL
                ORDER BY peak_frustration DESC
                LIMIT ?
                """,
                [limit],
            )
            cols = [d[0] for d in cur.description]
            rows = [dict(zip(cols, r)) for r in cur.fetchall()]
            answer = f"Top {len(rows)} contacts by peak frustration."

        elif intent == "escalation_by_agent":
            cur = con.execute(
                """
                SELECT agent, COUNT(*) AS action_count,
                       SUM(CASE WHEN action_type IN ('escalated', 'safety_flag_raised', 'alert_sent')
                                THEN 1 ELSE 0 END) AS escalation_signals
                FROM agent_actions
                GROUP BY agent
                ORDER BY escalation_signals DESC, action_count DESC
                """
            )
            cols = [d[0] for d in cur.description]
            rows = [dict(zip(cols, r)) for r in cur.fetchall()]
            top = rows[0]["agent"] if rows else "n/a"
            answer = f"Agent with most escalation-related ledger signals: {top}."

        elif intent == "recent_escalations":
            cur = con.execute(
                """
                SELECT interaction_id, status, outcome, peak_frustration, category, started_at
                FROM interactions
                WHERE status = 'escalated' OR outcome = 'escalated_safety'
                ORDER BY COALESCE(ended_at, started_at) DESC
                LIMIT ?
                """,
                [limit],
            )
            cols = [d[0] for d in cur.description]
            rows = [dict(zip(cols, r)) for r in cur.fetchall()]
            answer = f"{len(rows)} recent escalated contacts."

        elif intent == "long_contacts":
            cur = con.execute(
                """
                SELECT i.interaction_id, i.pack_id, i.status,
                       COUNT(t.turn_id) AS turn_count,
                       i.peak_frustration, i.started_at
                FROM interactions i
                LEFT JOIN interaction_turns t ON t.interaction_id = i.interaction_id
                GROUP BY i.interaction_id, i.pack_id, i.status, i.peak_frustration, i.started_at
                ORDER BY turn_count DESC
                LIMIT ?
                """,
                [limit],
            )
            cols = [d[0] for d in cur.description]
            rows = [dict(zip(cols, r)) for r in cur.fetchall()]
            answer = f"Longest contacts by turn count ({len(rows)} rows)."

        elif intent == "pack_stats":
            pack = params.get("pack", "automotive_nhtsa")
            cur = con.execute(
                """
                SELECT
                  COUNT(*) AS interactions,
                  SUM(CASE WHEN status = 'completed' THEN 1 ELSE 0 END) AS completed,
                  SUM(CASE WHEN status = 'escalated' THEN 1 ELSE 0 END) AS escalated,
                  ROUND(AVG(peak_frustration), 3) AS avg_peak_frustration
                FROM interactions WHERE pack_id = ?
                """,
                [pack],
            )
            cols = [d[0] for d in cur.description]
            rows = [dict(zip(cols, r)) for r in cur.fetchall()]
            answer = f"Pack stats for {pack}."

        elif intent == "open_cases":
            cur = con.execute(
                """
                SELECT case_id, severity, priority, category, status, created_at, interaction_id
                FROM cases WHERE status IN ('open', 'pending_followup')
                ORDER BY
                  CASE severity WHEN 'Critical' THEN 0 WHEN 'Medium' THEN 1 ELSE 2 END,
                  created_at DESC
                LIMIT ?
                """,
                [limit],
            )
            cols = [d[0] for d in cur.description]
            rows = [dict(zip(cols, r)) for r in cur.fetchall()]
            answer = f"{len(rows)} open/pending cases."

        elif intent == "critical_cases":
            cur = con.execute(
                """
                SELECT case_id, severity, priority, category, status, created_at, interaction_id
                FROM cases
                WHERE status IN ('open', 'pending_followup')
                  AND (severity = 'Critical' OR priority <= 1)
                ORDER BY created_at DESC
                LIMIT ?
                """,
                [limit],
            )
            cols = [d[0] for d in cur.description]
            rows = [dict(zip(cols, r)) for r in cur.fetchall()]
            answer = f"{len(rows)} open Critical/P1 cases."

        elif intent == "active_contacts":
            cur = con.execute(
                """
                SELECT interaction_id, pack_id, channel, peak_frustration, last_frustration, started_at
                FROM interactions WHERE status = 'active'
                ORDER BY started_at DESC
                LIMIT ?
                """,
                [limit],
            )
            cols = [d[0] for d in cur.description]
            rows = [dict(zip(cols, r)) for r in cur.fetchall()]
            answer = f"{len(rows)} active contacts."

        elif intent == "high_risk":
            # Score-like ranking without full risk module I/O: high peak_fr + active/escalated
            cur = con.execute(
                """
                SELECT interaction_id, status, peak_frustration, last_frustration,
                       category, entity_1, entity_2, entity_3, started_at
                FROM interactions
                WHERE COALESCE(peak_frustration, 0) >= 0.5
                   OR status IN ('active', 'escalated')
                ORDER BY COALESCE(peak_frustration, 0) DESC, started_at DESC
                LIMIT ?
                """,
                [limit],
            )
            cols = [d[0] for d in cur.description]
            rows = [dict(zip(cols, r)) for r in cur.fetchall()]
            answer = f"{len(rows)} high-risk / high-frustration contacts."

        elif intent == "entity_memory":
            e1 = (params.get("entity_1") or "").strip()
            e2 = (params.get("entity_2") or "").strip()
            e3 = (params.get("entity_3") or "").strip()
            clauses = []
            p: list[Any] = []
            if e1:
                clauses.append("(entity_1 ILIKE ? OR entity_2 ILIKE ? OR entity_3 ILIKE ?)")
                like = f"%{e1}%"
                p.extend([like, like, like])
            if e2:
                clauses.append("(entity_1 ILIKE ? OR entity_2 ILIKE ? OR entity_3 ILIKE ?)")
                like = f"%{e2}%"
                p.extend([like, like, like])
            if e3:
                clauses.append("(entity_1 ILIKE ? OR entity_2 ILIKE ? OR entity_3 ILIKE ?)")
                like = f"%{e3}%"
                p.extend([like, like, like])
            where = " AND ".join(clauses) if clauses else "1=0"
            cur = con.execute(
                f"""
                SELECT memory_id, pack_id, entity_1, entity_2, entity_3,
                       last_interaction_id, last_case_id, last_severity, last_category,
                       interaction_count, peak_frustration, last_seen_at, note_summary
                FROM contact_memory
                WHERE {where}
                ORDER BY last_seen_at DESC
                LIMIT ?
                """,
                p + [limit],
            )
            cols = [d[0] for d in cur.description]
            rows = [dict(zip(cols, r)) for r in cur.fetchall()]
            answer = (
                f"{len(rows)} memory row(s) matching "
                f"{' / '.join(x for x in (e1, e2, e3) if x) or 'query'}."
            )

        elif intent == "connector_pending":
            try:
                cur = con.execute(
                    """
                    SELECT delivery_id, event, ref_id, status, sink, attempts, error, created_at
                    FROM connector_deliveries
                    WHERE status = 'pending'
                    ORDER BY created_at DESC
                    LIMIT ?
                    """,
                    [limit],
                )
                cols = [d[0] for d in cur.description]
                rows = [dict(zip(cols, r)) for r in cur.fetchall()]
                answer = f"{len(rows)} pending connector deliveries."
            except Exception:
                rows = []
                answer = "Connector deliveries table unavailable."

        elif intent == "similar_to_case":
            case_id = params.get("case_id") or ""
            raw = params.get("case_raw") or ""
            crow = con.execute(
                """
                SELECT case_id, category, severity, pack_id, cluster_match_id, description_summary
                FROM cases WHERE case_id = ? OR case_id = ?
                LIMIT 1
                """,
                [case_id, raw if raw.startswith("case_") else f"case_{raw}"],
            ).fetchone()
            if not crow:
                answer = f"Case not found for query ({case_id})."
                rows = []
            else:
                cat, sev, pack, cluster = crow[1], crow[2], crow[3], crow[4]
                cur = con.execute(
                    """
                    SELECT case_id, interaction_id, category, severity, status, cluster_match_id, created_at
                    FROM cases
                    WHERE case_id != ?
                      AND pack_id = ?
                      AND (category = ? OR cluster_match_id = ? OR severity = ?)
                    ORDER BY created_at DESC
                    LIMIT ?
                    """,
                    [crow[0], pack, cat, cluster, sev, limit],
                )
                cols = [d[0] for d in cur.description]
                rows = [dict(zip(cols, r)) for r in cur.fetchall()]
                answer = (
                    f"Similar cases to {crow[0]} "
                    f"(category={cat}, severity={sev}, cluster={cluster}): {len(rows)} matches."
                )

    for r in rows:
        for k, v in list(r.items()):
            r[k] = _iso(v)

    return {
        "query": query,
        "intent": intent,
        "answer": answer,
        "rows": rows,
        "row_count": len(rows),
        "suggestions": list(COPILOT_SUGGESTIONS),
        "engine": "deterministic_intent_router",
        "note": "Not a generative LLM; answers are warehouse SQL via intent routing.",
    }
