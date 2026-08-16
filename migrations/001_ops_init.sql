-- Alembic-ready initial ops schema (feature #45).
-- Applied manually or via future Alembic env; DuckDB already has equivalent DDL.

CREATE TABLE IF NOT EXISTS interactions (
    interaction_id TEXT PRIMARY KEY,
    pack_id TEXT,
    channel TEXT,
    status TEXT,
    outcome TEXT,
    started_at TIMESTAMPTZ,
    ended_at TIMESTAMPTZ,
    peak_frustration DOUBLE PRECISION,
    tenant_id TEXT DEFAULT 'default'
);

CREATE TABLE IF NOT EXISTS cases (
    case_id TEXT PRIMARY KEY,
    interaction_id TEXT,
    pack_id TEXT,
    severity TEXT,
    status TEXT,
    category TEXT,
    cluster_id INTEGER,
    created_at TIMESTAMPTZ,
    tenant_id TEXT DEFAULT 'default'
);

CREATE TABLE IF NOT EXISTS agent_actions (
    action_id TEXT PRIMARY KEY,
    interaction_id TEXT,
    agent TEXT,
    action_type TEXT,
    input_summary TEXT,
    output_summary TEXT,
    created_at TIMESTAMPTZ,
    prev_hash TEXT,
    row_hash TEXT,
    tenant_id TEXT DEFAULT 'default'
);

CREATE INDEX IF NOT EXISTS idx_cases_tenant ON cases (tenant_id);
CREATE INDEX IF NOT EXISTS idx_interactions_tenant ON interactions (tenant_id);
