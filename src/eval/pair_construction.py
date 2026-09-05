"""Positive-pair construction rules for a future fine-tune.

Same category + entity is never sufficient. This module only validates
proposed pairs; it does not create them.
"""

from __future__ import annotations

from typing import Any


def validate_positive_pair(row: dict[str, Any]) -> tuple[bool, str]:
    """Return (ok, reason). Never infers a label from category/entity."""
    if row.get("label_source") in {"coding_agent_seed", "author_seed", "synthetic", "agent_proposed"}:
        return False, "ineligible_label_source"
    same_inv = bool(row.get("investigation_id")) and row.get("same_investigation") is True
    human_rca = bool(row.get("human_confirmed_same_root_cause"))
    two_reviewers = (
        row.get("adjudication_status") in {"agreed", "adjudicated"}
        and row.get("annotator_count", 0) >= 2
        and row.get("eval_class") == "paraphrase_positive"
    )
    if same_inv and human_rca:
        return True, "investigation_and_human_rca"
    if two_reviewers:
        return True, "dual_annotation"
    if row.get("category") and row.get("entity_2") and row.get("entity_3"):
        if not (same_inv and human_rca) and not two_reviewers:
            return False, "category_entity_insufficient"
    return False, "missing_root_cause_evidence"


def chronological_split(
    rows: list[dict[str, Any]], cutoff_iso: str
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Train = received_at < cutoff. Validate = received_at >= cutoff. No shuffle."""
    train, valid = [], []
    for r in rows:
        ts = str(r.get("received_at") or r.get("created_at") or "")
        if not ts:
            continue
        if ts < cutoff_iso:
            train.append(r)
        else:
            valid.append(r)
    return train, valid
