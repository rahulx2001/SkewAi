"""Model governance — versioning, shadow mode, fairness, calibration.

Closes review §3 (regulatory landmine for CFPB):
  - versioned model artifacts with model cards; stamp model_version everywhere
  - shadow mode: new model runs alongside rules, compare before promotion
  - fairness: severity/priority must not correlate with protected-class proxies
  - explainability hooks: which features drove severity
  - calibration: predicted severity vs eventual outcome

Deterministic + offline. No training here — governance over existing
``src/ml_runtime`` artifacts + pack rule lists.
"""

from __future__ import annotations

import hashlib
import json
import os
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from src.config import REPO_ROOT


# ── Model cards + versioning ──────────────────────────────────────────────

@dataclass
class ModelCard:
    artifact_ref: str
    version: str
    trained_at: str = ""
    pack_id: str = ""
    features: list[str] = field(default_factory=list)
    metrics: dict[str, Any] = field(default_factory=dict)
    limitations: str = ""
    promoted: bool = False


def _cards_dir() -> Path:
    raw = (os.getenv("MODEL_CARDS_DIR") or "").strip()
    p = Path(raw).expanduser() if raw else (REPO_ROOT / "data" / "model_cards")
    return p.resolve() if p.is_absolute() else (REPO_ROOT / p).resolve()


def artifact_version(artifact_ref: str) -> str:
    """Stable version stamp: artifact path + sha12, or rules:<pack_version>."""
    ref = (artifact_ref or "").strip()
    if not ref:
        return "rules:unknown"
    for cand in (Path(ref), REPO_ROOT / ref, REPO_ROOT / "domains" / ref):
        try:
            if cand.is_file():
                h = hashlib.sha256(cand.read_bytes()).hexdigest()[:12]
                return f"{ref}@{h}"
        except OSError:
            continue
    return f"{ref}@unreadable"


def save_model_card(card: ModelCard) -> Path:
    d = _cards_dir()
    d.mkdir(parents=True, exist_ok=True)
    safe = "".join(c if (c.isalnum() or c in "-_.") else "_" for c in card.version)[:80]
    p = d / f"{safe}.json"
    p.write_text(json.dumps(card.__dict__, indent=2, sort_keys=True), encoding="utf-8")
    return p


def load_model_card(version: str) -> ModelCard | None:
    safe = "".join(c if (c.isalnum() or c in "-_.") else "_" for c in version)[:80]
    p = _cards_dir() / f"{safe}.json"
    if not p.is_file():
        return None
    try:
        d = json.loads(p.read_text(encoding="utf-8"))
        return ModelCard(**{k: d.get(k, v) for k, v in ModelCard(d.get("artifact_ref", ""), version). __dict__.items()})
    except Exception:
        return None


# ── Shadow mode ───────────────────────────────────────────────────────────

@dataclass
class ShadowComparison:
    interaction_id: str
    champion: str  # e.g. "rules:abc" — live decision source
    challenger: str  # candidate model version
    champion_severity: str
    challenger_severity: str
    agree: bool
    promote_signal: str  # challenger_agrees | challenger_differs_higher | ..._lower


def compare_shadow(
    *, interaction_id: str, champion: str, challenger: str,
    champion_severity: str, challenger_severity: str,
) -> ShadowComparison:
    order = {"Low": 0, "Medium": 1, "High": 2, "Critical": 3}
    a = order.get(champion_severity, 0)
    b = order.get(challenger_severity, 0)
    if a == b:
        sig = "challenger_agrees"
    elif b > a:
        sig = "challenger_differs_higher"
    else:
        sig = "challenger_differs_lower"
    return ShadowComparison(
        interaction_id=interaction_id, champion=champion, challenger=challenger,
        champion_severity=champion_severity, challenger_severity=challenger_severity,
        agree=(a == b), promote_signal=sig,
    )


# ── Fairness: severity vs protected-class proxies ─────────────────────────
# Pilot rule: severity/priority must not correlate with zip / name proxies.
# We CANNOT see protected class; we test the proxies regulators test.

_PROXY_ZIP_KEYS = ("zip", "zipcode", "postal", "zip_code")
_PROXY_NAME_KEYS = ("name", "surname", "first_name", "last_name")


def _proxy_bucket(case: dict[str, Any]) -> str:
    for k in _PROXY_ZIP_KEYS:
        if case.get(k):
            z = str(case[k]).strip()
            return f"zip:{z[:3]}" if len(z) >= 3 else f"zip:{z}"
    for k in _PROXY_NAME_KEYS:
        if case.get(k):
            n = str(case[k]).strip().lower()
            # crude name-origin proxy bucket (vowel/consonant start) — deliberately
            # weak; real audits use BISG. Flags only gross skew, never clears.
            return "name:vowel" if n[:1] in "aeiou" else "name:consonant"
    return "unknown"


_SEV_ORDER = {"Low": 0, "Medium": 1, "High": 2, "Critical": 3}


def fairness_report(cases: list[dict[str, Any]]) -> dict[str, Any]:
    """Group severity rate by proxy bucket; flag max gap > threshold.

    Returns {buckets, max_gap, flagged, n, note}. Empty input → not flagged,
    insufficient_data (never green-light on zero evidence).
    """
    if not cases:
        return {"n": 0, "buckets": {}, "max_gap": 0.0, "flagged": False,
                "note": "insufficient_data"}
    buckets: dict[str, list[int]] = {}
    for c in cases:
        b = _proxy_bucket(c)
        sev = _SEV_ORDER.get(str(c.get("severity", "Low")), 0)
        buckets.setdefault(b, []).append(1 if sev >= 2 else 0)  # High/Critical rate
    rates = {b: (sum(v) / len(v)) for b, v in buckets.items() if v}
    gap = (max(rates.values()) - min(rates.values())) if len(rates) >= 2 else 0.0
    return {
        "n": len(cases),
        "buckets": {b: {"n": len(buckets[b]), "high_rate": r} for b, r in rates.items()},
        "max_gap": gap,
        "flagged": gap > 0.20 and len(cases) >= 30,
        "note": "proxy-only screen, not a clearance; BISG + human review required pre-promo",
    }


# ── Explainability + calibration ──────────────────────────────────────────

def explain_severity(*, severity: str, source: str, reason: str,
                     safety_flags: dict[str, Any] | None = None,
                     category: str | None = None) -> dict[str, Any]:
    """Which features drove severity — auditor-readable, no LLM."""
    drivers: list[str] = []
    if safety_flags and any(safety_flags.values()):
        drivers.append("safety_flag (P1 floor)")
    if category:
        drivers.append(f"category={category}")
    drivers.append(f"source={source}: {reason}"[:300])
    return {"severity": severity, "drivers": drivers, "source": source}


def calibration_table(
    predictions: list[dict[str, Any]],
) -> dict[str, Any]:
    """Predicted severity vs eventual outcome (reopen / investigation hit).

    Each item: {predicted: Low|Medium|High|Critical, bad_outcome: bool}.
    Small-N buckets report insufficient_data instead of a noisy rate.
    """
    buckets: dict[str, dict[str, int]] = {}
    for p in predictions:
        k = str(p.get("predicted", "Low"))
        b = buckets.setdefault(k, {"n": 0, "bad": 0})
        b["n"] += 1
        if p.get("bad_outcome"):
            b["bad"] += 1
    out = {}
    for k, b in buckets.items():
        if b["n"] < 20:
            out[k] = {**b, "bad_rate": None, "note": "insufficient_data (n<20)"}
        else:
            out[k] = {**b, "bad_rate": b["bad"] / b["n"], "note": "ok"}
    return {"buckets": out, "n": len(predictions),
            "generated_at": datetime.now(timezone.utc).isoformat()}


__all__ = [
    "ModelCard", "artifact_version", "save_model_card", "load_model_card",
    "ShadowComparison", "compare_shadow", "fairness_report",
    "explain_severity", "calibration_table",
]
