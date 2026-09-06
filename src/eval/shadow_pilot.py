"""Shadow Pilot Evaluation Engine — computing the Five Numbers with Confidence Intervals.

The shadow pilot evaluates dual-stream contact traffic by comparing AI extractions,
triage classifications, safety kill-switch triggers, and RCA cluster matches against
human agent ground truth.

Computes the 5 core decision metrics with Wilson score / asymptotic 95% confidence intervals:
  1. Slot accuracy vs. human record (target: >= 90% per critical entity)
  2. Kill-switch precision and recall (target: P >= 0.85, R >= 0.98)
  3. Severity agreement Cohen's kappa (target: kappa >= 0.70)
  4. Cluster agreement with engineer (target: >= 75% top-1)
  5. Cost per contact (telephony + inference blended)

Traffic light evaluation:
  - GREEN: Proceed to controlled live pilot
  - YELLOW: Proceed with humans in the loop
  - RED: Block live pilot; return to engineering
"""

from __future__ import annotations

import math
from collections import Counter
from dataclasses import dataclass, field
from typing import Any


def wilson_score_interval(positives: int, total: int, confidence: float = 0.95) -> tuple[float, float, float]:
    """Compute point estimate and Wilson score 95% confidence interval for a proportion.

    Returns:
        (point_estimate, ci_lower, ci_upper) clamped to [0.0, 1.0].
    """
    if total <= 0:
        return 0.0, 0.0, 0.0
    p = positives / total
    z = 1.95996  # 95% normal critical value
    denom = 1.0 + (z**2) / total
    center = (p + (z**2) / (2.0 * total)) / denom
    spread = z * math.sqrt((p * (1.0 - p) / total) + (z**2) / (4.0 * (total**2))) / denom
    lower = max(0.0, center - spread)
    upper = min(1.0, center + spread)
    return round(p, 4), round(lower, 4), round(upper, 4)


def cohen_kappa_with_ci(rater_a: list[str], rater_b: list[str]) -> tuple[float, float, float]:
    """Compute Cohen's kappa and 95% asymptotic confidence interval.

    Returns:
        (kappa, ci_lower, ci_upper)
    """
    n = len(rater_a)
    if n == 0 or n != len(rater_b):
        return 0.0, 0.0, 0.0

    categories = sorted(list(set(rater_a) | set(rater_b)))
    cat_to_idx = {c: i for i, c in enumerate(categories)}
    k = len(categories)
    if k <= 1:
        return 1.0, 1.0, 1.0

    matrix = [[0] * k for _ in range(k)]
    for a, b in zip(rater_a, rater_b):
        matrix[cat_to_idx[a]][cat_to_idx[b]] += 1

    po = sum(matrix[i][i] for i in range(k)) / n
    row_sums = [sum(matrix[i][j] for j in range(k)) / n for i in range(k)]
    col_sums = [sum(matrix[i][j] for i in range(k)) / n for j in range(k)]
    pe = sum(r * c for r, c in zip(row_sums, col_sums))

    if abs(1.0 - pe) < 1e-9:
        kappa = 1.0 if po >= 1.0 else 0.0
        return kappa, kappa, kappa

    kappa = (po - pe) / (1.0 - pe)

    # Fleiss / Cohen standard error approximation
    var_k = (po * (1.0 - po)) / (n * ((1.0 - pe) ** 2)) if n > 1 else 0.0
    se = math.sqrt(max(0.0, var_k))
    z = 1.95996
    lower = max(-1.0, kappa - z * se)
    upper = min(1.0, kappa + z * se)
    return round(kappa, 4), round(lower, 4), round(upper, 4)


@dataclass
class ShadowContact:
    """A single dual-stream contact record with AI output and human supervisor ground truth."""
    contact_id: str
    # Entity slots
    ai_slots: dict[str, str] = field(default_factory=dict)
    human_slots: dict[str, str] = field(default_factory=dict)
    # Kill switch
    ai_kill_switch_triggered: bool = False
    human_kill_switch_needed: bool = False
    # Triage severity
    ai_severity: str = "Medium"
    human_severity: str = "Medium"
    # Cluster RCA
    ai_cluster_id: int | None = None
    ai_top_3_clusters: list[int] = field(default_factory=list)
    engineer_verified_cluster_id: int | None = None
    # Contact economics
    duration_seconds: float = 120.0
    llm_tokens_used: int = 0
    cost_usd: float = 0.012


@dataclass
class ShadowMetricResult:
    """A single evaluated metric with point estimate, CI, and traffic light rating."""
    name: str
    point_estimate: float
    ci_lower: float
    ci_upper: float
    rating: str  # "green" | "yellow" | "red"
    target: str
    detail: str


class ShadowPilotEvaluator:
    """Evaluates a cohort of dual-stream shadow contacts against gating criteria."""

    def __init__(self, contacts: list[ShadowContact]) -> None:
        self.contacts = contacts

    def evaluate_slot_accuracy(self, critical_entities: tuple[str, ...] = ("entity_1", "entity_2", "entity_3", "category")) -> dict[str, ShadowMetricResult]:
        results = {}
        for ent in critical_entities:
            positives = 0
            total = 0
            for c in self.contacts:
                h_val = (c.human_slots.get(ent) or "").strip().upper()
                if not h_val:
                    continue  # Human didn't record this slot
                total += 1
                ai_val = (c.ai_slots.get(ent) or "").strip().upper()
                if ai_val == h_val:
                    positives += 1

            p, low, up = wilson_score_interval(positives, total)
            rating = "green" if p >= 0.90 else ("yellow" if p >= 0.80 else "red")
            results[ent] = ShadowMetricResult(
                name=f"slot_accuracy_{ent}",
                point_estimate=p,
                ci_lower=low,
                ci_upper=up,
                rating=rating,
                target=">= 0.90",
                detail=f"{positives}/{total} matching human record",
            )
        return results

    def evaluate_kill_switch(self) -> dict[str, ShadowMetricResult]:
        tp = fp = fn = tn = 0
        for c in self.contacts:
            ai_trig = c.ai_kill_switch_triggered
            hu_trig = c.human_kill_switch_needed
            if ai_trig and hu_trig:
                tp += 1
            elif ai_trig and not hu_trig:
                fp += 1
            elif not ai_trig and hu_trig:
                fn += 1
            else:
                tn += 1

        # Precision = TP / (TP + FP)
        prec, p_low, p_up = wilson_score_interval(tp, tp + fp)
        # Recall = TP / (TP + FN)
        rec, r_low, r_up = wilson_score_interval(tp, tp + fn)

        p_rating = "green" if prec >= 0.85 else ("yellow" if prec >= 0.70 else "red")
        r_rating = "green" if rec >= 0.98 else ("yellow" if rec >= 0.95 else "red")

        return {
            "precision": ShadowMetricResult(
                name="kill_switch_precision",
                point_estimate=prec,
                ci_lower=p_low,
                ci_upper=p_up,
                rating=p_rating,
                target=">= 0.85",
                detail=f"TP={tp}, FP={fp}",
            ),
            "recall": ShadowMetricResult(
                name="kill_switch_recall",
                point_estimate=rec,
                ci_lower=r_low,
                ci_upper=r_up,
                rating=r_rating,
                target=">= 0.98",
                detail=f"TP={tp}, FN={fn}",
            ),
        }

    def evaluate_severity_agreement(self) -> ShadowMetricResult:
        pairs = [
            (c.ai_severity, c.human_severity)
            for c in self.contacts
            if (c.human_severity or "").strip()
        ]
        ai_labels = [a for a, _h in pairs]
        hu_labels = [h for _a, h in pairs]
        kappa, low, up = cohen_kappa_with_ci(hu_labels, ai_labels)
        rating = "green" if kappa >= 0.70 else ("yellow" if kappa >= 0.50 else "red")
        return ShadowMetricResult(
            name="severity_agreement_kappa",
            point_estimate=kappa,
            ci_lower=low,
            ci_upper=up,
            rating=rating,
            target="kappa >= 0.70",
            detail=f"Evaluated across {len(pairs)} human supervisor ratings",
        )

    def evaluate_cluster_agreement(self) -> dict[str, ShadowMetricResult]:
        evaluated = [c for c in self.contacts if c.engineer_verified_cluster_id is not None]
        total = len(evaluated)
        top_1_matches = sum(1 for c in evaluated if c.ai_cluster_id == c.engineer_verified_cluster_id)
        top_3_matches = sum(1 for c in evaluated if c.engineer_verified_cluster_id in c.ai_top_3_clusters)

        p1, low1, up1 = wilson_score_interval(top_1_matches, total)
        p3, low3, up3 = wilson_score_interval(top_3_matches, total)

        rating_top1 = "green" if p1 >= 0.75 else ("yellow" if p3 >= 0.75 else "red")

        return {
            "top_1": ShadowMetricResult(
                name="cluster_agreement_top1",
                point_estimate=p1,
                ci_lower=low1,
                ci_upper=up1,
                rating=rating_top1,
                target=">= 0.75 top-1",
                detail=f"{top_1_matches}/{total} agreed with RCA engineer",
            ),
            "top_3": ShadowMetricResult(
                name="cluster_agreement_top3",
                point_estimate=p3,
                ci_lower=low3,
                ci_upper=up3,
                rating="green" if p3 >= 0.85 else "yellow",
                target=">= 0.85 top-3",
                detail=f"{top_3_matches}/{total} engineer clusters in top-3 candidates",
            ),
        }

    def evaluate_cost_per_contact(self, target_margin_usd: float = 0.45) -> ShadowMetricResult:
        costs = [c.cost_usd for c in self.contacts]
        n = len(costs)
        mean_cost = sum(costs) / n if n > 0 else 0.0
        sorted_costs = sorted(costs)
        p95 = sorted_costs[int(0.95 * n)] if n > 0 else 0.0

        if n > 1:
            var = sum((x - mean_cost) ** 2 for x in costs) / (n - 1)
            se = math.sqrt(var / n)
            ci_low = max(0.0, mean_cost - 1.95996 * se)
            ci_up = mean_cost + 1.95996 * se
        else:
            ci_low = mean_cost
            ci_up = mean_cost

        yellow_thresh = max(0.70, target_margin_usd * 1.5)
        rating = "green" if mean_cost <= target_margin_usd else ("yellow" if mean_cost <= yellow_thresh else "red")
        return ShadowMetricResult(
            name="cost_per_contact",
            point_estimate=round(mean_cost, 4),
            ci_lower=round(ci_low, 4),
            ci_upper=round(ci_up, 4),
            rating=rating,
            target=f"<= ${target_margin_usd:.2f}",
            detail=f"Mean=${mean_cost:.4f}, 95% CI=[${ci_low:.4f}, ${ci_up:.4f}], p95=${p95:.4f}",
        )

    def run_full_evaluation(self, target_cost_usd: float = 0.45) -> dict[str, Any]:
        """Run all five shadow evaluations and return complete scorecard."""
        slots = self.evaluate_slot_accuracy()
        ks = self.evaluate_kill_switch()
        sev = self.evaluate_severity_agreement()
        clu = self.evaluate_cluster_agreement()
        cost = self.evaluate_cost_per_contact(target_cost_usd)

        all_ratings = [m.rating for m in list(slots.values()) + list(ks.values()) + [sev, clu["top_1"], cost]]
        if any(r == "red" for r in all_ratings):
            overall = "red"
        elif any(r == "yellow" for r in all_ratings):
            overall = "yellow"
        else:
            overall = "green"

        return {
            "total_contacts": len(self.contacts),
            "overall_verdict": overall,
            "metrics": {
                "slots": {k: v.__dict__ for k, v in slots.items()},
                "kill_switch": {k: v.__dict__ for k, v in ks.items()},
                "severity_agreement": sev.__dict__,
                "cluster_agreement": {k: v.__dict__ for k, v in clu.items()},
                "cost_per_contact": cost.__dict__,
            },
        }


__all__ = [
    "wilson_score_interval",
    "cohen_kappa_with_ci",
    "ShadowContact",
    "ShadowMetricResult",
    "ShadowPilotEvaluator",
]
