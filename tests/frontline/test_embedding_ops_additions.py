"""Registry, determinism, shadow kill, backfill interrupt, budget."""

from __future__ import annotations

import pytest

from src.ml_runtime.embedding_models import current_model, register_model, retire_model
from src.ml_runtime.embedding_runtime import (
    budget_violations,
    reset_embedding_runtime,
    shadow_enabled,
    shadow_kill_switch,
)
from src.ml_runtime.embedding_space import EmbeddingVersionMismatch, as_embedded, compare_embeddings
from src.ml_runtime.hash_embedder import HashEmbedder
from src.ml_runtime.onnx_embedder import ToySemanticEmbedder


def test_append_only_registry(reset_ops_db):
    register_model(
        model_key="blake2b-512-v1",
        display_name="Hash",
        dimension=512,
        created_by="test",
        padding_strategy="none",
        status="active",
    )
    retire_model("blake2b-512-v1", created_by="test", reason="superseded")
    cur = current_model("blake2b-512-v1")
    assert cur["status"] == "retired"
    from src.data.warehouse import ops_con

    with ops_con(read_only=True) as con:
        n = con.execute(
            "SELECT COUNT(*) FROM embedding_models WHERE model_key = 'blake2b-512-v1'"
        ).fetchone()[0]
    assert n == 2


def test_model_key_mismatch_raises():
    a = as_embedded([1.0] + [0.0] * 511, "v", model_key="hash", padding_strategy="none")
    b = as_embedded([1.0] + [0.0] * 511, "v", model_key="minilm", padding_strategy="none")
    with pytest.raises(EmbeddingVersionMismatch):
        compare_embeddings(a, b)


def test_toy_and_hash_are_bit_identical_across_calls():
    h = HashEmbedder()
    t = ToySemanticEmbedder()
    phrase = "vehicle stalled at 65 mph"
    assert h.embed(phrase).values == h.embed(phrase).values
    assert t.embed(phrase).values == t.embed(phrase).values


def test_shadow_kill_switch(monkeypatch):
    monkeypatch.setenv("FRONTLINE_EMBEDDING_MODE", "shadow")
    monkeypatch.delenv("FRONTLINE_EMBEDDING_SHADOW_KILL", raising=False)
    reset_embedding_runtime()
    assert shadow_enabled() is True
    monkeypatch.setenv("FRONTLINE_EMBEDDING_SHADOW_KILL", "1")
    assert shadow_kill_switch() is True
    assert shadow_enabled() is False


def test_budget_violations():
    fails = budget_violations({"artifact_mb": 200, "p50_ms": 1, "p99_ms": 2, "ram_mb": 10, "warmup_ms": 10})
    assert any("artifact_mb" in f for f in fails)
    assert budget_violations({"artifact_mb": 10, "p50_ms": 1, "p99_ms": 2, "ram_mb": 10, "warmup_ms": 10}) == []
