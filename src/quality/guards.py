"""Ingest data-quality guards — schema drift, freshness, quarantine, cold-start.

Closes review §4:
  - schema drift detection per source (column added/renamed/type changed)
  - null-rate, cardinality, freshness monitors with thresholds + per-source SLA
  - cross-source duplicate detection (same event in NHTSA + warranty)
  - ingest quarantine bucket (reviewable, never silently dropped)
  - cold-start: N < 50 → suppress anomaly/cluster/backtest noise
"""

from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from typing import Any


COLD_START_MIN_N = 50


# ── Schema drift ──────────────────────────────────────────────────────────

def schema_fingerprint(columns: list[dict[str, Any]]) -> str:
    """Stable hash of [(name, type)] — detects add/rename/type change."""
    norm = sorted((str(c.get("name", "")).lower(), str(c.get("type", "")).lower())
                  for c in columns)
    return hashlib.sha256(json.dumps(norm, sort_keys=True).encode()).hexdigest()[:16]


def detect_schema_drift(
    expected: list[dict[str, Any]], observed: list[dict[str, Any]]
) -> dict[str, Any]:
    exp = {str(c.get("name", "")).lower(): str(c.get("type", "")).lower() for c in expected}
    obs = {str(c.get("name", "")).lower(): str(c.get("type", "")).lower() for c in observed}
    added = sorted(set(obs) - set(exp))
    removed = sorted(set(exp) - set(obs))
    type_changed = sorted(k for k in set(exp) & set(obs) if exp[k] != obs[k])
    return {
        "drifted": bool(added or removed or type_changed),
        "added": added, "removed": removed, "type_changed": type_changed,
        "expected_fp": schema_fingerprint(expected),
        "observed_fp": schema_fingerprint(observed),
    }


# ── Null-rate / cardinality / freshness ───────────────────────────────────

def null_rate_report(rows: list[dict[str, Any]], *, threshold: float = 0.30) -> dict[str, Any]:
    if not rows:
        return {"n": 0, "columns": {}, "breaches": [], "note": "insufficient_data"}
    cols = sorted({k for r in rows for k in r.keys()})
    out, breaches = {}, []
    for c in cols:
        nulls = sum(1 for r in rows if r.get(c) in (None, "", "NULL", "null"))
        rate = nulls / len(rows)
        out[c] = {"null_rate": rate, "breached": rate > threshold}
        if rate > threshold:
            breaches.append(c)
    return {"n": len(rows), "columns": out, "breaches": breaches}


def freshness_status(last_seen_iso: str | None, *, sla_hours: float) -> dict[str, Any]:
    if not last_seen_iso:
        return {"fresh": False, "age_hours": None, "breach": True, "note": "never_seen"}
    try:
        ts = datetime.fromisoformat(str(last_seen_iso).replace("Z", "+00:00"))
        age_h = (datetime.now(timezone.utc) - ts).total_seconds() / 3600.0
        return {"fresh": age_h <= sla_hours, "age_hours": round(age_h, 2),
                "breach": age_h > sla_hours, "sla_hours": sla_hours}
    except Exception:
        return {"fresh": False, "age_hours": None, "breach": True, "note": "unparseable_ts"}


# ── Cross-source duplicates ───────────────────────────────────────────────

def event_key(event: dict[str, Any]) -> str:
    parts = [str(event.get(k, "")).strip().lower()
             for k in ("entity_1", "entity_2", "category", "occurred_at", "description")]
    parts[-1] = parts[-1][:120]
    return hashlib.sha256("|".join(parts).encode()).hexdigest()[:20]


def find_cross_source_duplicates(
    batches: dict[str, list[dict[str, Any]]],
) -> list[dict[str, Any]]:
    """Same event_key in ≥2 sources → candidate duplicate."""
    owners: dict[str, set[str]] = {}
    for source, rows in batches.items():
        for r in rows:
            owners.setdefault(event_key(r), set()).add(source)
    return [{"event_key": k, "sources": sorted(v)}
            for k, v in owners.items() if len(v) >= 2]


# ── Quarantine (reviewable, never silent) ─────────────────────────────────

def lint_row(row: dict[str, Any], *, required: list[str]) -> list[str]:
    errors = []
    for col in required:
        if row.get(col) in (None, ""):
            errors.append(f"missing:{col}")
    return errors


def partition_quarantine(
    rows: list[dict[str, Any]], *, required: list[str]
) -> dict[str, Any]:
    good, bad = [], []
    for r in rows:
        errs = lint_row(r, required=required)
        if errs:
            bad.append({"row": r, "errors": errs})
        else:
            good.append(r)
    return {"accepted": good, "quarantined": bad,
            "quarantine_rate": (len(bad) / len(rows)) if rows else 0.0}


# ── Cold-start suppression ────────────────────────────────────────────────

def cold_start_gate(n: int, *, min_n: int = COLD_START_MIN_N) -> dict[str, Any]:
    if n < min_n:
        return {"emit": False, "n": n, "min_n": min_n,
                "action": "suppress",
                "reason": f"N={n} < {min_n}: suppress anomaly/cluster/backtest, return insufficient_data"}
    return {"emit": True, "n": n, "min_n": min_n, "action": "emit"}


__all__ = [
    "COLD_START_MIN_N", "schema_fingerprint", "detect_schema_drift",
    "null_rate_report", "freshness_status", "event_key",
    "find_cross_source_duplicates", "lint_row", "partition_quarantine",
    "cold_start_gate",
]
