"""Seed the automotive_nhtsa domain warehouse with a small fixture.

The real pack reuses v1's full NHTSA dataset (25k complaints + recalls) via
canonical views over the existing DuckDB. This fixture builds a self-contained
mini corpus so `make contact` + `make simulate` work out of the box without
requiring the full NHTSA ingest.

Run via:
    make seed-domains         (or)      python -m scripts.seed_domains --force

Rebuilding an existing pilot domain DB under data/domains/ requires --force or
FRONTLINE_ALLOW_DEFAULT_DB_RESET=1 (same intentional path as make frontline-db).

Lives in data/domains/automotive_nhtsa.duckdb
"""

from __future__ import annotations

import argparse
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

# Ensure repo root is on sys.path when invoked as `python -m scripts.seed_domains`
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.config import settings
from src.data.warehouse import domain_con, unlink_domain_db


# ── Fixture data ────────────────────────────────────────────────────────────
# Realistic records clustered around brake grinding on Honda CR-Vs (cluster 14
# in the demo script), plus a couple of unrelated records for variety.

_NOW = datetime.now(timezone.utc)


_RECORDS: list[dict] = [
    # Cluster 14 — brake grinding on Honda CR-Vs (5 records)
    {"record_id": "NHTSA-100001", "entity_1": "2019", "entity_2": "HONDA", "entity_3": "CR-V", "category": "SERVICE BRAKES", "text": "grinding noise when braking at low speed", "severity_label": "Medium", "region": "CA"},
    {"record_id": "NHTSA-100002", "entity_1": "2018", "entity_2": "HONDA", "entity_3": "CR-V", "category": "SERVICE BRAKES", "text": "brakes grind and vibrate when stopping", "severity_label": "Medium", "region": "TX"},
    {"record_id": "NHTSA-100003", "entity_1": "2019", "entity_2": "HONDA", "entity_3": "CR-V", "category": "SERVICE BRAKES", "text": "metal on metal grinding from front brakes", "severity_label": "Medium", "region": "NY"},
    {"record_id": "NHTSA-100004", "entity_1": "2020", "entity_2": "HONDA", "entity_3": "CR-V", "category": "SERVICE BRAKES", "text": "grinding when braking especially in cold weather", "severity_label": "Low", "region": "MN"},
    {"record_id": "NHTSA-100005", "entity_1": "2019", "entity_2": "HONDA", "entity_3": "CR-V", "category": "SERVICE BRAKES", "text": "front brake grinding noise", "severity_label": "Medium", "region": "FL"},
    # Cluster 22 — Toyota Camry airbag warning lights (3 records)
    {"record_id": "NHTSA-200001", "entity_1": "2017", "entity_2": "TOYOTA", "entity_3": "CAMRY", "category": "AIR BAGS", "text": "airbag warning light illuminated on dashboard", "severity_label": "Medium", "region": "WA"},
    {"record_id": "NHTSA-200002", "entity_1": "2018", "entity_2": "TOYOTA", "entity_3": "CAMRY", "category": "AIR BAGS", "text": "SRS airbag warning light stays on", "severity_label": "Medium", "region": "OR"},
    {"record_id": "NHTSA-200003", "entity_1": "2016", "entity_2": "TOYOTA", "entity_3": "CAMRY", "category": "AIR BAGS", "text": "airbag warning indicator persistent", "severity_label": "Low", "region": "CA"},
    # Cluster 31 — Ford F-150 power window failures (2 records)
    {"record_id": "NHTSA-300001", "entity_1": "2020", "entity_2": "FORD", "entity_3": "F-150", "category": "ELECTRICAL SYSTEM", "text": "power window stopped working driver side", "severity_label": "Low", "region": "MI"},
    {"record_id": "NHTSA-300002", "entity_1": "2019", "entity_2": "FORD", "entity_3": "F-150", "category": "ELECTRICAL SYSTEM", "text": "window regulator failure", "severity_label": "Low", "region": "OH"},
]


_ADVISORIES: list[dict] = [
    {
        "advisory_id": "19V-12345",
        "issued_at": _NOW - timedelta(days=200),
        "scope_entity_1": None, "scope_entity_2": "HONDA", "scope_entity_3": "CR-V",
        "scope_category": "SERVICE BRAKES",
        "summary": "Front brake pad wear causing grinding noise",
        "remedy": "Dealer will replace front brake pads and rotors free of charge.",
        "url": "https://www.nhtsa.gov/recalls/19V-12345",
        "source": "NHTSA",
    },
    {
        "advisory_id": "20V-67890",
        "issued_at": _NOW - timedelta(days=400),
        "scope_entity_1": None, "scope_entity_2": "TOYOTA", "scope_entity_3": "CAMRY",
        "scope_category": "AIR BAGS",
        "summary": "Airbag control unit software update",
        "remedy": "Dealer will reprogram airbag control unit.",
        "url": "https://www.nhtsa.gov/recalls/20V-67890",
        "source": "NHTSA",
    },
]


def _build_clusters(pack_id: str) -> list[dict]:
    import json
    return [
        {"cluster_id": 14, "pack_id": pack_id, "top_terms": json.dumps(["grinding", "brakes", "cr-v"]),
         "category": "SERVICE BRAKES", "record_count": 5,
         "first_seen": _NOW - timedelta(days=220), "last_seen": _NOW - timedelta(days=10)},
        {"cluster_id": 22, "pack_id": pack_id, "top_terms": json.dumps(["airbag", "warning", "light"]),
         "category": "AIR BAGS", "record_count": 3,
         "first_seen": _NOW - timedelta(days=420), "last_seen": _NOW - timedelta(days=20)},
        {"cluster_id": 31, "pack_id": pack_id, "top_terms": json.dumps(["window", "electrical", "regulator"]),
         "category": "ELECTRICAL SYSTEM", "record_count": 2,
         "first_seen": _NOW - timedelta(days=120), "last_seen": _NOW - timedelta(days=5)},
    ]


def _build_cluster_assignments() -> list[dict]:
    """Real cosine distances (item 5) — never a constant per row.

    Distance = 1 - cosine(record embedding, cluster centroid), computed with
    the shipped embedding function so fixtures carry honest geometry.
    """
    from src.ml_runtime.embeddings import cosine, embed_text, fit_idf

    try:
        fit_idf([r["text"] for r in _RECORDS])
    except Exception:
        pass
    by_cluster: dict[int, list[str]] = {}
    for r in _RECORDS:
        if r["record_id"].startswith("NHTSA-1000"):
            cluster = 14
        elif r["record_id"].startswith("NHTSA-2000"):
            cluster = 22
        else:
            cluster = 31
        by_cluster.setdefault(cluster, []).append(r["record_id"])
    text_by_id = {r["record_id"]: r["text"] for r in _RECORDS}
    vecs = {rid: embed_text(text_by_id[rid]) for ids in by_cluster.values() for rid in ids}
    out = []
    for cluster, ids in by_cluster.items():
        dim = len(vecs[ids[0]])
        centroid = [0.0] * dim
        for rid in ids:
            for d, v in enumerate(vecs[rid]):
                centroid[d] += v
        n = float(len(ids))
        centroid = [x / n for x in centroid]
        import math as _math

        norm = _math.sqrt(sum(x * x for x in centroid)) or 1.0
        centroid = [x / norm for x in centroid]
        for rid in ids:
            try:
                dist = max(0.0, min(2.0, 1.0 - cosine(vecs[rid], centroid)))
            except ValueError:
                dist = 1.0
            out.append({"record_id": rid, "cluster_id": cluster, "distance": dist})
    try:
        from src.ml_runtime.embeddings import reset_idf

        reset_idf()
    except Exception:
        pass
    return out


def _build_weekly_anomalies(pack_id: str) -> list[dict]:
    """Two weeks of weekly counts: last week normal, the week before that a spike."""
    iso_now = _NOW.strftime("%G-W%V")
    iso_prev = (_NOW - timedelta(weeks=1)).strftime("%G-W%V")
    iso_two_ago = (_NOW - timedelta(weeks=2)).strftime("%G-W%V")
    return [
        {"pack_id": pack_id, "iso_week": iso_now, "category": "SERVICE BRAKES", "entity_2": "HONDA",
         "record_count": 4, "baseline_mean": 1.0, "baseline_std": 0.5, "z_score": 6.0, "is_anomaly": True},
        {"pack_id": pack_id, "iso_week": iso_prev, "category": "SERVICE BRAKES", "entity_2": "HONDA",
         "record_count": 2, "baseline_mean": 1.0, "baseline_std": 0.5, "z_score": 2.0, "is_anomaly": False},
        {"pack_id": pack_id, "iso_week": iso_two_ago, "category": "SERVICE BRAKES", "entity_2": "HONDA",
         "record_count": 1, "baseline_mean": 1.0, "baseline_std": 0.5, "z_score": 0.0, "is_anomaly": False},
    ]


def _build_backtest_results() -> list[dict]:
    return [
        {"cluster_id": 14, "advisory_id": "19V-12345", "lead_time_weeks": 11, "matched": True},
        {"cluster_id": 22, "advisory_id": "20V-67890", "lead_time_weeks": 8, "matched": True},
    ]


def build(pack_id: str = "automotive_nhtsa", *, force: bool = False) -> Path:
    """Build (or rebuild) the pack's domain warehouse from the fixture.

    Existing pilot domain DBs under ``data/domains/`` are not deleted unless
    ``force=True`` or an allow-reset env flag is set.
    """
    path = settings.domain_db_path(pack_id)
    unlink_domain_db(path, force=force)

    with domain_con(pack_id, read_only=False) as con:
        # Records
        for r in _RECORDS:
            con.execute(
                """
                INSERT INTO records
                (record_id, occurred_at, received_at, entity_1, entity_2, entity_3,
                 category, subcategory, text, severity_label, region, source,
                 entity_key, provenance)
                VALUES (?, ?, ?, ?, ?, ?, ?, NULL, ?, ?, ?, 'NHTSA', ?, 'fixture')
                """,
                [
                    r["record_id"],
                    _NOW - timedelta(days=30),
                    _NOW - timedelta(days=10),
                    r["entity_1"], r["entity_2"], r["entity_3"],
                    r["category"], r["text"], r["severity_label"], r["region"],
                    "|".join([
                        str(r["entity_1"]).upper(), str(r["entity_2"]).upper(),
                        str(r["entity_3"]).upper(),
                    ]),
                ],
            )

        # Advisories
        for a in _ADVISORIES:
            con.execute(
                """
                INSERT INTO advisories
                (advisory_id, issued_at, scope_entity_1, scope_entity_2, scope_entity_3,
                 scope_category, summary, remedy, url, source)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                [
                    a["advisory_id"], a["issued_at"],
                    a["scope_entity_1"], a["scope_entity_2"], a["scope_entity_3"],
                    a["scope_category"], a["summary"], a["remedy"], a["url"], a["source"],
                ],
            )

        # Clusters + assignments
        for c in _build_clusters(pack_id):
            con.execute(
                """
                INSERT INTO clusters
                (cluster_id, pack_id, top_terms, category, record_count, first_seen, last_seen)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                [c["cluster_id"], c["pack_id"], c["top_terms"], c["category"],
                 c["record_count"], c["first_seen"], c["last_seen"]],
            )
        for a in _build_cluster_assignments():
            con.execute(
                """
                INSERT INTO cluster_assignments
                (record_id, cluster_id, distance) VALUES (?, ?, ?)
                """,
                [a["record_id"], a["cluster_id"], a["distance"]],
            )

        # Weekly anomalies
        for w in _build_weekly_anomalies(pack_id):
            con.execute(
                """
                INSERT INTO weekly_anomalies
                (pack_id, iso_week, category, entity_2, record_count,
                 baseline_mean, baseline_std, z_score, is_anomaly)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                [w["pack_id"], w["iso_week"], w["category"], w["entity_2"],
                 w["record_count"], w["baseline_mean"], w["baseline_std"],
                 w["z_score"], w["is_anomaly"]],
            )

        # Backtest results
        for b in _build_backtest_results():
            con.execute(
                """
                INSERT INTO backtest_results
                (cluster_id, advisory_id, lead_time_weeks, matched,
                 pack_id, provenance, match_basis)
                VALUES (?, ?, ?, ?, ?, 'fixture', 'seed-fixture')
                """,
                [b["cluster_id"], b["advisory_id"], b["lead_time_weeks"], b["matched"], pack_id],
            )

    # Seeds write current-schema warehouses directly: stamp migrations so
    # ingest gates (audit 0.5) see this DB at HEAD, not "behind".
    try:
        from scripts.migrate import stamp_schema_current

        stamp_schema_current(path, target="domain")
    except Exception:
        pass
    return path


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Seed automotive_nhtsa domain fixture")
    parser.add_argument(
        "--force",
        action="store_true",
        help="Allow deleting an existing pilot domain DB under data/domains/",
    )
    parser.add_argument("--pack", default="automotive_nhtsa", help="Pack id (default automotive_nhtsa)")
    args = parser.parse_args(argv)
    try:
        p = build(args.pack, force=args.force)
    except RuntimeError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    print(f"Built {p}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
