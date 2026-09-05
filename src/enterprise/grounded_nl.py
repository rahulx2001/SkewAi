"""Grounded NL query: plan a lookup, Qubot-verify every cited row before show."""

from __future__ import annotations

import re
from typing import Any

from src.data.warehouse import domain_con, ops_con
from src.qubot.claims import BoundClaim, audit_bound_claims, cited_text_from_snapshot
from src.qubot.evidence_pin import fetch_record_row


def plan_query(question: str) -> dict[str, Any]:
    """Deterministic planner (LLM optional later). Extracts category/entity tokens.

    Uses pack gazetteers when available; falls back to heuristics. Never
    hardcodes a single category like 'brake'.
    """
    q = (question or "").strip()
    ql = q.lower()
    intent = "similar_records"
    if "how many" in ql or "count" in ql:
        intent = "count"
    tokens = re.findall(r"[A-Za-z0-9][A-Za-z0-9_-]{2,40}", q)
    stop = {
        "show", "the", "and", "for", "with", "about", "records", "cases",
        "how", "many", "count", "similar", "complaints", "on", "in",
        "what", "which", "there", "have", "has", "are", "were", "been",
    }
    kept = [t for t in tokens if t.lower() not in stop]
    # Try gazetteer-aware linking across shipped packs (best effort)
    category = None
    entity_2 = None
    try:
        from src.domains.loader import list_packs, load_pack

        for pid in list_packs():
            try:
                pack = load_pack(pid)
            except Exception:
                continue
            for _slot, gaz in (pack.gazetteers or {}).items():
                try:
                    hit = gaz.match_substring(q)
                except Exception:
                    hit = None
                if hit:
                    lname = (gaz.name or "").lower()
                    if "categor" in lname and category is None:
                        category = hit
                    elif ("entity_2" in lname or "make" in lname or "compan" in lname) and entity_2 is None:
                        entity_2 = hit
            if category and entity_2:
                break
    except Exception:
        pass
    if category is None:
        # Uppercase multi-word spans are likely categories (e.g. SERVICE BRAKES)
        m = re.search(r"\b([A-Z][A-Z ]{3,40})\b", q)
        if m:
            category = m.group(1).strip()
        else:
            category = next((t for t in kept if t.isupper() and len(t) >= 3), None)
    if entity_2 is None:
        entity_2 = next((t for t in kept if t[:1].isupper() and t.lower() not in {"show"} and t != category), None)
    return {
        "intent": intent,
        "question": q,
        "tokens": kept[:6],
        "category": category,
        "entity_2": entity_2,
    }


def _like_escape(token: str) -> str:
    """Escape LIKE wildcards so user tokens match literally (item 30).

    ``%`` and ``_`` are escaped with backslash (queries use ``ESCAPE '\\'``);
    stripping them (the old behavior) silently widened the match.
    """
    return (
        token.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
    )


def _search_domain(pack_id: str, plan: dict[str, Any], *, limit: int = 5) -> list[dict[str, Any]]:
    tokens = [t for t in (plan.get("tokens") or []) if len(t) >= 3][:3]
    if not tokens:
        # No query terms -> no grounding. Never conjure a hardcoded category
        # (the old `or ["brake"]` fallback returned brake rows for any
        # unparseable question).
        return []
    try:
        with domain_con(pack_id) as con:
            # AND all tokens (all must appear) — single-token OR matched everything.
            conds: list[str] = []
            params: list[Any] = []
            for tok in tokens:
                esc = _like_escape(tok)
                if not esc:
                    continue
                conds.append(
                    "(r.text ILIKE '%' || ? || '%' ESCAPE '\\' "
                    "OR r.category ILIKE '%' || ? || '%' ESCAPE '\\')"
                )
                params.extend([esc, esc])
            if not conds:
                return []
            where = " AND ".join(conds)
            rows = con.execute(
                f"""
                SELECT record_id, text, category, entity_2, source, received_at
                FROM records r
                WHERE {where}
                LIMIT ?
                """,
                [*params, limit],
            ).fetchall()
            cols = [d[0] for d in con.description]
            return [dict(zip(cols, r)) for r in rows]
    except FileNotFoundError:
        return []


def _best_snippet_token(text: str, tokens: list[str]) -> str:
    """Pick the grounding token with real support (item 30).

    Never ``tokens[0]`` blindly: returns the LONGEST plan token (len>=4)
    actually present in the row text. Empty when nothing overlaps — the
    caller then falls back to a sentence span, which still must audit clean.
    """
    lowered = (text or "").lower()
    cands = sorted(
        {t for t in (tokens or []) if len(t or "") >= 4},
        key=len,
        reverse=True,
    )
    for tok in cands:
        if tok.lower() in lowered:
            return tok
    return ""


def _claim_for_row(row: dict[str, Any], snippet: str) -> BoundClaim | None:
    text = str(row.get("text") or "")
    rid = str(row.get("record_id") or "")
    if not text or not rid:
        return None
    # Require a substantive snippet (>=8 chars) to avoid vacuous "My" claims.
    # Minimum overlap: at least two distinct content words (len>=3) from the
    # snippet must occur in the text — a lone short word is not grounding.
    cand = (snippet or "").strip()
    content_words = {w.lower() for w in re.findall(r"[a-z0-9]{3,}", cand.lower())}
    text_lower = text.lower()
    overlap = sum(1 for w in content_words if w in text_lower)
    if len(cand) < 8 or cand.lower() not in text_lower or overlap < 2:
        # Fall back to first sentence-ish span (>=40 chars, sentence boundary)
        import re as _re

        m = _re.search(r".{40,120}?[.!?]|.{40,120}$", text, flags=_re.S)
        needle = (m.group(0).strip() if m else text[: min(80, len(text))].strip())
        if len(needle) < 8:
            return None
    else:
        needle = cand
    idx = text.lower().find(needle.lower())
    if idx < 0:
        return None
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
            claim = _claim_for_row(
                live or row,
                _best_snippet_token(
                    str((live or row).get("text") or ""),
                    [str(t) for t in (plan.get("tokens") or [])],
                ),
            )
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
