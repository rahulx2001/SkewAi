# Pilot Runbooks (10/10 operability §8)

## stuck contact
1. `GET /api/frontline/metrics` — check active calls, queue depth.
2. `GET /health` — confirm `single_worker:true`; do not start a second worker.
3. Find interaction: audit export `GET /api/frontline/audits/export?start=...&end=...`.
4. If COLLECTING > max_turns: orchestrator force wrap-ups automatically; if wedged, supervisor takeover via Live Console then release.
5. Ledger check: `make verify-chain ID=int_...`.

## duplicate case
1. Search cases `GET /api/frontline/cases?q=...`.
2. Compare `event_key` (see `src/quality/guards.py:event_key`) across sources.
3. Keep earliest case, PATCH others to `duplicate_of=<case_id>` + operator note.
4. File quarantine review so ingest dedup rule covers the pattern.

## anchor down (Merkle/locker)
1. Contacts continue — ledger is local-first; anchoring is async.
2. Check rotation manifest `data/locker_keys/ring/rotation.json`; old pubs still verify.
3. Re-run anchor when service returns; verify chain before + after.

## model unavailable
1. Triage safe-fallbacks to rules (`source=rules`, `model_healthy=False` gauged).
2. Check `model_health()` + model card version in `data/model_cards/`.
3. Shadow challenger continues scoring in background; do not hot-swap — promote via card.

## queue backlog
1. `GET /api/frontline/hardening/slos` — depth vs ceiling (50 pending / 10 running).
2. If sustained > ceiling 7d: migrate JOB_BACKEND db-poll → Redis/SQS (see `src/ops/pilot.py:queue_ceiling`).
3. Apply fatigue budget: `POST /hardening/stats/robust` ranks by expected cost, caps 5/engineer/day.

## DR (RTO/RPO)
- RTO 4h / RPO 1h for single-tenant pilot (ops DuckDB + domain DuckDBs + locker dir).
- Backup: `data/frontline.duckdb`, `data/domains/*.duckdb`, `reports/qubot/lockers/`, `data/locker_keys/`.
- Restore test quarterly: restore → `make verify-chain` on sample + audit export diff must be empty.
- Merkle anchor residency: `MERKLE_ANCHOR_RESIDENCY` (default us-tenant-local).
