# Migrations — deployment ordering (item 48)

Runner: `python -m scripts.migrate --db ops|domain|postgres`

| File | Target | Contents |
|------|--------|----------|
| `001_ops_init.sql` | ops | Baseline ops schema (interactions, cases, ledger, jobs, …) |
| `002_pg_vector_fts.sql` | postgres | pgvector 512-dim, `fts_main_records`, trigram index, rollups |

Rules:

1. Files are append-only and idempotent (`IF NOT EXISTS`, guarded `ALTER`).
   A half-applied deploy can safely retry; re-runs are no-ops.
2. Scope via the `-- target:` header (`ops`, `domain`, `postgres`, `all`).
3. Each database records applied versions in `schema_migrations`.
4. Runtime DuckDB code keeps `CREATE TABLE IF NOT EXISTS` + guarded `ALTER`
   for local/dev (see `apply_domain_schema` / `apply_ops_schema`); the runner
   is authoritative for production Postgres, where the app never runs DDL.
5. Deploy order: `001` → `002` → `ANALYZE` → (after bulk load) tune the
   IVFFlat `lists` parameter and `REINDEX`.

## Backup / PITR strategy

- DuckDB pilot: `python -m scripts.backup --out <dir> --verify` (CHECKPOINT +
  copy + sha256 manifest + restore-drill verification of critical tables and
  indexes). Private locker keys are NOT copied — restore those from the
  secret manager (see item 50).
- Postgres production: continuous WAL archiving + `pg_basebackup`; PITR to any
  point via the managed provider. Verify with the same critical-table checklist
  in `scripts/backup.py::verify_backup` (adapted to the PG DSN), plus an
  air-gapped locker-bundle verification (`python -m src.qubot.locker verify`).
- RTO/RPO targets live in `docs/compliance/backup_and_dr.md`.
