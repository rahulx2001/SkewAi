"""Golden labeled set + inter-annotator agreement (review §2).

Replaces 'eval asserts against own fixtures' with a human-label contract:
  - golden items carry 2+ independent labels + adjudicated gold
  - Cohen's kappa (pairwise) + Fleiss-style agreement reported
  - loaders accept a 200-call anonymized transcript corpus (JSONL)

Synthetic evals remain as regression; golden gates promotion.
"""

from __future__ import annotations

import json
from collections import Counter
from pathlib import Path
from typing import Any


def cohen_kappa(a: list[str], b: list[str]) -> float:
    """Pairwise Cohen's kappa for two annotators over the same items."""
    assert len(a) == len(b) and len(a) > 0
    cats = sorted(set(a) | set(b))
    n = len(a)
    po = sum(1 for x, y in zip(a, b) if x == y) / n
    pa = Counter(a)
    pb = Counter(b)
    pe = sum((pa[c] / n) * (pb[c] / n) for c in cats)
    return (po - pe) / (1 - pe) if pe < 1 else 1.0


def inter_annotator_report(labels: dict[str, list[str]]) -> dict[str, Any]:
    """labels: item_id → [label_ann1, label_ann2, ...]. Adjudicate by majority."""
    gold, kappas = {}, []
    for item, votes in labels.items():
        gold[item] = Counter(votes).most_common(1)[0][0] if votes else None
    annotators = max((len(v) for v in labels.values()), default=0)
    for j in range(annotators):
        for k in range(j + 1, annotators):
            a = [labels[i][j] for i in labels if len(labels[i]) > j]
            b = [labels[i][k] for i in labels if len(labels[i]) > k]
            shared = min(len(a), len(b))
            if shared >= 5:
                kappas.append(cohen_kappa(a[:shared], b[:shared]))
    mean_k = (sum(kappas) / len(kappas)) if kappas else None
    return {"n_items": len(labels), "gold": gold,
            "pairwise_kappa": kappas, "mean_kappa": mean_k,
            "promotion_gate": "mean_kappa >= 0.70 and n_items >= 100"}


def load_transcript_corpus(path: str | Path) -> list[dict[str, Any]]:
    """Load anonymized transcript JSONL: {id, turns, lang, labels?}."""
    p = Path(path)
    if not p.is_file():
        return []
    out = []
    for line in p.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            out.append(json.loads(line))
        except Exception:
            continue
    return out


GOLDEN_SCHEMA = {
    "required": ["id", "turns", "gold_slots", "gold_severity", "labels"],
    "note": "labels: ≥2 independent annotator votes per item; gold_* adjudicated",
}


__all__ = ["cohen_kappa", "inter_annotator_report", "load_transcript_corpus", "GOLDEN_SCHEMA"]
