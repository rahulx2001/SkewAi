"""Seed the finance_cfpb domain warehouse with a small fixture.

The real pack is built by the Pack Builder from the public CFPB consumer-complaint
CSV (millions of rows). This fixture builds a self-contained mini corpus so
`make contact` + `make simulate` work out of the box on the finance pack without
requiring the full CFPB ingest.

Run via:
    python -m scripts.seed_finance_cfpb --force

Rebuilding an existing pilot domain DB under data/domains/ requires --force or
FRONTLINE_ALLOW_DEFAULT_DB_RESET=1 (same intentional path as make frontline-db).

Lives in data/domains/finance_cfpb.duckdb
"""

from __future__ import annotations

import argparse
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

# Ensure repo root is on sys.path when invoked as `python -m scripts.seed_finance_cfpb`
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.config import settings
from src.data.warehouse import domain_con, unlink_domain_db


_NOW = datetime.now(timezone.utc)


# ── Fixture data ────────────────────────────────────────────────────────────
# Realistic records clustered around Chase double-charge issues (cluster 41),
# plus a couple of unrelated records for variety.

_RECORDS: list[dict] = [
    # Cluster 41 — Chase checking double-charge (5 records)
    {"record_id": "CFPB-400001", "entity_1": "Checking or savings account", "entity_2": "Checking account", "entity_3": "JPMORGAN CHASE & CO.", "category": "Incorrect charges", "text": "Chase charged me twice for the same transaction on my checking account", "severity_label": "Medium", "region": "CA"},
    {"record_id": "CFPB-400002", "entity_1": "Checking or savings account", "entity_2": "Checking account", "entity_3": "JPMORGAN CHASE & CO.", "category": "Incorrect charges", "text": "duplicate charge on my Chase debit card", "severity_label": "Medium", "region": "TX"},
    {"record_id": "CFPB-400003", "entity_1": "Checking or savings account", "entity_2": "Checking account", "entity_3": "JPMORGAN CHASE & CO.", "category": "Incorrect charges", "text": "charged twice for the same purchase with Chase", "severity_label": "Medium", "region": "NY"},
    {"record_id": "CFPB-400004", "entity_1": "Checking or savings account", "entity_2": "Checking account", "entity_3": "JPMORGAN CHASE & CO.", "category": "Incorrect charges", "text": "Chase double charged me and won't refund the overdraft fee", "severity_label": "Medium", "region": "FL"},
    {"record_id": "CFPB-400005", "entity_1": "Checking or savings account", "entity_2": "Checking account", "entity_3": "JPMORGAN CHASE & CO.", "category": "Incorrect charges", "text": "duplicate debit transaction posted twice to my checking account", "severity_label": "Low", "region": "WA"},
    # Cluster 52 — Bank of America unauthorized transactions (3 records)
    {"record_id": "CFPB-500001", "entity_1": "Credit card", "entity_2": "Credit card", "entity_3": "BANK OF AMERICA", "category": "Unauthorized transactions", "text": "unauthorized transaction on my Bank of America credit card", "severity_label": "Critical", "region": "IL"},
    {"record_id": "CFPB-500002", "entity_1": "Credit card", "entity_2": "Credit card", "entity_3": "BANK OF AMERICA", "category": "Unauthorized transactions", "text": "fraudulent charge on my BofA credit card that I didn't make", "severity_label": "Critical", "region": "GA"},
    {"record_id": "CFPB-500003", "entity_1": "Credit card", "entity_2": "Credit card", "entity_3": "BANK OF AMERICA", "category": "Unauthorized transactions", "text": "someone used my credit card without authorization at Bank of America", "severity_label": "Critical", "region": "MA"},
    # Cluster 63 — Wells Fargo mortgage escrow (2 records)
    {"record_id": "CFPB-600001", "entity_1": "Mortgage", "entity_2": "Conventional home mortgage", "entity_3": "WELLS FARGO", "category": "Managing an account", "text": "Wells Fargo misapplied my mortgage escrow payment", "severity_label": "Medium", "region": "OH"},
    {"record_id": "CFPB-600002", "entity_1": "Mortgage", "entity_2": "Conventional home mortgage", "entity_3": "WELLS FARGO", "category": "Managing an account", "text": "escrow analysis incorrect on my Wells Fargo mortgage", "severity_label": "Low", "region": "PA"},
]


_ADVISORIES: list[dict] = [
    {
        "advisory_id": "CFPB-2023-01",
        "issued_at": _NOW - timedelta(days=120),
        "scope_entity_1": "Checking or savings account", "scope_entity_2": None, "scope_entity_3": "JPMORGAN CHASE & CO.",
        "scope_category": "Incorrect charges",
        "summary": "CFPB consent order: Chase refund for duplicate debit charges",
        "remedy": "Chase must refund affected customers for duplicate charges and related overdraft fees.",
        "url": "https://www.consumerfinance.gov/actions/jpmorgan-chase-bank-na-2023-01/",
        "source": "CFPB",
    },
    {
        "advisory_id": "CFPB-2022-07",
        "issued_at": _NOW - timedelta(days=300),
        "scope_entity_1": "Credit card", "scope_entity_2": None, "scope_entity_3": "BANK OF AMERICA",
        "scope_category": "Unauthorized transactions",
        "summary": "CFPB enforcement: Bank of America credit card fraud response",
        "remedy": "Bank of America must improve unauthorized transaction dispute resolution timelines.",
        "url": "https://www.consumerfinance.gov/actions/bank-of-america-na-2022-07/",
        "source": "CFPB",
    },
]


def _build_clusters(pack_id: str) -> list[dict]:
    import json
    return [
        {"cluster_id": 41, "pack_id": pack_id, "top_terms": json.dumps(["double", "charged", "chase"]),
         "category": "Incorrect charges", "record_count": 5,
         "first_seen": _NOW - timedelta(days=140), "last_seen": _NOW - timedelta(days=5)},
        {"cluster_id": 52, "pack_id": pack_id, "top_terms": json.dumps(["unauthorized", "fraud", "credit card"]),
         "category": "Unauthorized transactions", "record_count": 3,
         "first_seen": _NOW - timedelta(days=320), "last_seen": _NOW - timedelta(days=15)},
        {"cluster_id": 63, "pack_id": pack_id, "top_terms": json.dumps(["escrow", "mortgage", "wells fargo"]),
         "category": "Managing an account", "record_count": 2,
         "first_seen": _NOW - timedelta(days=180), "last_seen": _NOW - timedelta(days=10)},
    ]


def _build_cluster_assignments() -> list[dict]:
    """Real cosine distances (item 5) — never a constant per row."""
    from src.ml_runtime.embeddings import cosine, embed_text, fit_idf

    try:
        fit_idf([r["text"] for r in _RECORDS])
    except Exception:
        pass

    def _cluster_for(rid: str) -> int:
        if rid.startswith("CFPB-4000"):
            return 41
        if rid.startswith("CFPB-5000"):
            return 52
        return 63

    by_cluster: dict[int, list[str]] = {}
    for r in _RECORDS:
        by_cluster.setdefault(_cluster_for(r["record_id"]), []).append(r["record_id"])
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
        {"pack_id": pack_id, "iso_week": iso_now, "category": "Incorrect charges", "entity_2": "JPMORGAN CHASE & CO.",
         "record_count": 4, "baseline_mean": 1.0, "baseline_std": 0.5, "z_score": 6.0, "is_anomaly": True},
        {"pack_id": pack_id, "iso_week": iso_prev, "category": "Incorrect charges", "entity_2": "JPMORGAN CHASE & CO.",
         "record_count": 2, "baseline_mean": 1.0, "baseline_std": 0.5, "z_score": 2.0, "is_anomaly": False},
        {"pack_id": pack_id, "iso_week": iso_two_ago, "category": "Incorrect charges", "entity_2": "JPMORGAN CHASE & CO.",
         "record_count": 1, "baseline_mean": 1.0, "baseline_std": 0.5, "z_score": 0.0, "is_anomaly": False},
    ]


def _build_backtest_results() -> list[dict]:
    return [
        {"cluster_id": 41, "advisory_id": "CFPB-2023-01", "lead_time_weeks": 9, "matched": True},
        {"cluster_id": 52, "advisory_id": "CFPB-2022-07", "lead_time_weeks": 14, "matched": True},
    ]


def build(pack_id: str = "finance_cfpb", *, force: bool = False) -> Path:
    """Build (or rebuild) the pack's domain warehouse from the fixture.

    Existing pilot domain DBs under ``data/domains/`` are not deleted unless
    ``force=True`` or an allow-reset env flag is set.
    """
    path = settings.domain_db_path(pack_id)
    unlink_domain_db(path, force=force)

    with domain_con(pack_id, read_only=False) as con:
        for r in _RECORDS:
            con.execute(
                """
                INSERT INTO records
                (record_id, occurred_at, received_at, entity_1, entity_2, entity_3,
                 category, subcategory, text, severity_label, region, source,
                 entity_key, provenance)
                VALUES (?, ?, ?, ?, ?, ?, ?, NULL, ?, ?, ?, 'CFPB', ?, 'fixture')
                """,
                [
                    r["record_id"],
                    _NOW - timedelta(days=20),
                    _NOW - timedelta(days=5),
                    r["entity_1"], r["entity_2"], r["entity_3"],
                    r["category"], r["text"], r["severity_label"], r["region"],
                    "|".join([
                        str(r["entity_3"]).upper(), str(r["entity_1"]).upper(),
                        str(r["category"]).upper(),
                    ]),
                ],
            )

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
    parser = argparse.ArgumentParser(description="Seed finance_cfpb domain fixture")
    parser.add_argument(
        "--force",
        action="store_true",
        help="Allow deleting an existing pilot domain DB under data/domains/",
    )
    parser.add_argument("--pack", default="finance_cfpb", help="Pack id (default finance_cfpb)")
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
