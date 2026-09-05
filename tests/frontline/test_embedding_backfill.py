"""Resumable sidecar backfill: dry-run, idempotency, resume, quarantine."""

from __future__ import annotations

import os

import pytest

from src.ml_runtime.embedding_backfill import run_backfill
from src.ml_runtime.embedding_runtime import reset_embedding_runtime
from src.ml_runtime.embedding_store import completed_ids, coverage_for_version
from src.ml_runtime.onnx_embedder import ToySemanticEmbedder


@pytest.fixture
def toy_mode(monkeypatch):
    monkeypatch.setenv("FRONTLINE_EMBEDDING_TOY", "1")
    monkeypatch.setenv("FRONTLINE_EMBEDDING_MODE", "shadow")
    reset_embedding_runtime()
    yield
    reset_embedding_runtime()
    monkeypatch.delenv("FRONTLINE_EMBEDDING_TOY", raising=False)


def test_backfill_dry_run_writes_nothing(seed_automotive_pack, toy_mode):
    ver = ToySemanticEmbedder().version
    before = completed_ids("automotive_nhtsa", ver)
    out = run_backfill("automotive_nhtsa", ver, dry_run=True, batch_size=4)
    assert out["dry_run"] is True
    assert out["eligible"] >= 1
    assert completed_ids("automotive_nhtsa", ver) == before


def test_backfill_success_idempotent_resume(seed_automotive_pack, toy_mode):
    ver = ToySemanticEmbedder().version
    first = run_backfill("automotive_nhtsa", ver, batch_size=3, limit=3)
    assert first["newly_completed"] >= 1
    mid = completed_ids("automotive_nhtsa", ver)
    second = run_backfill("automotive_nhtsa", ver, batch_size=3)
    # Resume: already complete rows are not duplicated.
    assert second["already_completed"] >= len(mid)
    third = run_backfill("automotive_nhtsa", ver, batch_size=8)
    assert third["newly_completed"] == 0
    cov = coverage_for_version("automotive_nhtsa", ver)
    assert cov["complete"] >= first["newly_completed"]


def test_backfill_quarantines_empty_text(seed_automotive_pack, toy_mode):
    from src.data.warehouse import apply_domain_schema, domain_con

    ver = ToySemanticEmbedder().version
    with domain_con("automotive_nhtsa", read_only=False) as con:
        apply_domain_schema(con)
        con.execute(
            """
            INSERT OR REPLACE INTO records
            (record_id, received_at, text, provenance)
            VALUES ('EMPTY-1', CURRENT_TIMESTAMP, '   ', 'fixture')
            """
        )
    out = run_backfill("automotive_nhtsa", ver, batch_size=16)
    assert out["quarantined"] >= 1


def test_wrong_artifact_hash_prevents_backfill(seed_automotive_pack, toy_mode, monkeypatch):
    monkeypatch.setenv("FRONTLINE_SEMANTIC_MODEL_SHA256", "deadbeef" * 8)
    reset_embedding_runtime()
    ver = ToySemanticEmbedder().version
    from src.ml_runtime.embedding_space import ArtifactIntegrityError

    with pytest.raises(ArtifactIntegrityError):
        run_backfill("automotive_nhtsa", ver, batch_size=2)
