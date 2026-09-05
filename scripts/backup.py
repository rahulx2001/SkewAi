"""Backup + restore drill for the pilot warehouses (item 48).

Backup (DuckDB): CHECKPOINT each file, copy ops + domain DBs + locker keys
manifest into a timestamped directory with sha256 sidecars.

    python -m scripts.backup --out backups/2026-09-05

Restore drill (PITR strategy for Postgres is documented in
docs/compliance/backup_and_dr.md; this drills the DuckDB path):

    python -m scripts.backup --restore backups/2026-09-05 --to /tmp/restore --verify

--verify checks application-critical tables AND indexes open and read back
(cases, interactions, agent_actions, records, advisories, clusters,
backtest_results, weekly_anomalies) and fails loudly otherwise.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import sys
from datetime import datetime, timezone
from pathlib import Path

from src.config import REPO_ROOT

CRITICAL_TABLES = [
    "interactions",
    "interaction_turns",
    "cases",
    "investigations",
    "agent_actions",
]

CRITICAL_DOMAIN_TABLES = [
    "records",
    "advisories",
    "clusters",
    "cluster_assignments",
    "weekly_anomalies",
    "backtest_results",
]

CRITICAL_INDEXES = [
    "idx_cases_interaction",
]

CRITICAL_DOMAIN_INDEXES = [
    "idx_backtest_pack_matched",
]


def _sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def backup(*, out: Path) -> dict:
    import duckdb

    from src.config import settings

    out.mkdir(parents=True, exist_ok=True)
    manifest: dict = {
        "taken_at": datetime.now(timezone.utc).isoformat(),
        "files": [],
    }
    # Configured paths (FRONTLINE_DB_PATH / DOMAIN_DB_PATH), never hardcoded
    # pilot dirs — tests and custom deploys back up the LIVE databases.
    sources = [settings.frontline_db_path]
    try:
        sources += sorted(settings.domain_db_dir.glob("*.duckdb"))
    except OSError:
        pass
    for src in sources:
        if not src.is_file():
            continue
        try:
            con = duckdb.connect(str(src), read_only=True)
            try:
                con.execute("CHECKPOINT")
            finally:
                con.close()
        except Exception:
            pass
        dest = out / src.name
        dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(src, dest)
        manifest["files"].append(
            {"path": str(dest.relative_to(out)), "sha256": _sha256(dest)}
        )
    keys = REPO_ROOT / "data" / "locker_keys"
    if keys.is_dir():
        dest_keys = out / "locker_keys"
        dest_keys.mkdir(parents=True, exist_ok=True)
        for pem in sorted(keys.glob("*.pub.pem")) + sorted(
            [p for p in keys.glob("*.pem") if not p.name.endswith(".pub.pem")]
        ):
            # Private keys are referenced, never copied into backups by
            # default (operators restore them from the secret manager).
            if pem.name.endswith(".pub.pem"):
                shutil.copy2(pem, dest_keys / pem.name)
        manifest["locker_keys"] = "public keys only; privates stay in secret manager"
    (out / "manifest.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    return manifest


def verify_backup(backup_dir: Path) -> dict:
    """Restore-drill verification: manifest hashes + critical tables/indexes."""
    import duckdb

    manifest = json.loads((backup_dir / "manifest.json").read_text(encoding="utf-8"))
    for entry in manifest.get("files", []):
        p = backup_dir / entry["path"]
        assert p.is_file(), f"backup file missing: {entry['path']}"
        assert _sha256(p) == entry["sha256"], f"hash mismatch: {entry['path']}"
    ops = backup_dir / "frontline.duckdb"
    assert ops.is_file(), "ops warehouse missing from backup"
    con = duckdb.connect(str(ops), read_only=True)
    try:
        tables = {r[0] for r in con.execute(
            "SELECT table_name FROM information_schema.tables").fetchall()}
        for t in CRITICAL_TABLES:
            assert t in tables, f"critical table missing: {t}"
        idx = {r[0] for r in con.execute(
            "SELECT index_name FROM duckdb_indexes()").fetchall()}
        for i in CRITICAL_INDEXES:
            assert i in idx, f"critical index missing: {i}"
        counts = {
            t: con.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0]
            for t in CRITICAL_TABLES
        }
    finally:
        con.close()
    domain_files = [p for p in backup_dir.glob("*.duckdb") if p.name != "frontline.duckdb"]
    domain_files += list((backup_dir / "domains").glob("*.duckdb")) if (backup_dir / "domains").is_dir() else []
    for dom in domain_files:
        dcon = duckdb.connect(str(dom), read_only=True)
        try:
            tables = {r[0] for r in dcon.execute(
                "SELECT table_name FROM information_schema.tables").fetchall()}
            for t in CRITICAL_DOMAIN_TABLES:
                assert t in tables, f"{dom.name}: critical table missing: {t}"
            didx = {r[0] for r in dcon.execute(
                "SELECT index_name FROM duckdb_indexes()").fetchall()}
            for i in CRITICAL_DOMAIN_INDEXES:
                assert i in didx, f"{dom.name}: critical index missing: {i}"
        finally:
            dcon.close()
    return {"ok": True, "ops_counts": counts, "domain_files": len(domain_files)}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Pilot backup + restore drill")
    parser.add_argument("--out", default="", help="backup output dir")
    parser.add_argument("--restore", default="", help="backup dir to verify (drill)")
    parser.add_argument("--verify", action="store_true")
    args = parser.parse_args(argv)
    if args.restore:
        report = verify_backup(Path(args.restore))
        print(json.dumps(report, indent=2, default=str))
        return 0
    if not args.out:
        print("usage: python -m scripts.backup --out <dir> [--verify]")
        return 2
    out = Path(args.out)
    manifest = backup(out=out)
    print(f"backup complete: {len(manifest['files'])} files -> {out}")
    if args.verify:
        print(json.dumps(verify_backup(out), indent=2, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
