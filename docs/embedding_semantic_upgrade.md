# Semantic embedding upgrade — operator runbook

Default after deploy is **legacy**: the blake2b-512 hash embedder stays
customer-visible. Semantic results do not change cases until you
explicitly activate them.

## Safe sequence

1. Prepare the local artifact (network allowed here only):

   `python -m scripts.prepare_minilm_onnx --out models/minilm`

   Confirm `manifest.json` and `checksums.sha256`. Set
   `FRONTLINE_SEMANTIC_MODEL_SHA256` to the model file digest.

2. Apply schema: DuckDB applies `record_embeddings` / `cluster_builds` on
   open. Postgres: `python -m scripts.migrate --db postgres` after the
   sidecar DDL in `PG_PRODUCTION_DDL` is reviewed.

3. Enable shadow (hash remains visible):

   `FRONTLINE_EMBEDDING_MODE=shadow`
   `FRONTLINE_SEMANTIC_ARTIFACT_DIR=models/minilm`

4. Dry-run backfill:

   `python -m scripts.embedding_backfill --pack automotive_nhtsa --dry-run`

5. Backfill (resumable, idempotent, does not overwrite `records.embedding`):

   `python -m scripts.embedding_backfill --pack automotive_nhtsa`

6. Review quarantined rows:

   `SELECT record_id, error_code FROM record_embeddings WHERE status='quarantined'`

7. Build a semantic cluster version (does not delete hash-era clusters):

   `python -m scripts.rebuild_cluster_build --pack automotive_nhtsa --dry-run`
   `python -m scripts.rebuild_cluster_build --pack automotive_nhtsa`

8. Offline eval:

   `make embedding-eval`
   `python -m scripts.embedding_benchmark`

9. Compare shadow rows in `embedding_shadow_comparisons` (IDs and scores
   only; no complaint text).

10. Cutover (atomic from the app’s perspective):

    `FRONTLINE_EMBEDDING_MODE=semantic`
    `FRONTLINE_ACTIVE_CLUSTER_BUILD_ID=<build_id>`
    `FRONTLINE_SEMANTIC_MODEL_SHA256=<sha>`

    Startup refuses semantic mode if the artifact is missing, the cluster
    build version disagrees, or backfill is partial (override:
    `FRONTLINE_EMBEDDING_ALLOW_PARTIAL=1`).

11. Monitor `/health` `embedding` payload: mode, `semantic_ready`, version
    prefix. Watch sidecar coverage, shadow overlap, novelty counts, and
    Qubot mismatch flags.

12. Rollback:

    `FRONTLINE_EMBEDDING_MODE=rollback`
    unset `FRONTLINE_ACTIVE_CLUSTER_BUILD_ID`

    Hash-era `records.embedding` and `clusters` are unchanged. Semantic
    sidecar rows are retained.

## Thresholds

Hash-era `FRONTLINE_CLUSTER_MAX_DISTANCE` (default 0.85) and
`FRONTLINE_NOVELTY_MIN_SCORE` (default 3.0) were calibrated on hash
vectors. Do not treat them as semantic production thresholds until a
reviewed pair set exists. Semantic cutover with inherited thresholds is
an operational risk; leave semantic mode off until calibration.

## What this change does not do

Safety lexicons, kill-switch, P1 floor, slot extraction, ASR
confirmation, anomaly formulas, and sentiment scoring are untouched.
A semantic embedding failure cannot delay or weaken those paths.
