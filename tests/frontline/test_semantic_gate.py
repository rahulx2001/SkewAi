"""Tests for F-007: semantic embedding fail-closed startup validation."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from src.api.main import _readiness_report, app
from src.ml_runtime.embedding_runtime import (
    EmbeddingUnavailableError,
    reset_embedding_runtime,
)


def test_f007_semantic_mode_without_active_cluster_build_refuses_startup(monkeypatch):
    """F-007: App startup must fail-closed when FRONTLINE_EMBEDDING_MODE=semantic without valid cluster build."""
    reset_embedding_runtime()
    monkeypatch.setenv("FRONTLINE_EMBEDDING_MODE", "semantic")
    monkeypatch.delenv("FRONTLINE_ACTIVE_CLUSTER_BUILD_ID", raising=False)
    monkeypatch.delenv("FRONTLINE_EMBEDDING_TOY", raising=False)
    # Ensure startup readiness is not skipped
    monkeypatch.delenv("FRONTLINE_READINESS_SKIP_STARTUP", raising=False)

    with pytest.raises(EmbeddingUnavailableError, match="FRONTLINE_ACTIVE_CLUSTER_BUILD_ID is required"):
        with TestClient(app):
            pass


def test_f007_readiness_report_enforces_validate_startup_config(monkeypatch, reset_ops_db):
    """F-007: Readiness probe must fail semantic_embedder check if validate_startup_config fails."""
    reset_embedding_runtime()
    monkeypatch.setenv("FRONTLINE_EMBEDDING_MODE", "semantic")
    monkeypatch.delenv("FRONTLINE_ACTIVE_CLUSTER_BUILD_ID", raising=False)
    monkeypatch.delenv("FRONTLINE_EMBEDDING_TOY", raising=False)

    report = _readiness_report("automotive_nhtsa", None, db_ok=True)
    check = report["checks"].get("semantic_embedder")
    assert check is not None
    assert check["ok"] is False
    assert "FRONTLINE_ACTIVE_CLUSTER_BUILD_ID is required" in check["note"]


def test_f007_legacy_mode_startup_passes(monkeypatch, reset_ops_db, seed_automotive_pack):
    """F-007: Default legacy mode does not require semantic artifact or cluster build."""
    reset_embedding_runtime()
    monkeypatch.setenv("FRONTLINE_EMBEDDING_MODE", "legacy")

    with TestClient(app) as client:
        resp = client.get("/health/ready")
        assert resp.status_code == 200
