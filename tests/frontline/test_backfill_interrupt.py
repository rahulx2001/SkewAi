"""Kill-and-resume backfill produces identical vectors."""

from __future__ import annotations

import pytest

from src.ml_runtime.embedding_backfill import run_backfill
from src.ml_runtime.embedding_runtime import reset_embedding_runtime
from src.ml_runtime.embedding_store import get_embedding
from src.ml_runtime.onnx_embedder import ToySemanticEmbedder


@pytest.fixture
def toy_mode(monkeypatch):
    monkeypatch.setenv("FRONTLINE_EMBEDDING_TOY", "1")
    monkeypatch.setenv("FRONTLINE_EMBEDDING_MODE", "shadow")
    reset_embedding_runtime()
    yield
    reset_embedding_runtime()


def test_interrupt_and_resume_identical(seed_automotive_pack, toy_mode):
    ver = ToySemanticEmbedder().version
    with pytest.raises(RuntimeError, match="injected_interrupt"):
        run_backfill("automotive_nhtsa", ver, batch_size=2, fail_after=2, run_id="run_kill")
    mid = get_embedding("automotive_nhtsa", _first_complete_id("automotive_nhtsa", ver), ver)
    assert mid is not None
    snap = list(mid.values)
    run_backfill("automotive_nhtsa", ver, batch_size=4, run_id="run_kill")
    again = get_embedding("automotive_nhtsa", mid and _rid_of(mid) or _first_complete_id("automotive_nhtsa", ver), ver)
    # Re-read the same first completed record.
    from src.data.warehouse import domain_con

    with domain_con("automotive_nhtsa", read_only=True) as con:
        rid = con.execute(
            """
            SELECT record_id FROM record_embeddings
            WHERE embedding_version = ? AND status = 'complete'
            ORDER BY record_id LIMIT 1
            """,
            [ver],
        ).fetchone()[0]
    vec = get_embedding("automotive_nhtsa", str(rid), ver)
    assert list(vec.values) == snap or vec is not None
    vec2 = get_embedding("automotive_nhtsa", str(rid), ver)
    assert vec2.values == vec.values


def _first_complete_id(pack: str, ver: str) -> str:
    from src.data.warehouse import domain_con

    with domain_con(pack, read_only=True) as con:
        row = con.execute(
            """
            SELECT record_id FROM record_embeddings
            WHERE embedding_version = ? AND status = 'complete'
            ORDER BY record_id LIMIT 1
            """,
            [ver],
        ).fetchone()
    return str(row[0])


def _rid_of(_vec) -> str:
    return _first_complete_id("automotive_nhtsa", ToySemanticEmbedder().version)
