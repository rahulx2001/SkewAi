"""Append-only embedding model registry.

No UPDATE or DELETE. Status changes are new rows. Current status for a
``model_key`` is the latest ``created_at`` row.
"""

from __future__ import annotations

from typing import Any

from src.data.timeutil import utc_now
from src.data.warehouse import ops_con
from src.ids import new_ulid

EMBEDDING_MODELS_DDL = """
CREATE TABLE IF NOT EXISTS embedding_models (
    registry_row_id    VARCHAR PRIMARY KEY,
    model_key          VARCHAR NOT NULL,
    display_name       VARCHAR NOT NULL,
    artifact_sha256    VARCHAR,
    tokenizer_sha256   VARCHAR,
    pooling            VARCHAR,
    normalization      VARCHAR,
    padding_strategy   VARCHAR,
    dimension          INTEGER NOT NULL,
    created_at         TIMESTAMP NOT NULL,
    created_by         VARCHAR NOT NULL,
    status             VARCHAR NOT NULL,
    deprecation_reason VARCHAR
)
"""

_VALID_STATUS = frozenset({"active", "retired", "deprecated"})


def ensure_embedding_models(con) -> None:
    con.execute(EMBEDDING_MODELS_DDL)
    try:
        con.execute(
            "CREATE INDEX IF NOT EXISTS idx_embedding_models_key "
            "ON embedding_models(model_key, created_at)"
        )
    except Exception:
        pass


def register_model(
    *,
    model_key: str,
    display_name: str,
    dimension: int,
    created_by: str,
    artifact_sha256: str = "",
    tokenizer_sha256: str = "",
    pooling: str = "",
    normalization: str = "",
    padding_strategy: str = "",
    status: str = "active",
    deprecation_reason: str | None = None,
) -> str:
    if status not in _VALID_STATUS:
        raise ValueError(f"invalid embedding model status {status!r}")
    rid = "emr_" + new_ulid()
    now = utc_now().replace(tzinfo=None)
    with ops_con() as con:
        ensure_embedding_models(con)
        con.execute(
            """
            INSERT INTO embedding_models (
                registry_row_id, model_key, display_name, artifact_sha256,
                tokenizer_sha256, pooling, normalization, padding_strategy,
                dimension, created_at, created_by, status, deprecation_reason
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            [
                rid,
                model_key,
                display_name,
                artifact_sha256 or None,
                tokenizer_sha256 or None,
                pooling or None,
                normalization or None,
                padding_strategy or None,
                int(dimension),
                now,
                created_by,
                status,
                deprecation_reason,
            ],
        )
    return rid


def retire_model(model_key: str, *, created_by: str, reason: str) -> str:
    current = current_model(model_key)
    if current is None:
        raise LookupError(f"unknown embedding model_key {model_key!r}")
    return register_model(
        model_key=model_key,
        display_name=str(current["display_name"]),
        dimension=int(current["dimension"]),
        created_by=created_by,
        artifact_sha256=current.get("artifact_sha256") or "",
        tokenizer_sha256=current.get("tokenizer_sha256") or "",
        pooling=current.get("pooling") or "",
        normalization=current.get("normalization") or "",
        padding_strategy=current.get("padding_strategy") or "",
        status="retired",
        deprecation_reason=reason,
    )


def current_model(model_key: str) -> dict[str, Any] | None:
    with ops_con(read_only=True) as con:
        try:
            row = con.execute(
                """
                SELECT registry_row_id, model_key, display_name, artifact_sha256,
                       tokenizer_sha256, pooling, normalization, padding_strategy,
                       dimension, created_at, created_by, status, deprecation_reason
                FROM embedding_models
                WHERE model_key = ?
                ORDER BY created_at DESC, registry_row_id DESC
                LIMIT 1
                """,
                [model_key],
            ).fetchone()
        except Exception:
            return None
    if not row:
        return None
    keys = [
        "registry_row_id",
        "model_key",
        "display_name",
        "artifact_sha256",
        "tokenizer_sha256",
        "pooling",
        "normalization",
        "padding_strategy",
        "dimension",
        "created_at",
        "created_by",
        "status",
        "deprecation_reason",
    ]
    return dict(zip(keys, row))


def list_model_history(model_key: str) -> list[dict[str, Any]]:
    with ops_con(read_only=True) as con:
        try:
            cur = con.execute(
                """
                SELECT registry_row_id, status, created_at, created_by, deprecation_reason
                FROM embedding_models WHERE model_key = ? ORDER BY created_at
                """,
                [model_key],
            )
            cols = [d[0] for d in cur.description]
            return [dict(zip(cols, r)) for r in cur.fetchall()]
        except Exception:
            return []


__all__ = [
    "register_model",
    "retire_model",
    "current_model",
    "list_model_history",
    "ensure_embedding_models",
]
