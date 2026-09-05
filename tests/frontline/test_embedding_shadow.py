"""Shadow mode: hash remains visible; semantic is recorded separately."""

from __future__ import annotations

import pytest

from src.ml_runtime.embedding_match import maybe_run_shadow, rank_hash
from src.ml_runtime.embedding_runtime import reset_embedding_runtime
from src.ml_runtime.embedding_shadow import load_shadow_comparisons
from src.ml_runtime.onnx_embedder import ToySemanticEmbedder


@pytest.fixture
def toy_shadow(monkeypatch, reset_ops_db):
    monkeypatch.setenv("FRONTLINE_EMBEDDING_TOY", "1")
    monkeypatch.setenv("FRONTLINE_EMBEDDING_MODE", "shadow")
    reset_embedding_runtime()
    yield
    reset_embedding_runtime()


def test_shadow_does_not_change_hash_ranking(toy_shadow, seed_automotive_pack):
    cands = [
        {"record_id": "a", "text": "brake grinding at low speed"},
        {"record_id": "b", "text": "airbag light on"},
    ]
    hashed = rank_hash("grinding brakes", cands, top_k=2)
    assert hashed
    assert hashed[0]["record_id"] in {"a", "b"}
    maybe_run_shadow(
        interaction_id="int_shadow_test",
        pack_id="automotive_nhtsa",
        query="grinding brakes",
        candidates=cands,
        hash_ranked=hashed,
        hash_cluster_id=1000,
        hash_novel=False,
    )
    rows = load_shadow_comparisons("int_shadow_test")
    assert len(rows) == 1
    rec = rows[0]
    assert rec["semantic_status"] in {"performed", "skipped", "failed"}
    # Shadow must not invent an active novelty queue row.
    from src.data.warehouse import ops_con

    with ops_con(read_only=True) as con:
        n = con.execute(
            "SELECT COUNT(*) FROM novel_candidates WHERE interaction_id = 'int_shadow_test'"
        ).fetchone()[0]
    assert n == 0


def test_legacy_mode_skips_shadow(monkeypatch, reset_ops_db):
    monkeypatch.setenv("FRONTLINE_EMBEDDING_MODE", "legacy")
    reset_embedding_runtime()
    out = maybe_run_shadow(
        interaction_id="int_legacy",
        pack_id="automotive_nhtsa",
        query="x",
        candidates=[],
        hash_ranked=[],
        hash_cluster_id=None,
        hash_novel=False,
    )
    assert out is None
