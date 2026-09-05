"""Robust statistics, second pass — seasonality, shrinkage, change-point, TZ, fatigue.

Closes review §5:
  - seasonality (weekly/monthly) decomposition before spike detection
  - small-count handling: Bayesian shrinkage / hierarchical pooling
  - change-point detection (sustained shift), not just spike
  - timezone/DST-correct event-clock bucketing
  - alert fatigue budget: cap alerts per engineer per day, rank by expected cost
"""

from __future__ import annotations

import math
from collections import defaultdict
from datetime import datetime, timezone
from typing import Any
from zoneinfo import ZoneInfo


# ── Seasonality decomposition (additive, weekly period=7 / monthly=30) ────

def decompose_seasonal(series: list[float], *, period: int = 7) -> dict[str, Any]:
    n = len(series)
    if n < period * 2:
        return {"method": "insufficient_history", "n": n,
                "seasonal": [0.0] * n, "trend": list(series), "residual": [0.0] * n}
    seasonal = []
    for i in range(n):
        idxs = [j for j in range(n) if j % period == i % period]
        seasonal.append(sum(series[j] for j in idxs) / len(idxs))
    mean = sum(series) / n
    s_mean = sum(seasonal) / n
    seasonal = [s - s_mean for s in seasonal]
    deseasoned = [v - s for v, s in zip(series, seasonal)]
    # centered moving-average trend
    w = min(period, n)
    trend = []
    for i in range(n):
        lo, hi = max(0, i - w // 2), min(n, i + w // 2 + 1)
        trend.append(sum(deseasoned[lo:hi]) / (hi - lo))
    residual = [v - s - t for v, s, t in zip(series, seasonal, trend)]
    return {"method": f"additive_period_{period}", "n": n, "mean": mean,
            "seasonal": seasonal, "trend": trend, "residual": residual}


def spike_on_residual(residual: list[float], *, z: float = 3.0) -> list[int]:
    if len(residual) < 3:
        return []
    m = sum(residual) / len(residual)
    var = sum((v - m) ** 2 for v in residual) / len(residual)
    sd = math.sqrt(var) if var > 0 else 0.0
    if sd == 0:
        return []
    return [i for i, v in enumerate(residual) if (v - m) / sd >= z]


# ── Bayesian shrinkage for small counts ───────────────────────────────────

def shrink_rate(
    successes: int, trials: int, *, prior_alpha: float = 2.0, prior_beta: float = 8.0
) -> dict[str, Any]:
    """Posterior mean with Beta(prior) pooling toward the fleet prior.

    Default prior mean 0.2 (pilot defect-ish base rate); siblings share the
    same prior → hierarchical-ish pooling without MCMC.
    """
    post_a = prior_alpha + successes
    post_b = prior_beta + (trials - successes)
    mean = post_a / (post_a + post_b)
    raw = (successes / trials) if trials else 0.0
    return {"raw_rate": raw, "shrunk_rate": mean, "n": trials,
            "prior": {"alpha": prior_alpha, "beta": prior_beta},
            "shrinkage": abs(raw - mean)}


def pool_siblings(
    counts: dict[str, tuple[int, int]], *, prior_alpha: float = 2.0,
    prior_beta: float = 8.0,
) -> dict[str, dict[str, Any]]:
    return {k: shrink_rate(s, t, prior_alpha=prior_alpha, prior_beta=prior_beta)
            for k, (s, t) in counts.items()}


# ── Change-point (CUSUM-lite for sustained shifts) ────────────────────────

def detect_shift(series: list[float], *, min_run: int = 5, threshold_sd: float = 1.0) -> dict[str, Any]:
    """Sustained mean shift (recalls come from slow drifts, not just spikes)."""
    n = len(series)
    if n < min_run * 2:
        return {"shift": False, "index": None, "note": "insufficient_history", "n": n}
    m = sum(series) / n
    var = sum((v - m) ** 2 for v in series) / n
    sd = math.sqrt(var) if var > 0 else 0.0
    if sd == 0:
        return {"shift": False, "index": None, "note": "no_variance", "n": n}
    best, best_i = 0.0, None
    for i in range(min_run, n - min_run + 1):
        pre = sum(series[:i]) / i
        post = sum(series[i:]) / (n - i)
        gap = abs(post - pre) / sd
        if gap > best:
            best, best_i = gap, i
    return {"shift": best >= threshold_sd, "index": best_i,
            "gap_sd": best, "threshold_sd": threshold_sd, "n": n}


# ── TZ/DST-correct bucketing ──────────────────────────────────────────────

def bucket_by_day(
    events: list[dict[str, Any]], *, tz: str = "America/Chicago",
    ts_key: str = "occurred_at",
) -> dict[str, int]:
    """Bucket event-clock (not worker-clock) by calendar day in source TZ.

    Unparseable/missing timestamps → 'unknown' bucket (counted, never dropped).
    """
    try:
        zone = ZoneInfo(tz)
    except Exception:
        zone = timezone.utc
    out: dict[str, int] = defaultdict(int)
    for e in events:
        raw = e.get(ts_key)
        try:
            dt = datetime.fromisoformat(str(raw).replace("Z", "+00:00"))
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
            out[dt.astimezone(zone).date().isoformat()] += 1
        except Exception:
            out["unknown"] += 1
    return dict(out)


# ── Alert fatigue budget ──────────────────────────────────────────────────

def rank_by_expected_cost(alerts: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Rank by expected cost = p(severe) × cost_per_case × confidence, not p-value."""
    def cost(a: dict[str, Any]) -> float:
        return (float(a.get("p_severe", 0.5)) * float(a.get("cost_per_case", 250.0))
                * float(a.get("confidence", 0.5)))
    return sorted(alerts, key=cost, reverse=True)


def apply_fatigue_budget(
    alerts: list[dict[str, Any]], *, per_engineer_per_day: int = 5,
) -> dict[str, Any]:
    ranked = rank_by_expected_cost(alerts)
    kept = ranked[:max(0, per_engineer_per_day)]
    dropped = ranked[len(kept):]
    return {"kept": kept, "dropped": dropped,
            "budget": per_engineer_per_day,
            "note": f"cap {per_engineer_per_day}/engineer/day; ranked by expected cost"}


__all__ = [
    "decompose_seasonal", "spike_on_residual", "shrink_rate", "pool_siblings",
    "detect_shift", "bucket_by_day", "rank_by_expected_cost", "apply_fatigue_budget",
]
