"""Scale domain warehouse: expand fixture rows to N synthetic records + embeddings.

CI still uses the 10-row fixture path (`seed_domains`). This script builds a
larger corpus for demos: ``python -m scripts.ingest_scale --pack automotive_nhtsa --n 10000``.

Does not download external NHTSA/CFPB dumps (network optional); synthesizes from
fixture templates so offline CI and demos both work.
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.config import settings
from src.data.timeutil import utc_now
from src.data.warehouse import apply_domain_schema, domain_con
from src.ml_runtime.embeddings import embed_text
from scripts.seed_domains import (
    _ADVISORIES,
    _RECORDS,
    _build_cluster_assignments,
    _build_clusters,
    _build_weekly_anomalies,
)
from scripts import seed_domains


def _synth_records(base: list[dict], n: int) -> list[dict]:
    out: list[dict] = []
    now = utc_now()
    for i in range(n):
        tmpl = base[i % len(base)]
        rec = dict(tmpl)
        rec["record_id"] = f"{tmpl['record_id']}-S{i:05d}"
        # Spread over ~2 years
        rec["_offset_days"] = (i * 3) % 700
        rec["_received"] = now - timedelta(days=rec["_offset_days"])
        # Light text variation for embeddings
        rec["text"] = f"{tmpl['text']} (case variant {i % 17})"
        out.append(rec)
    return out


def build_scaled(pack_id: str, n: int, *, force: bool = False) -> Path:
    from src.data.warehouse import unlink_domain_db

    path = settings.domain_db_path(pack_id)
    path.parent.mkdir(parents=True, exist_ok=True)
    unlink_domain_db(path, force=force)

    # Reuse automotive fixture templates for any pack id (structure only)
    base = list(_RECORDS)
    if pack_id == "finance_cfpb":
        try:
            from scripts.seed_finance_cfpb import _RECORDS as fin_recs  # type: ignore
            base = list(fin_recs)
        except Exception:
            pass

    records = _synth_records(base, n)
    with domain_con(pack_id, read_only=False) as con:
        apply_domain_schema(con)
        # embedding column for older DBs
        try:
            con.execute("ALTER TABLE records ADD COLUMN embedding FLOAT[]")
        except Exception:
            pass

        for r in records:
            emb = embed_text(r["text"])
            con.execute(
                """
                INSERT INTO records (
                    record_id, occurred_at, received_at, entity_1, entity_2, entity_3,
                    category, subcategory, text, severity_label, region, source, embedding
                ) VALUES (?, ?, ?, ?, ?, ?, ?, NULL, ?, ?, ?, ?, ?)
                """,
                [
                    r["record_id"],
                    r["_received"],
                    r["_received"],
                    r.get("entity_1"),
                    r.get("entity_2"),
                    r.get("entity_3"),
                    r.get("category"),
                    r["text"],
                    r.get("severity_label"),
                    r.get("region"),
                    "synthetic_scale",
                    emb,
                ],
            )

        for a in _ADVISORIES:
            con.execute(
                """
                INSERT INTO advisories (
                    advisory_id, issued_at, scope_entity_1, scope_entity_2, scope_entity_3,
                    scope_category, summary, remedy, url, source
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                [
                    a["advisory_id"],
                    a["issued_at"].replace(tzinfo=None) if hasattr(a["issued_at"], "replace") else a["issued_at"],
                    a.get("scope_entity_1"),
                    a.get("scope_entity_2"),
                    a.get("scope_entity_3"),
                    a.get("scope_category"),
                    a["summary"],
                    a.get("remedy"),
                    a.get("url"),
                    a.get("source"),
                ],
            )

        for c in _build_clusters(pack_id):
            con.execute(
                """
                INSERT INTO clusters (
                    cluster_id, pack_id, top_terms, category, record_count, first_seen, last_seen
                ) VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                [
                    c["cluster_id"],
                    c["pack_id"],
                    c["top_terms"],
                    c["category"],
                    c["record_count"],
                    c["first_seen"].replace(tzinfo=None) if hasattr(c["first_seen"], "tzinfo") else c["first_seen"],
                    c["last_seen"].replace(tzinfo=None) if hasattr(c["last_seen"], "tzinfo") else c["last_seen"],
                ],
            )
        # assignments for base only (scale records unassigned — semantic search still works)
        for a in _build_cluster_assignments():
            con.execute(
                "INSERT INTO cluster_assignments (record_id, cluster_id, distance) VALUES (?, ?, ?)",
                [a["record_id"], a["cluster_id"], a["distance"]],
            )
        for w in _build_weekly_anomalies(pack_id):
            con.execute(
                """
                INSERT INTO weekly_anomalies (
                    pack_id, iso_week, category, entity_2, record_count,
                    baseline_mean, baseline_std, z_score, is_anomaly
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                [
                    w["pack_id"],
                    w["iso_week"],
                    w.get("category"),
                    w.get("entity_2"),
                    w["record_count"],
                    w.get("baseline_mean"),
                    w.get("baseline_std"),
                    w.get("z_score"),
                    w.get("is_anomaly"),
                ],
            )

    # Real backtest after scale load
    from src.backtest.engine import run_backtest

    run_backtest(pack_id)
    return path


def main() -> int:
    ap = argparse.ArgumentParser(description="Scale domain DuckDB corpus")
    ap.add_argument("--pack", default="automotive_nhtsa")
    ap.add_argument("--n", type=int, default=10000, help="target record count")
    ap.add_argument(
        "--force",
        action="store_true",
        help="Allow deleting an existing pilot domain DB under data/domains/",
    )
    args = ap.parse_args()
    n = max(10, min(int(args.n), 100_000))
    try:
        path = build_scaled(args.pack, n, force=args.force)
    except RuntimeError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    print(f"✓ scaled {args.pack}: {n} records → {path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
