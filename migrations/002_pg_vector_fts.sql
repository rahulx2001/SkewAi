-- 002: production Postgres vector + FTS surface (item 32).
-- target: postgres
-- Alembic-ready SQL; also embedded as PG_PRODUCTION_DDL in
-- src/data/postgres_backend.py::ensure_postgres_schema (single source of
-- truth for review — keep both in sync).
-- Deploy ordering: run AFTER 001_ops_init.sql, then ANALYZE, then (after bulk
-- load) tune the IVFFlat lists parameter to sqrt(rowcount) and REINDEX.
-- Rollback: DROP INDEX fts_main_records / idx_pg_records_embedding /
-- idx_pg_records_trgm; DROP TABLE weekly_rollups; DROP EXTENSION vector
-- (only if no other objects depend on it).

CREATE EXTENSION IF NOT EXISTS vector;
CREATE EXTENSION IF NOT EXISTS pg_trgm;

ALTER TABLE records ADD COLUMN IF NOT EXISTS embedding vector(512);

ALTER TABLE records ADD COLUMN IF NOT EXISTS fts tsvector
    GENERATED ALWAYS AS (
        to_tsvector('english', coalesce(text, '') || ' ' || coalesce(category, ''))
    ) STORED;

-- Full-text search surface: replaces contact-level ILIKE '%keyword%' scans.
CREATE INDEX IF NOT EXISTS fts_main_records ON records USING GIN (fts);
CREATE INDEX IF NOT EXISTS idx_pg_records_trgm ON records USING GIN (text gin_trgm_ops);

-- Cosine similarity over 512-dim embeddings.
CREATE INDEX IF NOT EXISTS idx_pg_records_embedding
    ON records USING ivfflat (embedding vector_cosine_ops) WITH (lists = 100);

CREATE INDEX IF NOT EXISTS idx_pg_records_received ON records (received_at);
CREATE INDEX IF NOT EXISTS idx_pg_records_category ON records (category);
CREATE INDEX IF NOT EXISTS idx_pg_records_entities ON records (entity_1, entity_2, entity_3);

-- Reporting rollups (rebuilt by refresh_weekly_rollups after recompute).
CREATE TABLE IF NOT EXISTS weekly_rollups (
    pack_id         TEXT NOT NULL,
    iso_week        TEXT NOT NULL,
    category        TEXT,
    entity_2        TEXT,
    record_count    INTEGER NOT NULL DEFAULT 0,
    anomaly_count   INTEGER NOT NULL DEFAULT 0,
    PRIMARY KEY (pack_id, iso_week, category, entity_2)
);
CREATE INDEX IF NOT EXISTS idx_pg_rollups_week ON weekly_rollups (pack_id, iso_week);
