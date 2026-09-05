"""Human-label store, IAA, and acceptance eligibility. No agent-made labels."""

from __future__ import annotations

import pytest

from src.eval.embedding_gates import acceptance_eligibility, filter_acceptance_rows, load_decision_rules
from src.eval.embedding_labels import (
    KAPPA_MIN,
    adjudicate,
    agreement_report,
    enqueue_unlabeled_item,
    next_unlabeled_item,
    submit_label,
)
from src.eval.pair_construction import chronological_split, validate_positive_pair
from src.ml_runtime.embedding_eval import load_pairs


def test_seed_pairs_are_ineligible_for_acceptance():
    pairs = load_pairs()
    assert pairs
    assert all(p.get("label_source") == "coding_agent_seed" for p in pairs)
    assert all(p.get("acceptance_eligible") is False for p in pairs)
    assert filter_acceptance_rows(pairs) == []


def test_decision_rules_are_pre_registered():
    rules = load_decision_rules()
    assert rules["primary_metric"] == "hard_negative_same_category.precision_at_5"
    assert rules["kappa_min"] == KAPPA_MIN
    assert "coding_agent_seed" in rules["ineligible_label_sources"]


def test_label_roundtrip_and_kappa(reset_ops_db):
    eid = enqueue_unlabeled_item(
        query_text="engine stalled on the highway",
        candidate_text="motor died at freeway speed",
        category="ENGINE",
        entity_2="HONDA",
        entity_3="CR-V",
    )
    item = next_unlabeled_item("human-a")
    assert item and item["eval_id"] == eid
    assert "sim_score" not in item
    submit_label(eval_id=eid, annotator_id="human-a", label="paraphrase_positive")
    submit_label(eval_id=eid, annotator_id="human-b", label="paraphrase_positive")
    agr = agreement_report()
    assert agr["paired_items"] == 1
    para = agr["per_class"]["paraphrase_positive"]
    assert para["annotator_count"] >= 2
    assert para["cohens_kappa"] == pytest.approx(1.0)
    elig = acceptance_eligibility()
    assert elig["acceptance_ready"] is False  # quotas unmet
    assert "paraphrase_positive" in elig["blocked_classes"]


def test_disagreement_needs_third_reviewer(reset_ops_db):
    eid = enqueue_unlabeled_item(query_text="a", candidate_text="b")
    submit_label(eval_id=eid, annotator_id="human-a", label="paraphrase_positive")
    submit_label(eval_id=eid, annotator_id="human-b", label="hard_negative_same_category")
    with pytest.raises(ValueError):
        adjudicate(
            eval_id=eid,
            adjudicator_id="human-a",
            label="paraphrase_positive",
            notes="same person",
        )
    adjudicate(
        eval_id=eid,
        adjudicator_id="human-c",
        label="paraphrase_positive",
        notes="same stall",
    )


def test_rejects_agent_annotator(reset_ops_db):
    eid = enqueue_unlabeled_item(query_text="a", candidate_text="b")
    with pytest.raises(ValueError):
        submit_label(eval_id=eid, annotator_id="agent-coder", label="paraphrase_positive")


def test_category_entity_is_not_a_positive_pair():
    ok, reason = validate_positive_pair(
        {
            "category": "BRAKES",
            "entity_2": "HONDA",
            "entity_3": "CR-V",
            "label_source": "human",
        }
    )
    assert ok is False
    assert reason == "category_entity_insufficient"


def test_chronological_split_does_not_shuffle():
    rows = [
        {"received_at": "2026-01-01", "id": "a"},
        {"received_at": "2026-06-01", "id": "b"},
        {"received_at": "2025-01-01", "id": "c"},
    ]
    train, valid = chronological_split(rows, "2026-03-01")
    assert [r["id"] for r in train] == ["a", "c"]
    assert [r["id"] for r in valid] == ["b"]
