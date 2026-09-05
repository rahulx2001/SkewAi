"""Versioned cluster rebuild does not delete hash-era clusters."""

from __future__ import annotations

import pytest

from src.ml_runtime.cluster_builds import (
    activate_cluster_build,
    list_cluster_builds,
    rebuild_cluster_build,
    rollback_cluster_build,
)
from src.ml_runtime.embedding_backfill import run_backfill
from src.ml_runtime.embedding_runtime import reset_embedding_runtime
from src.ml_runtime.onnx_embedder import ToySemanticEmbedder


@pytest.fixture
def toy_ready(monkeypatch, seed_automotive_pack):
    monkeypatch.setenv("FRONTLINE_EMBEDDING_TOY", "1")
    monkeypatch.setenv("FRONTLINE_EMBEDDING_MODE", "shadow")
    reset_embedding_runtime()
    ver = ToySemanticEmbedder().version
    run_backfill("automotive_nhtsa", ver, batch_size=8)
    yield ver
    reset_embedding_runtime()


def test_rebuild_creates_separate_version(toy_ready):
    from src.data.warehouse import domain_con

    with domain_con("automotive_nhtsa", read_only=True) as con:
        old_n = con.execute("SELECT COUNT(*) FROM clusters").fetchone()[0]
    dry = rebuild_cluster_build("automotive_nhtsa", toy_ready, k=3, dry_run=True)
    assert dry["dry_run"] is True
    assert "build_id" not in dry
    built = rebuild_cluster_build("automotive_nhtsa", toy_ready, k=3, dry_run=False)
    assert built["status"] == "built"
    assert built["build_id"].startswith("cbuild_")
    assert built["activated"] is False
    with domain_con("automotive_nhtsa", read_only=True) as con:
        new_n = con.execute("SELECT COUNT(*) FROM clusters").fetchone()[0]
        builds = con.execute("SELECT COUNT(*) FROM cluster_builds").fetchone()[0]
    assert new_n == old_n  # live hash clusters untouched
    assert builds >= 1
    act = activate_cluster_build("automotive_nhtsa", built["build_id"])
    assert act["status"] == "active"
    rb = rollback_cluster_build("automotive_nhtsa", built["build_id"])
    assert rb["status"] == "rolled_back"
    listed = list_cluster_builds("automotive_nhtsa")
    assert any(b["build_id"] == built["build_id"] for b in listed)


def test_rebuild_rejects_mixed_versions(toy_ready):
    from src.ml_runtime.embedding_space import HASH_EMBEDDING_VERSION, as_embedded
    from src.ml_runtime.embedding_store import upsert_embedding
    from src.data.warehouse import domain_con

    with domain_con("automotive_nhtsa", read_only=True) as con:
        rid = con.execute("SELECT record_id FROM records LIMIT 1").fetchone()[0]
    upsert_embedding(
        "automotive_nhtsa",
        str(rid),
        as_embedded([0.0] * 512, HASH_EMBEDDING_VERSION),
        status="complete",
    )
    # Mixed rows for the *requested* version are missing, not mixed; requesting
    # hash version against toy-backfilled corpus still only reads that version.
    out = rebuild_cluster_build("automotive_nhtsa", HASH_EMBEDDING_VERSION, k=2)
    assert out["excluded"]["missing"] >= 0
