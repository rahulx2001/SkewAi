"""Golden-set evaluation — measuring slot accuracy against labeled ground truth.

The golden set is a collection of annotated customer utterances with ground-truth
slot values. It is used to:
1. Measure slot precision/recall per entity type
2. Detect accuracy drift over time
3. Validate that changes improve (or at minimum don't regress) extraction

Format: each golden-set entry is a dict with:
  {
    "turn_id": str,
    "text": str,
    "expected_slots": {"entity_1": "2019", "entity_2": "TOYOTA", ...},
    "annotator": str,
    "difficulty": "easy" | "medium" | "hard",
    "tags": ["negation", "asr_corruption", "homophone", ...],
  }
"""
from __future__ import annotations

import json
import logging
import math
from collections import defaultdict
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)


@dataclass
class SlotMetrics:
    """Per-slot accuracy metrics."""
    slot_name: str
    true_positives: int = 0
    false_positives: int = 0
    false_negatives: int = 0
    true_negatives: int = 0

    @property
    def precision(self) -> float:
        denom = self.true_positives + self.false_positives
        return self.true_positives / denom if denom > 0 else 0.0

    @property
    def recall(self) -> float:
        denom = self.true_positives + self.false_negatives
        return self.true_positives / denom if denom > 0 else 0.0

    @property
    def f1(self) -> float:
        p, r = self.precision, self.recall
        return 2 * p * r / (p + r) if (p + r) > 0 else 0.0

    @property
    def accuracy(self) -> float:
        total = self.true_positives + self.false_positives + self.false_negatives + self.true_negatives
        return (self.true_positives + self.true_negatives) / total if total > 0 else 0.0

    def to_dict(self) -> dict[str, Any]:
        return {
            "slot_name": self.slot_name,
            "precision": round(self.precision, 4),
            "recall": round(self.recall, 4),
            "f1": round(self.f1, 4),
            "accuracy": round(self.accuracy, 4),
            "true_positives": self.true_positives,
            "false_positives": self.false_positives,
            "false_negatives": self.false_negatives,
            "true_negatives": self.true_negatives,
        }


@dataclass
class EvalResult:
    """Full golden-set evaluation result."""
    total_examples: int = 0
    slot_metrics: dict[str, SlotMetrics] = field(default_factory=dict)
    per_tag_metrics: dict[str, dict[str, SlotMetrics]] = field(default_factory=lambda: defaultdict(dict))
    errors: list[dict[str, Any]] = field(default_factory=list)

    @property
    def overall_slot_f1(self) -> float:
        """Macro-average F1 across all slots."""
        if not self.slot_metrics:
            return 0.0
        return sum(m.f1 for m in self.slot_metrics.values()) / len(self.slot_metrics)

    @property
    def overall_slot_precision(self) -> float:
        if not self.slot_metrics:
            return 0.0
        return sum(m.precision for m in self.slot_metrics.values()) / len(self.slot_metrics)

    @property
    def overall_slot_recall(self) -> float:
        if not self.slot_metrics:
            return 0.0
        return sum(m.recall for m in self.slot_metrics.values()) / len(self.slot_metrics)

    def to_dict(self) -> dict[str, Any]:
        return {
            "total_examples": self.total_examples,
            "overall_f1": round(self.overall_slot_f1, 4),
            "overall_precision": round(self.overall_slot_precision, 4),
            "overall_recall": round(self.overall_slot_recall, 4),
            "per_slot": {k: v.to_dict() for k, v in self.slot_metrics.items()},
            "per_tag": {
                tag: {slot: m.to_dict() for slot, m in slots.items()}
                for tag, slots in self.per_tag_metrics.items()
            },
            "error_count": len(self.errors),
        }


def _normalize_slot_value(val: Any) -> str:
    """Normalize a slot value for comparison (strip, upper, handle None)."""
    if val is None or (isinstance(val, str) and not val.strip()):
        return ""
    return str(val).strip().upper()


def evaluate_extraction(
    golden_set: list[dict[str, Any]],
    extractor_fn: Any,
    *,
    slot_names: list[str] | None = None,
) -> EvalResult:
    """Run extractor_fn on each golden-set example and compute metrics.

    Args:
        golden_set: List of annotated examples.
        extractor_fn: Callable(text: str) -> dict[str, str] returning extracted slots.
        slot_names: If provided, only evaluate these slots. Otherwise, derive from golden set.
    """
    if slot_names is None:
        slot_names_set: set[str] = set()
        for ex in golden_set:
            slot_names_set.update(ex.get("expected_slots", {}).keys())
        slot_names = sorted(slot_names_set)

    result = EvalResult(total_examples=len(golden_set))
    for slot in slot_names:
        result.slot_metrics[slot] = SlotMetrics(slot_name=slot)

    for i, example in enumerate(golden_set):
        text = example.get("text", "")
        expected = example.get("expected_slots", {})
        tags = example.get("tags", [])

        try:
            predicted = extractor_fn(text)
        except Exception as e:
            result.errors.append({
                "index": i,
                "turn_id": example.get("turn_id"),
                "error": f"{type(e).__name__}: {e}",
            })
            predicted = {}

        for slot in slot_names:
            expected_val = _normalize_slot_value(expected.get(slot))
            predicted_val = _normalize_slot_value(predicted.get(slot))

            metrics = result.slot_metrics[slot]
            if expected_val and predicted_val:
                if expected_val == predicted_val:
                    metrics.true_positives += 1
                else:
                    metrics.false_positives += 1
                    metrics.false_negatives += 1
            elif expected_val and not predicted_val:
                metrics.false_negatives += 1
            elif not expected_val and predicted_val:
                metrics.false_positives += 1
            else:
                metrics.true_negatives += 1

            # Per-tag tracking
            for tag in tags:
                if tag not in result.per_tag_metrics:
                    result.per_tag_metrics[tag] = {}
                if slot not in result.per_tag_metrics[tag]:
                    result.per_tag_metrics[tag][slot] = SlotMetrics(slot_name=slot)
                tag_metrics = result.per_tag_metrics[tag][slot]
                if expected_val and predicted_val:
                    if expected_val == predicted_val:
                        tag_metrics.true_positives += 1
                    else:
                        tag_metrics.false_positives += 1
                        tag_metrics.false_negatives += 1
                elif expected_val and not predicted_val:
                    tag_metrics.false_negatives += 1
                elif not expected_val and predicted_val:
                    tag_metrics.false_positives += 1
                else:
                    tag_metrics.true_negatives += 1

    return result


def load_golden_set(path: str | Path) -> list[dict[str, Any]]:
    """Load a golden set from a JSON or JSONL file."""
    path = Path(path)
    if not path.exists():
        raise FileNotFoundError(f"Golden set file not found: {path}")
    text = path.read_text(encoding="utf-8")
    if path.suffix == ".jsonl":
        return [json.loads(line) for line in text.splitlines() if line.strip()]
    return json.loads(text)


def compute_inter_annotator_agreement(
    annotations_a: list[dict[str, Any]],
    annotations_b: list[dict[str, Any]],
    *,
    slot_names: list[str] | None = None,
) -> dict[str, Any]:
    """Compute Cohen's kappa between two annotators.

    Each annotation is {turn_id, expected_slots: {slot: value}}.
    Returns per-slot kappa and overall average.
    """
    if len(annotations_a) != len(annotations_b):
        raise ValueError("Annotation sets must have the same length")

    if slot_names is None:
        slot_names_set: set[str] = set()
        for a in annotations_a:
            slot_names_set.update(a.get("expected_slots", {}).keys())
        for b in annotations_b:
            slot_names_set.update(b.get("expected_slots", {}).keys())
        slot_names = sorted(slot_names_set)

    per_slot: dict[str, float] = {}
    for slot in slot_names:
        agree = 0
        total = len(annotations_a)
        # Simple agreement ratio (Cohen's kappa simplification for multi-class)
        vals_a = [_normalize_slot_value(a.get("expected_slots", {}).get(slot)) for a in annotations_a]
        vals_b = [_normalize_slot_value(b.get("expected_slots", {}).get(slot)) for b in annotations_b]

        agree = sum(1 for va, vb in zip(vals_a, vals_b) if va == vb)
        po = agree / total if total > 0 else 0.0

        # Expected agreement (chance)
        from collections import Counter
        all_vals = vals_a + vals_b
        counts = Counter(all_vals)
        n = len(vals_a)
        pe = sum((c / (2 * n)) ** 2 for c in counts.values()) if n > 0 else 0.0

        if abs(1.0 - pe) < 1e-9:
            kappa = 1.0 if po >= 1.0 else 0.0
        else:
            kappa = (po - pe) / (1.0 - pe)

        per_slot[slot] = round(kappa, 4)

    overall = sum(per_slot.values()) / len(per_slot) if per_slot else 0.0
    return {
        "per_slot_kappa": per_slot,
        "overall_kappa": round(overall, 4),
        "n_examples": len(annotations_a),
        "interpretation": (
            "substantial" if overall >= 0.61
            else "moderate" if overall >= 0.41
            else "fair" if overall >= 0.21
            else "slight" if overall >= 0.0
            else "poor"
        ),
    }


def drift_check(
    current: EvalResult,
    baseline: EvalResult,
    *,
    max_f1_drop: float = 0.05,
) -> dict[str, Any]:
    """Compare current eval to baseline; flag regressions."""
    regressions: list[dict[str, Any]] = []
    for slot, cur_m in current.slot_metrics.items():
        base_m = baseline.slot_metrics.get(slot)
        if base_m is None:
            continue
        f1_delta = cur_m.f1 - base_m.f1
        if f1_delta < -max_f1_drop:
            regressions.append({
                "slot": slot,
                "baseline_f1": round(base_m.f1, 4),
                "current_f1": round(cur_m.f1, 4),
                "delta": round(f1_delta, 4),
            })
    return {
        "drifted": len(regressions) > 0,
        "regressions": regressions,
        "overall_f1_baseline": round(baseline.overall_slot_f1, 4),
        "overall_f1_current": round(current.overall_slot_f1, 4),
    }


__all__ = [
    "SlotMetrics",
    "EvalResult",
    "evaluate_extraction",
    "load_golden_set",
    "compute_inter_annotator_agreement",
    "drift_check",
]
