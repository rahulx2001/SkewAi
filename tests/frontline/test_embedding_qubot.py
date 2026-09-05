"""Qubot independently flags mixed embedding versions on a fixture action."""

from __future__ import annotations

from src.ml_runtime.embedding_space import HASH_EMBEDDING_VERSION
from src.qubot.auditor import _audit_embedding_versions, _audit_single_action


def test_similarity_layer_blocks_mismatch():
    from src.ml_runtime.embedding_space import EmbeddingVersionMismatch, as_embedded, compare_embeddings

    a = as_embedded([1.0] + [0.0] * 511, HASH_EMBEDDING_VERSION)
    b = as_embedded([1.0] + [0.0] * 511, "all-MiniLM-L6-v2@x:onnx-int8:mean-pool:l2:zeropad512:v1:modelsha256=zz")
    try:
        compare_embeddings(a, b)
        assert False, "expected mismatch"
    except EmbeddingVersionMismatch:
        pass


def test_qubot_flags_malformed_historical_fixture():
    action = {
        "action_id": "act_fixture",
        "agent": "investigator",
        "action_type": "similar_search",
        "input_summary": (
            "keyword='stall' mode=semantic "
            f"emb_q={HASH_EMBEDDING_VERSION} "
            "emb_c=all-MiniLM-L6-v2@abc:onnx-int8:mean-pool:l2:zeropad512:v1:modelsha256=ff "
            "match=performed"
        ),
        "output_summary": "found 3 similar records (semantic)",
        "evidence_ids": [],
    }
    flags = _audit_embedding_versions(action)
    assert any("mismatch" in f for f in flags)
    verdict = _audit_single_action(
        "automotive_nhtsa",
        action,
        {"entity_1": None, "entity_2": None, "entity_3": None, "category": None},
    )
    assert verdict.verdict == "mismatch"


def test_qubot_ignores_hash_era_actions_without_metadata():
    action = {
        "action_id": "act_old",
        "agent": "investigator",
        "action_type": "similar_search",
        "input_summary": "keyword='brake', category=BRAKES, mode=association",
        "output_summary": "found 2 similar records (association)",
        "evidence_ids": [],
    }
    assert _audit_embedding_versions(action) == []
