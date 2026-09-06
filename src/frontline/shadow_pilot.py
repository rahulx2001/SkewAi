"""Shadow Pilot CLI & Execution Harness — Step 0 Dual-Stream Production Validation.

Evaluates AI frontline assistant against human supervisor and engineer ground truth
across the Five Decision Numbers with 95% confidence intervals:
  1. Slot accuracy vs. human record (>= 90% per critical entity, Wilson CI)
  2. Kill-switch precision (>= 0.85) & recall (>= 0.98) (Wilson CI)
  3. Severity agreement Cohen's kappa (>= 0.70, Asymptotic CI)
  4. Cluster agreement with engineer (>= 75% top-1, >= 85% top-3, Wilson CI)
  5. Cost per contact blended (<= $0.45, SE / normal 95% CI)

Usage:
  python3 -m src.frontline.shadow_pilot --mode=batch --sample-size=100 --out=reports/shadow_baseline_01.json
"""

from __future__ import annotations

import argparse
import json
import math
import os
import random
import re
import sys
from pathlib import Path
from typing import Any

from src.eval.shadow_pilot import (
    ShadowContact,
    ShadowMetricResult,
    ShadowPilotEvaluator,
    cohen_kappa_with_ci,
    wilson_score_interval,
)


# ── Synthetic / Replay Automotive Cohort Generator ──────────────────────────

_MAKES_MODELS: dict[str, list[str]] = {
    "HONDA": ["CR-V", "CIVIC", "ACCORD", "PILOT", "ODYSSEY"],
    "TOYOTA": ["CAMRY", "COROLLA", "RAV4", "HIGHLANDER", "TACOMA", "TUNDRA"],
    "FORD": ["F-150", "EXPLORER", "ESCAPE", "MUSTANG", "EDGE"],
    "CHEVROLET": ["SILVERADO", "EQUINOX", "MALIBU", "TAHOE", "TRAVERSE"],
    "NISSAN": ["ROGUE", "ALTIMA", "SENTRA", "PATHFINDER"],
    "JEEP": ["GRAND CHEROKEE", "WRANGLER", "CHEROKEE"],
    "TESLA": ["MODEL 3", "MODEL Y", "MODEL S"],
    "HYUNDAI": ["TUCSON", "SANTA FE", "ELANTRA", "SONATA"],
    "SUBARU": ["OUTBACK", "FORESTER", "CROSSTREK"],
}

_CATEGORIES = [
    "SERVICE BRAKES",
    "ENGINE",
    "AIR BAGS",
    "ELECTRICAL SYSTEM",
    "STEERING",
    "SUSPENSION",
    "POWER TRAIN",
]

_CATEGORY_CLUSTERS: dict[str, int] = {
    "SERVICE BRAKES": 14,
    "AIR BAGS": 22,
    "ELECTRICAL SYSTEM": 31,
    "ENGINE": 40,
    "STEERING": 55,
    "SUSPENSION": 63,
    "POWER TRAIN": 71,
    "VEHICLE SPEED CONTROL": 82,
    "STRUCTURE": 90,
    "EXTERIOR LIGHTING": 95,
    "SEAT BELTS": 98,
    "SEATS": 102,
}

_SYMPTOM_TEMPLATES: dict[str, list[str]] = {
    "SERVICE BRAKES": [
        "severe brake pedal pulsation and grinding noise when coming to a stop",
        "brake pedal went soft and spongy on the highway, required extra stopping distance",
        "high pitched screeching from front brakes whenever lightly pressing pedal",
        "anti-lock braking system light on dashboard and brakes shudder at low speeds",
    ],
    "ENGINE": [
        "check engine light flashing with rough idle and engine misfire under acceleration",
        "engine stalls unexpectedly at stop lights but restarts after several seconds",
        "excessive oil consumption and burning smell coming from under the hood",
        "loud knocking noise from engine bay during cold morning startup",
    ],
    "AIR BAGS": [
        "airbag warning light stays on constantly while driving",
        "passenger airbag light shows off even when adult passenger is seated",
        "airbag indicator flashes intermittently when adjusting driver seat",
    ],
    "ELECTRICAL SYSTEM": [
        "center infotainment screen completely black and instrument cluster flickering",
        "battery drains overnight and vehicle will not crank in the morning",
        "power windows fail to roll up and door lock switches unresponsive",
    ],
    "STEERING": [
        "power steering assist cuts out suddenly while making low speed turns",
        "steering wheel pulls sharply to the right on flat level pavement",
        "stiff steering wheel with whining noise when turning all the way left",
    ],
    "SUSPENSION": [
        "loud clunking and popping noise over road bumps from front suspension",
        "excessive body roll and bouncy ride quality on highway dips",
        "front end vibrations transmitted into vehicle cabin at 65 mph",
    ],
    "POWER TRAIN": [
        "transmission slips and hesitates between second and third gear",
        "harsh shudder and jerking when accelerating from a complete stop",
        "vehicle fails to shift into reverse gear without multiple attempts",
    ],
}

_EMERGENCY_SCENARIOS = [
    ("Thick black smoke and flames pouring out of the engine compartment on the highway!", "Critical", "fire"),
    ("Brakes failed completely at 55 mph and crashed into a guardrail, ambulance was called for passenger injuries.", "Critical", "crash"),
    ("Under-hood fire broke out immediately after parking in driveway, fire department responded.", "Critical", "fire"),
    ("Sudden unintended acceleration caused crash through garage wall, injured driver bleeding.", "Critical", "injury"),
]

_IDIOMATIC_HEDGED_SCENARIOS = [
    ("This diagnostic repair estimate is killing me and almost gave me a heart attack, but my brakes are making a squealing sound.", "Medium"),
    ("I am worried it might catch fire because there is a faint hot smell when heater is running.", "Medium"),
    ("Nobody is hurt and no fire, just a strange clicking noise when turning on headlights.", "Low"),
    ("Driving in rush hour traffic is killing me, I need to schedule routine brake maintenance.", "Low"),
]


def generate_shadow_cohort(sample_size: int = 100, seed: int = 42) -> list[ShadowContact]:
    """Generate a realistic cohort of dual-stream shadow contacts.

    Simulates live customer interactions with ground-truth recorded by human
    supervisors / RCA engineers alongside AI extractions and classifications.
    """
    rng = random.Random(seed)
    contacts: list[ShadowContact] = []

    # Distribution:
    # ~8% true life-safety emergencies (must have 100% recall)
    # ~5% idiomatic/hedged mentions (must NOT trigger kill switch -> high precision)
    # ~87% standard automotive defect contacts
    emergency_indices = set(rng.sample(range(sample_size), k=max(2, int(sample_size * 0.08))))
    remaining_indices = [i for i in range(sample_size) if i not in emergency_indices]
    idiomatic_indices = set(rng.sample(remaining_indices, k=max(2, int(sample_size * 0.05))))

    all_cluster_ids = list(_CATEGORY_CLUSTERS.values())

    for i in range(sample_size):
        contact_id = f"shadow_cnt_{i+1:04d}"
        year = str(rng.randint(2015, 2024))
        make = rng.choice(list(_MAKES_MODELS.keys()))
        model = rng.choice(_MAKES_MODELS[make])
        category = rng.choice(_CATEGORIES)
        eng_cluster = _CATEGORY_CLUSTERS[category]

        # Defaults
        human_kill_needed = False
        ai_kill_triggered = False
        duration = rng.uniform(85.0, 160.0)
        tokens = rng.randint(400, 850)

        # Base human slots
        human_slots = {
            "entity_1": year,
            "entity_2": make,
            "entity_3": model,
            "category": category,
        }

        # AI extraction simulation: ~95% accurate on entities (replicates ASR + phonetic normalizer)
        ai_slots = {}
        for k, v in human_slots.items():
            if rng.random() < 0.95:
                ai_slots[k] = v
            else:
                # Slight phonetic or extraction miss in small % of contacts
                if k == "entity_1":
                    ai_slots[k] = str(int(v) - 1)
                elif k == "entity_2":
                    ai_slots[k] = "HONDA" if v != "HONDA" else "TOYOTA"
                elif k == "entity_3":
                    ai_slots[k] = "CR-V" if v != "CR-V" else "CIVIC"
                else:
                    ai_slots[k] = "ENGINE" if v != "ENGINE" else "SERVICE BRAKES"

        if i in emergency_indices:
            # True emergency
            text, sev, kill_term = rng.choice(_EMERGENCY_SCENARIOS)
            human_kill_needed = True
            ai_kill_triggered = True  # High recall on true safety
            human_sev = "Critical"
            ai_sev = "Critical"
            category = "ENGINE" if "fire" in kill_term else "SERVICE BRAKES"
            human_slots["category"] = category
            ai_slots["category"] = category
            eng_cluster = _CATEGORY_CLUSTERS[category]
        elif i in idiomatic_indices:
            # Idiomatic mention — should NOT trigger kill switch
            text, sev = rng.choice(_IDIOMATIC_HEDGED_SCENARIOS)
            human_kill_needed = False
            # Negation/hedging suppression correctly handles 95%+ of idiomatic turns
            ai_kill_triggered = False
            human_sev = sev
            ai_sev = sev
        else:
            # Standard defect contact
            symptoms = _SYMPTOM_TEMPLATES[category]
            text = rng.choice(symptoms)
            human_kill_needed = False
            ai_kill_triggered = False

            # Severity assignment
            if category in ("SERVICE BRAKES", "STEERING"):
                human_sev = "High" if rng.random() < 0.75 else "Medium"
            elif category in ("ENGINE", "AIR BAGS"):
                human_sev = "High" if rng.random() < 0.60 else "Medium"
            else:
                human_sev = "Medium" if rng.random() < 0.80 else "Low"

            # AI severity prediction (kappa ~ 0.75-0.85)
            if rng.random() < 0.88:
                ai_sev = human_sev
            else:
                sev_scale = ["Critical", "High", "Medium", "Low"]
                idx = sev_scale.index(human_sev)
                shift = rng.choice([-1, 1])
                ai_sev = sev_scale[max(0, min(3, idx + shift))]

        # Cluster prediction:
        # Top-1 accuracy ~ 80%, Top-3 accuracy ~ 93%
        other_clusters = [c for c in all_cluster_ids if c != eng_cluster]
        if rng.random() < 0.80:
            ai_cluster_id = eng_cluster
            ai_top_3 = [eng_cluster] + rng.sample(other_clusters, 2)
        elif rng.random() < 0.70:
            # Top-3 hit (not top-1)
            distractor = rng.choice(other_clusters)
            ai_cluster_id = distractor
            remaining = [c for c in other_clusters if c != distractor]
            ai_top_3 = [distractor, eng_cluster] + rng.sample(remaining, 1)
        else:
            # Complete miss
            sample_miss = rng.sample(other_clusters, min(3, len(other_clusters)))
            ai_cluster_id = sample_miss[0]
            ai_top_3 = sample_miss

        # Blended unit cost:
        # Telephony: $0.0085/min * duration/60
        # Deepgram ASR: $0.0043/min * duration/60
        # TTS: $0.009
        # LLM (Gemini Flash fast-path): ~$0.00015 / 1k tokens
        telephony_cost = (0.0085 + 0.0043) * (duration / 60.0)
        tts_cost = 0.009
        llm_cost = (tokens / 1000.0) * 0.015
        total_cost = round(telephony_cost + tts_cost + llm_cost, 4)

        contacts.append(
            ShadowContact(
                contact_id=contact_id,
                ai_slots=ai_slots,
                human_slots=human_slots,
                ai_kill_switch_triggered=ai_kill_triggered,
                human_kill_switch_needed=human_kill_needed,
                ai_severity=ai_sev,
                human_severity=human_sev,
                ai_cluster_id=ai_cluster_id,
                ai_top_3_clusters=ai_top_3,
                engineer_verified_cluster_id=eng_cluster,
                duration_seconds=round(duration, 1),
                llm_tokens_used=tokens,
                cost_usd=total_cost,
            )
        )

    return contacts


def load_empirical_cohort(
    input_path: str,
    pack_id: str = "automotive_nhtsa",
    sample_size: int | None = None,
) -> list[ShadowContact]:
    """Load empirical contacts from an authentic JSONL/JSON recorded transcript corpus.

    Evaluates live NLP extraction, safety hazard detection, severity mapping,
    and cluster assignment against human ground truth.
    """
    from src.domains.loader import load_pack
    from src.agents.base import InteractionContext
    from src.agents.intake import (
        _check_kill_switch,
        _extract_year,
        _extract_via_gazetteer,
        _CATEGORY_SYNONYMS,
    )

    p = Path(input_path)
    if not p.exists():
        raise FileNotFoundError(f"Empirical corpus file not found: {input_path}")

    pack = load_pack(pack_id)
    ctx = InteractionContext(interaction_id="shadow_eval", pack=pack)

    lines = [line.strip() for line in p.read_text(encoding="utf-8").splitlines() if line.strip()]
    if sample_size and sample_size < len(lines):
        lines = lines[:sample_size]

    contacts: list[ShadowContact] = []
    all_cluster_ids = list(_CATEGORY_CLUSTERS.values())

    for i, line in enumerate(lines):
        record = json.loads(line)
        contact_id = record.get("id", f"empirical_cnt_{i+1:04d}")
        text = record.get("text", "")

        # Ground truth slots
        human_slots = {
            "entity_1": str(record.get("entity_1", "")),
            "entity_2": str(record.get("entity_2", "")),
            "entity_3": str(record.get("entity_3", "")),
            "category": str(record.get("category", "")),
        }
        human_kill_needed = bool(record.get("expected_safety", record.get("human_kill_needed", False)))
        # F-010: never invent supervisor/engineer labels from the same rules the AI uses.
        human_sev = (record.get("human_severity") or "").strip()
        eng_cluster = record.get("engineer_cluster_id")
        if eng_cluster is None:
            eng_cluster = record.get("engineer_verified_cluster_id")
        if isinstance(eng_cluster, str) and str(eng_cluster).isdigit():
            eng_cluster = int(eng_cluster)
        elif eng_cluster is not None:
            try:
                eng_cluster = int(eng_cluster)
            except (TypeError, ValueError):
                eng_cluster = None

        # AI Extraction
        ai_slots: dict[str, str] = {}
        y = _extract_year(text, (1990, 2026))
        if y:
            ai_slots["entity_1"] = y
        m = _extract_via_gazetteer(text, ctx, "entity_2")
        if m:
            ai_slots["entity_2"] = m
        mod = _extract_via_gazetteer(text, ctx, "entity_3")
        if mod:
            ai_slots["entity_3"] = mod

        # Category extraction
        matched_cat = None
        for syn, cat_val in _CATEGORY_SYNONYMS.items():
            if re.search(rf"\b{re.escape(syn)}\b", text.lower()):
                matched_cat = cat_val
                break
        if not matched_cat:
            matched_cat = _extract_via_gazetteer(text, ctx, "category")
        if not matched_cat:
            # Residual NHTSA class when no specific system is named. Not a
            # ground-truth copy: unmatched text is UNKNOWN OR OTHER.
            matched_cat = "UNKNOWN OR OTHER"
        if matched_cat:
            ai_slots["category"] = matched_cat
        # F-009: do not copy human/ground-truth category into the AI prediction.

        # AI Kill Switch
        matched_term = _check_kill_switch(text, ctx)
        ai_kill_triggered = (matched_term is not None)

        # AI Severity
        if ai_kill_triggered:
            ai_sev = "Critical"
        elif ai_slots.get("category") in ("SERVICE BRAKES", "STEERING", "VEHICLE SPEED CONTROL"):
            ai_sev = "High"
        else:
            ai_sev = "Medium"

        # AI Cluster — from extracted category only; never the engineer label.
        ai_cat = ai_slots.get("category") or ""
        ai_cluster_id = _CATEGORY_CLUSTERS.get(ai_cat) if ai_cat else None
        other_clusters = [c for c in all_cluster_ids if c != ai_cluster_id]
        ai_top_3 = [ai_cluster_id] + other_clusters[:2]

        # Duration & cost modeling
        words = len(text.split())
        duration = max(45.0, min(180.0, words * 1.8))
        tokens = int(words * 4.5 + 250)
        telephony_cost = (0.0085 + 0.0043) * (duration / 60.0)
        tts_cost = 0.009
        llm_cost = (tokens / 1000.0) * 0.015
        total_cost = round(telephony_cost + tts_cost + llm_cost, 4)

        contacts.append(
            ShadowContact(
                contact_id=contact_id,
                ai_slots=ai_slots,
                human_slots=human_slots,
                ai_kill_switch_triggered=ai_kill_triggered,
                human_kill_switch_needed=human_kill_needed,
                ai_severity=ai_sev,
                human_severity=human_sev,
                ai_cluster_id=ai_cluster_id,
                ai_top_3_clusters=ai_top_3,
                engineer_verified_cluster_id=eng_cluster,
                duration_seconds=round(duration, 1),
                llm_tokens_used=tokens,
                cost_usd=total_cost,
            )
        )

    return contacts


def format_scorecard_table(report: dict[str, Any], target_cost_usd: float = 0.45) -> str:
    """Render an ANSI text scorecard table suitable for console and log output."""
    m = report.get("metrics", {})
    slots = m.get("slots", {})
    ks = m.get("kill_switch", {})
    sev = m.get("severity_agreement", {})
    clu = m.get("cluster_agreement", {})
    cost = m.get("cost_per_contact", {})

    meta = report.get("meta", {})
    data_source = meta.get("data_source", "synthetic_monte_carlo")
    source_type = meta.get("source_type", "offline_synthetic").upper()

    lines: list[str] = []
    w = 88
    lines.append("=" * w)
    lines.append("                  SHADOW PILOT EVALUATION SCORECARD (STEP 0)")
    lines.append("=" * w)
    lines.append(f"Cohort Size: {report.get('total_contacts')} contacts | Pack: {meta.get('pack_id', 'automotive_nhtsa')} | Target Cost: <= ${target_cost_usd:.2f}")
    lines.append(f"Data Source: {data_source} [{source_type}]")
    lines.append("-" * w)
    lines.append(f"{'Metric':<34} {'Estimate':<10} {'95% CI':<20} {'Target':<14} {'Rating'}")
    lines.append("-" * w)

    # Slots
    for k, v in slots.items():
        name = f"Slot: {k}"
        est = f"{v['point_estimate']:.4f}"
        ci = f"[{v['ci_lower']:.4f}, {v['ci_upper']:.4f}]"
        rating = f"[{v['rating'].upper()}]"
        lines.append(f"{name:<34} {est:<10} {ci:<20} {v['target']:<14} {rating}")

    # Kill switch
    for k, v in ks.items():
        name = f"Kill-Switch {k.capitalize()}"
        est = f"{v['point_estimate']:.4f}"
        ci = f"[{v['ci_lower']:.4f}, {v['ci_upper']:.4f}]"
        rating = f"[{v['rating'].upper()}]"
        lines.append(f"{name:<34} {est:<10} {ci:<20} {v['target']:<14} {rating}")

    # Severity
    est_sev = f"{sev['point_estimate']:.4f}"
    ci_sev = f"[{sev['ci_lower']:.4f}, {sev['ci_upper']:.4f}]"
    rating_sev = f"[{sev['rating'].upper()}]"
    lines.append(f"{'Severity Agreement (Kappa)':<34} {est_sev:<10} {ci_sev:<20} {sev['target']:<14} {rating_sev}")

    # Cluster
    for k, v in clu.items():
        name = f"Cluster Agreement ({k})"
        est = f"{v['point_estimate']:.4f}"
        ci = f"[{v['ci_lower']:.4f}, {v['ci_upper']:.4f}]"
        rating = f"[{v['rating'].upper()}]"
        lines.append(f"{name:<34} {est:<10} {ci:<20} {v['target']:<14} {rating}")

    # Cost
    est_cost = f"${cost['point_estimate']:.4f}"
    ci_cost = f"[${cost['ci_lower']:.4f}, ${cost['ci_upper']:.4f}]"
    rating_cost = f"[{cost['rating'].upper()}]"
    lines.append(f"{'Unit Cost per Contact':<34} {est_cost:<10} {ci_cost:<20} {cost['target']:<14} {rating_cost}")

    lines.append("-" * w)
    verdict = report.get("overall_verdict", "UNKNOWN").upper()
    status_note = {
        "GREEN": "PROCEED — System meets all statistical thresholds for Phase 1 Live Pilot (5% traffic)",
        "YELLOW": "HUMAN IN LOOP — Proceed with mandatory supervisor sign-off on flagged entities",
        "RED": "BLOCKED — Do not route live customer calls; address regressions in engineering",
        "BLOCKED": "BLOCKED — Independent human labels missing or metrics below gate",
    }.get(verdict, "")
    lines.append(f"OVERALL PILOT VERDICT: [{verdict}] — {status_note}")
    lines.append("=" * w)
    return "\n".join(lines)


def run_shadow_pilot(
    mode: str = "batch",
    sample_size: int = 100,
    out_path: str = "reports/shadow_baseline_01.json",
    pack_id: str = "automotive_nhtsa",
    target_cost: float = 0.45,
    seed: int = 42,
    input_path: str | None = None,
) -> dict[str, Any]:
    """Run shadow pilot evaluation and write JSON report to disk."""
    if mode == "live" and not input_path:
        raise ValueError(
            "--mode=live requires --input with labeled contacts; "
            "refusing Monte Carlo as live evidence"
        )
    if input_path:
        contacts = load_empirical_cohort(input_path, pack_id=pack_id, sample_size=sample_size)
    else:
        contacts = generate_shadow_cohort(sample_size=sample_size, seed=seed)

    evaluator = ShadowPilotEvaluator(contacts)
    report = evaluator.run_full_evaluation(target_cost_usd=target_cost)

    report["meta"] = {
        "mode": mode,
        "pack_id": pack_id,
        "sample_size": len(contacts),
        "seed": seed,
        "target_cost_usd": target_cost,
        "data_source": input_path if input_path else "synthetic_monte_carlo",
        "source_type": "empirical_ground_truth" if input_path else "offline_synthetic",
        "synthetic_self_labels": not bool(input_path),
    }

    # Write output report
    if out_path:
        p = Path(out_path)
        p.parent.mkdir(parents=True, exist_ok=True)
        with open(p, "w", encoding="utf-8") as f:
            json.dump(report, f, indent=2)

    return report


def main() -> int:
    parser = argparse.ArgumentParser(description="Frontline Shadow Pilot Validation Runner")
    parser.add_argument("--mode", choices=["batch", "replay", "live"], default="batch", help="Shadow execution mode")
    parser.add_argument("--sample-size", type=int, default=100, help="Number of dual-stream contacts to evaluate")
    parser.add_argument("--out", type=str, default="reports/shadow_baseline_01.json", help="Path to write JSON evaluation scorecard")
    parser.add_argument("--pack", type=str, default="automotive_nhtsa", help="Domain pack identifier")
    parser.add_argument("--target-cost", type=float, default=0.45, help="Maximum target unit cost per contact (USD)")
    parser.add_argument("--seed", type=int, default=42, help="Random seed for repeatable evaluation")
    parser.add_argument("--input", type=str, default=None, help="Path to empirical JSONL transcript corpus")

    args = parser.parse_args()

    report = run_shadow_pilot(
        mode=args.mode,
        sample_size=args.sample_size,
        out_path=args.out,
        pack_id=args.pack,
        target_cost=args.target_cost,
        seed=args.seed,
        input_path=args.input,
    )

    table = format_scorecard_table(report, target_cost_usd=args.target_cost)
    print(table)

    verdict = report.get("overall_verdict")
    return 0 if verdict in ("green", "yellow") else 1


if __name__ == "__main__":
    sys.exit(main())
