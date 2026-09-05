-- 003: versioned embedding sidecar + cluster builds (semantic upgrade).
-- target: domain
-- records.embedding remains the hash-era 512-d column (blake2b-512-v1).
-- New vectors live in record_embeddings keyed by (record_id, embedding_version).
-- Cluster rebuilds for a new embedding version write cluster_builds without
-- deleting the live hash-era clusters / cluster_assignments tables.
-- Rollback: leave tables in place; set FRONTLINE_EMBEDDING_MODE=rollback.

CREATE TABLE IF NOT EXISTS record_embeddings (
    record_id          TEXT NOT NULL,
    embedding_version  TEXT NOT NULL,
    native_dimension   INTEGER NOT NULL,
    output_dimension   INTEGER NOT NULL,
    artifact_sha256    TEXT,
    embedding          FLOAT[],
    status             TEXT NOT NULL,
    error_code         TEXT,
    error_message      TEXT,
    created_at         TIMESTAMP DEFAULT current_timestamp,
    updated_at         TIMESTAMP DEFAULT current_timestamp,
    PRIMARY KEY (record_id, embedding_version)
);

CREATE INDEX IF NOT EXISTS idx_record_embeddings_version
    ON record_embeddings (embedding_version, status);

CREATE TABLE IF NOT EXISTS cluster_builds (
    build_id                  TEXT PRIMARY KEY,
    pack_id                   TEXT NOT NULL,
    embedding_version         TEXT NOT NULL,
    cluster_algorithm_version TEXT NOT NULL,
    parameters_json           TEXT NOT NULL,
    source_cutoff             TIMESTAMP,
    status                    TEXT NOT NULL,
    coverage_json             TEXT,
    created_at                TIMESTAMP DEFAULT current_timestamp,
    activated_at              TIMESTAMP
);

CREATE TABLE IF NOT EXISTS cluster_build_clusters (
    build_id           TEXT NOT NULL,
    cluster_id         INTEGER NOT NULL,
    cluster_uid        TEXT NOT NULL,
    embedding_version  TEXT NOT NULL,
    centroid           FLOAT[],
    top_terms          TEXT,
    category           TEXT,
    record_count       INTEGER NOT NULL,
    first_seen         TIMESTAMP,
    last_seen          TIMESTAMP,
    signature          TEXT,
    PRIMARY KEY (build_id, cluster_id)
);

CREATE TABLE IF NOT EXISTS cluster_build_assignments (
    build_id           TEXT NOT NULL,
    record_id          TEXT NOT NULL,
    cluster_id         INTEGER NOT NULL,
    embedding_version  TEXT NOT NULL,
    distance           DOUBLE PRECISION,
    PRIMARY KEY (build_id, record_id)
);
