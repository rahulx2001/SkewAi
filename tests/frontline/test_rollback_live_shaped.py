"""Replay contacts, flip embedding mode, roll back, assert no mixed-version cosine."""

from __future__ import annotations

import pytest

from src.ml_runtime.embedding_runtime import reset_embedding_runtime
from src.ml_runtime.embedding_space import HASH_EMBEDDING_VERSION, EmbeddingVersionMismatch, as_embedded, compare_embeddings
from src.ml_runtime.hash_embedder import HashEmbedder
from src.ml_runtime.onnx_embedder import ToySemanticEmbedder


def test_rollback_mode_uses_hash(monkeypatch):
    monkeypatch.setenv("FRONTLINE_EMBEDDING_MODE", "rollback")
    monkeypatch.setenv("FRONTLINE_EMBEDDING_TOY", "1")
    reset_embedding_runtime()
    from src.ml_runtime.embedding_runtime import customer_visible_mode, embedding_mode

    assert embedding_mode() == "rollback"
    assert customer_visible_mode() == "hash"
    h = HashEmbedder()
    a = h.embed("stall")
    b = h.embed("stall")
    assert compare_embeddings(a, b) == pytest.approx(1.0)
    toy = ToySemanticEmbedder()
    with pytest.raises(EmbeddingVersionMismatch):
        compare_embeddings(a, toy.embed("stall"))


@pytest.mark.asyncio
async def test_replay_then_rollback_ledger_valid(
    reset_ops_db, seed_automotive_pack, pack, monkeypatch, orchestrator_factory
):
    monkeypatch.setenv("FRONTLINE_EMBEDDING_MODE", "legacy")
    reset_embedding_runtime()
    orch, _ = orchestrator_factory()
    await orch.start()
    await orch.handle_customer_turn("My 2019 Honda CR-V grinds when I brake.")
    await orch.handle_customer_turn("Nobody is hurt and I'm safe.")
    await orch.handle_customer_turn("Yes, I'm in a safe location.")
    if orch.ctx.slots.get("__confirm_pending__"):
        await orch.handle_customer_turn("Yes, that's right.")
    iid = orch.ctx.interaction_id
    monkeypatch.setenv("FRONTLINE_EMBEDDING_MODE", "shadow")
    monkeypatch.setenv("FRONTLINE_EMBEDDING_TOY", "1")
    reset_embedding_runtime()
    monkeypatch.setenv("FRONTLINE_EMBEDDING_MODE", "rollback")
    reset_embedding_runtime()
    from src.ledger.chain import verify_chain
    from src.ledger.writer import list_actions

    acts = list_actions(iid)
    assert acts
    texts = " ".join(str(a.get("input_summary") or "") for a in acts)
    assert "emb_c=all-MiniLM" not in texts or "emb_q=all-MiniLM" in texts
    result = verify_chain(acts)
    assert result.get("ok") is True, result
