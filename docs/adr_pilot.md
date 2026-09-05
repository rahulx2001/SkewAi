# ADR-001: SQLite/DuckDB-first, Postgres at volume
- Status: accepted. Fixture + pilot on DuckDB (`data/frontline.duckdb`).
- Flip primary to Postgres only when sustained queue depth > ceiling or corpus > ~1M rows.
- Parity suite: same seed → same counts/chain hashes (see `tests/.../test_pilot_10.py::test_parity_shape`).

# ADR-002: ULIDs for interactions/cases
- Sortable, unguessable-enough, no central sequence. Kept.

# ADR-003: Hash-chained ledger + Ed25519 locker with rotation ring
- Every agent action ledgered before output. Locker keys rotate; retired pubs stay in `data/locker_keys/ring/` so old signatures verify (`src/security/rotation.py`).
- Never delete ledger rows; DSR = tombstone + redact.

# ADR-004: DB computes, agents narrate from templates
- Numbers come from DuckDB; LLM only rephrases (capped, fallback). Keeps $0 hermetic CI.

# ADR-005: /api/* canonical, /api/v1/* alias
- Single router source; V1AliasASGI rewrites. Breaking changes → /api/v2/*.

# ADR-006: One ranked engineer queue
- Four tabs replaced by expected_cost × confidence ÷ (1+lead_time) (`src/ops/pilot.py:rank_engineer_queue`).
