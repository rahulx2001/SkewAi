# Database optimization notes (Frontline v2 / DuckDB)

Date: 2026-07-21  
Stack: **DuckDB** ops warehouse (`data/frontline.duckdb`) + per-pack domain warehouses.

## Baseline findings

Hot paths (from code review + `EXPLAIN` on a **20k–50k row** synthetic ops load):

| Query pattern | Issue |
|---------------|--------|
| `cases WHERE interaction_id = ?` | **No index** → sequential scan on every audit/risk/timeline/export |
| `cases WHERE pack_id + cluster_match_id + created_at` | Investigation auto-link + live_risk aggregation under-indexed |
| `cases WHERE status IN (...) ORDER BY created_at` | Queue lists partial index only on `(status, severity)` |
| `interactions` failure / frustration filters | Status/outcome and peak_frustration scans under-indexed |
| `interaction_turns WHERE interaction_id + speaker` | Risk turn counts only had `(interaction_id, seq)` |
| `agent_actions WHERE ts >= now() - window` | Window digests scanned full table without `ts` index |
| `investigation_status` | **N+1** SQL: one cases query per investigation |

DuckDB often still reports `SEQ_SCAN` on small tables (optimizer cost model); wall-clock still improves on selective filters, and indexes matter as pilot data grows.

## Changes shipped

### 1. Indexes (`src/data/schema.py`)

**Ops**

- `idx_cases_interaction` — FK path case ↔ interaction  
- `idx_cases_cluster_pack_created` — live risk / inv threshold counts  
- `idx_cases_status_created` — open queue by recency  
- `idx_cases_category` — copilot / filter by category  
- `idx_interactions_status_outcome` — abandoned/escalated lists  
- `idx_interactions_peak_fr` — “most frustrated” ranking  
- `idx_interactions_entities` — entity triple filters  
- `idx_turns_ix_speaker` — customer turn counts  
- `idx_actions_ts`, `idx_actions_ok_ts` — window + failure scans  

**Domain**

- `idx_advisories_issued`, `idx_advisories_scope_e1`  
- `idx_clusters_pack`  
- `idx_weekly_anom_pack_week`  

All use `CREATE INDEX IF NOT EXISTS` so existing DBs pick them up on next write bootstrap / `init_ops_db`.

### 2. Query rewrite

`investigation_status` loads all linked cases in **one** `WHERE investigation_id IN (...)` and embeds `days_open` in the header SELECT (no per-row re-query).

### 3. Connection hygiene

- Thread-local **read-only** ops connection reuse (dashboard/list-heavy paths).  
- Cache cleared on write open and `reset_ops_db`.  
- `ANALYZE` on core tables after `apply_ops_schema` so the planner sees new indexes.

## How to apply on an existing pilot DB

Indexes are applied automatically the next time the process opens a **write** connection (schema bootstrap) or when you run:

```bash
# from repo root, venv active
python -c "from src.data.warehouse import init_ops_db; init_ops_db()"
```

For domain packs after rebuild:

```bash
make frontline-db   # or scripts.seed_domains per pack
```

## Validation

- Full `tests/frontline`: green after changes (261 tests at ship time).  
- Synthetic bench: point lookup `cases.interaction_id` improved ~**3–4×** wall-clock on 50k rows in local runs; connection reuse cut repeated RO open cost.

## Monitoring recommendations

1. After bulk simulate/eval loads, ensure process restarts or write once so `ANALYZE` runs.  
2. If a list endpoint slows, capture `EXPLAIN <sql>` in DuckDB CLI on `data/frontline.duckdb`.  
3. Prefer **not** adding more indexes on write-heavy `agent_actions` without a measured list/filter need (write amplification).  
4. Single-worker DuckDB remains a deploy constraint (`/health` `single_worker`); multi-writer Postgres is still a non-goal.

## Non-goals

- PostgreSQL / MySQL migration  
- Partitioning / sharding  
- Cross-process connection pools  
- Fake “we use OTEL on DuckDB” claims  
