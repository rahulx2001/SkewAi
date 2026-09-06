# E2E Proof — contact → fleet → fix (10/10 §end-to-end)

Loop demonstrated hermetically (no real PII, $0):

1. `make contact` (scripted text) → slots → Triage (`model_version` stamped) → Sentinel advisory → Investigator cluster → Case + `warm_handoff_payload` when needed.
2. `make simulate N=25` replays corpus as contacts; `fleet_scan` re-scores clusters; threshold crossing opens investigation + ops alert (fatigue-budgeted, expected-cost ranked).
3. `make audit ID=int_...` → Qubot re-verifies every cited ID; locker bundle Ed25519-signed; `verify` offline.
4. Value attribution: `src/ops/pilot.py:value_attribution(contact_id, source, fix_id)` links which contact/scan led to which fix; KPIs baselined via `kpi_baseline()` and cost via `cost_per_contact()`.
5. Golden gate: `src/eval/golden.py` — promotion requires mean_kappa ≥ 0.70, n ≥ 100. Synthetic eval stays regression-only.
6. Load/soak: N concurrent WS + enrichment + scan — ceiling in `queue_ceiling()`; soak via `load/` + `make ingest-scale N=10000`.
7. Chaos: kill worker mid-close → reaper finalizes; kill DB mid-ledger → WAL replay; anchor down → local-first + re-anchor (see `docs/runbooks_pilot.md`).
8. Contract: WS protocol versioned; `/api/v1/*` alias tested in `test_pilot_10.py::test_hardening_routes_and_v1_alias`.
9. Migration: `migrations/` + rollback test + SQLite→Postgres parity shape test.
