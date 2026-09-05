"""CPU benchmark for the local ONNX embedder. Not part of the unit suite.

  python -m scripts.embedding_benchmark --out reports/embedding_benchmark.json
"""

from __future__ import annotations

import argparse
import json
import os
import platform
import resource
import statistics
import time
from pathlib import Path

from src.config import REPO_ROOT
from src.ml_runtime.embedding_runtime import semantic_artifact_dir, try_semantic_embedder
from src.ml_runtime.hash_embedder import HashEmbedder
from src.ml_runtime.onnx_embedder import OnnxSemanticEmbedder, ToySemanticEmbedder


TEXTS = [
    "vehicle stalled at 65 mph",
    "engine died on highway at speed",
    "front brake grinding on honda cr-v at low speed",
    "airbag warning light stays on after start",
    "the power window on the driver side will not go up",
    "transmission slipping when accelerating from a stop",
    "customer reports a burning smell near the dashboard",
    "short noisy asr like um the car just kinda died",
]


def _rss_mb() -> float:
    try:
        return resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / (1024 * 1024)
    except Exception:
        return 0.0


def _pct(xs: list[float], p: float) -> float:
    if not xs:
        return 0.0
    ys = sorted(xs)
    k = min(len(ys) - 1, max(0, int(round((p / 100.0) * (len(ys) - 1)))))
    return ys[k]


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--out", default="reports/embedding_benchmark.json")
    p.add_argument("--iters", type=int, default=40)
    p.add_argument("--concurrency", default="20,50,100")
    args = p.parse_args(argv)
    rss0 = _rss_mb()
    t_init0 = time.perf_counter()
    embedder = try_semantic_embedder()
    used = "onnx" if embedder is not None else "toy"
    if embedder is None:
        embedder = ToySemanticEmbedder()
    # Warmup (not counted in warm latency).
    embedder.embed("warmup " + TEXTS[0])
    cold = time.perf_counter() - t_init0
    single: list[float] = []
    for i in range(args.iters):
        t0 = time.perf_counter()
        embedder.embed(TEXTS[i % len(TEXTS)])
        single.append(time.perf_counter() - t0)
    batch_lat: list[float] = []
    for _ in range(max(5, args.iters // 4)):
        t0 = time.perf_counter()
        embedder.embed_many(TEXTS)
        batch_lat.append(time.perf_counter() - t0)
    artifact = semantic_artifact_dir()
    size = 0
    if artifact.is_dir():
        for f in artifact.iterdir():
            if f.is_file():
                size += f.stat().st_size
    h = HashEmbedder()
    ht0 = time.perf_counter()
    for i in range(args.iters):
        h.embed(TEXTS[i % len(TEXTS)])
    hash_s = (time.perf_counter() - ht0) / args.iters
    report = {
        "os": platform.platform(),
        "cpu": platform.processor() or platform.machine(),
        "python": platform.python_version(),
        "provider": used,
        "version": embedder.version,
        "threads": int(os.getenv("FRONTLINE_ONNX_INTRA_THREADS") or "1"),
        "artifact_bytes": size,
        "rss_mb_after_load": round(_rss_mb(), 2),
        "rss_mb_before": round(rss0, 2),
        "cold_init_s": round(cold, 4),
        "warm_single_s": {
            "p50": round(_pct(single, 50), 4),
            "p95": round(_pct(single, 95), 4),
            "p99": round(_pct(single, 99), 4),
            "mean": round(statistics.fmean(single), 4),
        },
        "batch8_s": {
            "p50": round(_pct(batch_lat, 50), 4),
            "p95": round(_pct(batch_lat, 95), 4),
            "mean": round(statistics.fmean(batch_lat), 4) if batch_lat else 0.0,
        },
        "throughput_texts_per_s": round(len(TEXTS) / statistics.fmean(batch_lat), 2) if batch_lat else 0.0,
        "hash_single_mean_s": round(hash_s, 6),
        "iters": args.iters,
        "concurrency": {},
        "note": "Warmup excluded from warm percentiles. No model download time included.",
    }
    from concurrent.futures import ThreadPoolExecutor

    levels = [int(x) for x in str(args.concurrency).split(",") if x.strip()]
    def _one(i: int) -> float:
        t0 = time.perf_counter()
        embedder.embed(TEXTS[i % len(TEXTS)])
        return time.perf_counter() - t0
    for n in levels:
        with ThreadPoolExecutor(max_workers=n) as pool:
            times = list(pool.map(_one, range(n * 2)))
        report["concurrency"][str(n)] = {
            "p99_s": round(_pct(times, 99), 4),
            "rss_mb": round(_rss_mb(), 2),
        }
    out = Path(args.out)
    if not out.is_absolute():
        out = REPO_ROOT / out
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
