"""Resumable, idempotent corpus backfill for a single embedding version.

Does not overwrite records.embedding. Writes only to record_embeddings.
Never logs raw complaint text.
"""

from __future__ import annotations

import json
import logging
import time
from typing import Any

from src.ids import new_ulid
from src.ml_runtime.embedding_runtime import (
    backfill_batch_size,
    expected_manifest_sha,
    hash_embedder,
    semantic_embedder,
    try_semantic_embedder,
)
from src.ml_runtime.embedding_space import (
    HASH_EMBEDDING_VERSION,
    ArtifactIntegrityError,
    Embedder,
    EmbeddingUnavailableError,
    as_embedded,
)
from src.ml_runtime.embedding_store import (
    completed_ids,
    coverage_for_version,
    ensure_pack_embedding_schema,
    iter_records_for_backfill,
    list_eligible_record_ids,
    mark_embedding_status,
    upsert_embedding,
)


logger = logging.getLogger(__name__)

PERMANENT_ERROR_CODES = frozenset({"empty_text", "invalid_text", "dimension"})
TRANSIENT_ERROR_CODES = frozenset({"inference", "unavailable", "timeout"})


def _select_embedder(embedding_version: str) -> Embedder:
    if embedding_version == HASH_EMBEDDING_VERSION or embedding_version.startswith(
        "blake2b-512-v1"
    ):
        return hash_embedder()
    sem = semantic_embedder()
    if sem.version != embedding_version:
        raise ArtifactIntegrityError(
            "requested embedding_version does not match the loaded semantic artifact"
        )
    expected = expected_manifest_sha()
    meta = sem.artifact_metadata()
    if expected and meta and meta.model_sha256.lower() != expected:
        raise ArtifactIntegrityError("wrong artifact hash prevents backfill")
    return sem


def _quarantine_reason(text: str) -> str | None:
    if text is None or not str(text).strip():
        return "empty_text"
    if "\x00" in text:
        return "invalid_text"
    return None


def _write_checkpoint(run_id: str, summary: dict[str, Any], last_record_id: str | None) -> None:
    from src.data.warehouse import ops_con
    from src.data.timeutil import utc_now

    now = utc_now().replace(tzinfo=None)
    with ops_con() as con:
        con.execute(
            """
            CREATE TABLE IF NOT EXISTS embedding_backfill_runs (
                run_id VARCHAR PRIMARY KEY,
                pack_id VARCHAR,
                embedding_version VARCHAR,
                last_record_id VARCHAR,
                total_records INTEGER,
                completed INTEGER,
                in_progress INTEGER,
                failed_permanent INTEGER,
                failed_retriable INTEGER,
                quarantined INTEGER,
                checkpoint_ts TIMESTAMP,
                status VARCHAR
            )
            """
        )
        con.execute(
            """
            INSERT INTO embedding_backfill_runs (
                run_id, pack_id, embedding_version, last_record_id, total_records,
                completed, in_progress, failed_permanent, failed_retriable,
                quarantined, checkpoint_ts, status
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT (run_id) DO UPDATE SET
                last_record_id = excluded.last_record_id,
                completed = excluded.completed,
                in_progress = excluded.in_progress,
                failed_permanent = excluded.failed_permanent,
                failed_retriable = excluded.failed_retriable,
                quarantined = excluded.quarantined,
                checkpoint_ts = excluded.checkpoint_ts,
                status = excluded.status
            """,
            [
                run_id,
                summary["pack_id"],
                summary["embedding_version"],
                last_record_id,
                summary.get("eligible", 0),
                summary.get("already_completed", 0) + summary.get("newly_completed", 0),
                0,
                summary.get("failed_permanent", 0),
                summary.get("failed_retriable", summary.get("failed", 0)),
                summary.get("quarantined", 0),
                now,
                summary.get("run_status", "running"),
            ],
        )
        summary["checkpoint_ts"] = str(now)
        summary["total_records"] = summary.get("eligible", 0)
        summary["completed"] = summary.get("already_completed", 0) + summary.get("newly_completed", 0)
        summary["in_progress"] = 0


def run_backfill(
    pack_id: str,
    embedding_version: str,
    *,
    dry_run: bool = False,
    batch_size: int | None = None,
    limit: int | None = None,
    include_retry: bool = True,
    fail_after: int | None = None,
    run_id: str | None = None,
) -> dict[str, Any]:
    started = time.perf_counter()
    ensure_pack_embedding_schema(pack_id)
    embedder = _select_embedder(embedding_version)
    if embedder.version != embedding_version:
        raise ArtifactIntegrityError(
            f"embedder version {embedder.version!r} != requested {embedding_version!r}"
        )
    artifact_sha = ""
    meta = embedder.artifact_metadata()
    if meta:
        artifact_sha = meta.model_sha256 or ""
    batch_n = batch_size or backfill_batch_size()
    eligible = list_eligible_record_ids(pack_id)
    already = completed_ids(pack_id, embedding_version)
    summary: dict[str, Any] = {
        "pack_id": pack_id,
        "embedding_version": embedding_version,
        "artifact_sha256": artifact_sha,
        "dry_run": bool(dry_run),
        "batch_size": batch_n,
        "eligible": len(eligible),
        "already_completed": len(already),
        "newly_completed": 0,
        "skipped": 0,
        "retried": 0,
        "quarantined": 0,
        "failed": 0,
        "failed_permanent": 0,
        "failed_retriable": 0,
        "throughput_per_s": 0.0,
        "duration_s": 0.0,
        "run_id": run_id or ("ebr_" + new_ulid()),
        "run_status": "running",
        "last_record_id": None,
    }
    processed = 0
    for batch in iter_records_for_backfill(
        pack_id, embedding_version, batch_size=batch_n, include_retry=include_retry
    ):
        if limit is not None and processed >= limit:
            break
        if limit is not None:
            batch = batch[: max(0, limit - processed)]
        if dry_run:
            summary["skipped"] += len(batch)
            processed += len(batch)
            continue
        clean: list[tuple[str, str]] = []
        for rid, text in batch:
            reason = _quarantine_reason(text)
            if reason:
                mark_embedding_status(
                    pack_id,
                    rid,
                    embedding_version,
                    status="quarantined",
                    error_code=reason,
                    error_message=reason,
                    native_dimension=embedder.native_dimension,
                    output_dimension=embedder.output_dimension,
                )
                summary["quarantined"] += 1
                summary["failed_permanent"] += 1
                continue
            clean.append((rid, text))
        if not clean:
            processed += len(batch)
            continue
        try:
            vectors = embedder.embed_many([t for _, t in clean])
        except (EmbeddingUnavailableError, ArtifactIntegrityError) as e:
            for rid, _ in clean:
                mark_embedding_status(
                    pack_id,
                    rid,
                    embedding_version,
                    status="failed",
                    error_code="unavailable",
                    error_message=type(e).__name__,
                    native_dimension=embedder.native_dimension,
                    output_dimension=embedder.output_dimension,
                )
                summary["failed"] += 1
                summary["failed_retriable"] += 1
            processed += len(batch)
            continue
        if len(vectors) != len(clean):
            raise RuntimeError("embedder returned a different batch size")
        for (rid, _), vec in zip(clean, vectors):
            if vec.embedding_version != embedding_version:
                mark_embedding_status(
                    pack_id,
                    rid,
                    embedding_version,
                    status="failed",
                    error_code="version",
                    error_message="embedder version drift",
                    native_dimension=embedder.native_dimension,
                    output_dimension=embedder.output_dimension,
                )
                summary["failed"] += 1
                continue
            upsert_embedding(
                pack_id,
                rid,
                vec,
                artifact_sha256=artifact_sha,
                status="complete",
                model_key=vec.model_key,
                sanitized=False,
            )
            summary["newly_completed"] += 1
            summary["last_record_id"] = rid
            if fail_after is not None and summary["newly_completed"] >= int(fail_after):
                summary["run_status"] = "interrupted"
                _write_checkpoint(str(summary["run_id"]), summary, rid)
                raise RuntimeError("injected_interrupt")
        processed += len(batch)
        _write_checkpoint(str(summary["run_id"]), summary, summary.get("last_record_id"))
    elapsed = time.perf_counter() - started
    done_now = summary["newly_completed"]
    summary["duration_s"] = round(elapsed, 4)
    summary["throughput_per_s"] = round(done_now / elapsed, 3) if elapsed else 0.0
    summary["skipped"] += summary["already_completed"]
    cov = coverage_for_version(pack_id, embedding_version)
    summary["coverage"] = cov
    summary["run_status"] = "complete"
    summary["total_records"] = summary["eligible"]
    summary["completed"] = summary["already_completed"] + summary["newly_completed"]
    summary["in_progress"] = 0
    _write_checkpoint(str(summary["run_id"]), summary, summary.get("last_record_id"))
    logger.info(
        "embedding_backfill_done pack=%s newly=%s quarantined=%s failed=%s",
        pack_id,
        summary["newly_completed"],
        summary["quarantined"],
        summary["failed"],
    )
    return summary


def job_handler(payload: dict[str, Any]) -> dict[str, Any]:
    pack = payload.get("pack_id") or "automotive_nhtsa"
    version = payload.get("embedding_version") or ""
    if not version:
        raise ValueError("embedding_version is required")
    return run_backfill(
        pack,
        version,
        dry_run=bool(payload.get("dry_run")),
        batch_size=payload.get("batch_size"),
        limit=payload.get("limit"),
        include_retry=bool(payload.get("include_retry", True)),
    )


__all__ = ["run_backfill", "job_handler"]
