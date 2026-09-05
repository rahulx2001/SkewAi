"""Embedding rollout modes, provider factory, and startup validation.

Modes (FRONTLINE_EMBEDDING_MODE):
  legacy   — hash embedder is active; ONNX artifact is not required (default)
  shadow   — hash remains customer-visible; semantic vectors stored in parallel
  semantic — semantic vectors + matching cluster build are active
  rollback — hash reactivated; semantic sidecar data is retained

Deploying this code does not change production behavior: default is legacy.
"""

from __future__ import annotations

import logging
import os
from pathlib import Path
from typing import Any

from src.config import REPO_ROOT
from src.ml_runtime.embedding_space import (
    HASH_EMBEDDING_VERSION,
    OUTPUT_DIMENSION,
    ArtifactIntegrityError,
    Embedder,
    EmbeddingUnavailableError,
)
from src.ml_runtime.hash_embedder import HashEmbedder

logger = logging.getLogger(__name__)

MODES = frozenset({"legacy", "shadow", "semantic", "rollback"})
PRODUCTION_SEMANTIC_PREFIX = "all-MiniLM-L6-v2@"

_HASH = HashEmbedder()
_SEMANTIC: Embedder | None = None
_SEMANTIC_ERROR: str | None = None


def embedding_mode() -> str:
    raw = (os.getenv("FRONTLINE_EMBEDDING_MODE") or "legacy").strip().lower()
    if raw not in MODES:
        raise ValueError(
            f"FRONTLINE_EMBEDDING_MODE={raw!r} is not one of {sorted(MODES)}"
        )
    return raw


def customer_visible_mode() -> str:
    """Provider whose results may change cases / novelty / investigations."""
    mode = embedding_mode()
    if mode == "semantic":
        return "semantic"
    return "hash"  # legacy, shadow, rollback


def shadow_kill_switch() -> bool:
    """Independent of primary path. Stops shadow generation only."""
    return os.getenv("FRONTLINE_EMBEDDING_SHADOW_KILL", "").strip().lower() in {
        "1",
        "true",
        "yes",
        "on",
    }


def shadow_enabled() -> bool:
    if shadow_kill_switch():
        return False
    if embedding_mode() == "shadow":
        return True
    return os.getenv("FRONTLINE_EMBEDDING_SHADOW", "").strip().lower() in {
        "1",
        "true",
        "yes",
        "on",
    }


def semantic_artifact_dir() -> Path:
    raw = (os.getenv("FRONTLINE_SEMANTIC_ARTIFACT_DIR") or "models/minilm").strip()
    p = Path(raw).expanduser()
    return p.resolve() if p.is_absolute() else (REPO_ROOT / p).resolve()


def expected_manifest_sha() -> str:
    return (os.getenv("FRONTLINE_SEMANTIC_MODEL_SHA256") or "").strip().lower()


def active_cluster_build_id() -> str:
    return (os.getenv("FRONTLINE_ACTIVE_CLUSTER_BUILD_ID") or "").strip()


def backfill_batch_size() -> int:
    try:
        return max(1, int(os.getenv("FRONTLINE_EMBEDDING_BACKFILL_BATCH") or "32"))
    except ValueError:
        return 32


def inference_timeout_s() -> float:
    try:
        return max(0.1, float(os.getenv("FRONTLINE_EMBEDDING_TIMEOUT_S") or "8"))
    except ValueError:
        return 8.0


def onnx_intra_threads() -> int:
    try:
        return max(1, int(os.getenv("FRONTLINE_ONNX_INTRA_THREADS") or "1"))
    except ValueError:
        return 1


def resource_budget() -> dict[str, float]:
    def _f(name: str, default: float) -> float:
        try:
            return float(os.getenv(name) or default)
        except ValueError:
            return default

    return {
        "max_artifact_mb": _f("FRONTLINE_EMBED_MAX_ARTIFACT_MB", 80.0),
        "max_ram_after_warmup_mb": _f("FRONTLINE_EMBED_MAX_RAM_MB", 512.0),
        "p50_inference_ms": _f("FRONTLINE_EMBED_P50_MS", 15.0),
        "p99_inference_ms": _f("FRONTLINE_EMBED_P99_MS", 50.0),
        "warmup_ms": _f("FRONTLINE_EMBED_WARMUP_MS", 2000.0),
    }


def budget_violations(measured: dict[str, float]) -> list[str]:
    budget = resource_budget()
    fails: list[str] = []
    mapping = {
        "artifact_mb": "max_artifact_mb",
        "ram_mb": "max_ram_after_warmup_mb",
        "p50_ms": "p50_inference_ms",
        "p99_ms": "p99_inference_ms",
        "warmup_ms": "warmup_ms",
    }
    for mk, bk in mapping.items():
        if mk in measured and measured[mk] > budget[bk]:
            fails.append(f"{mk} {measured[mk]} exceeds budget {budget[bk]}")
    return fails


def hash_embedder() -> HashEmbedder:
    return _HASH


def _load_semantic() -> Embedder:
    global _SEMANTIC, _SEMANTIC_ERROR
    if _SEMANTIC is not None:
        return _SEMANTIC
    if os.getenv("FRONTLINE_EMBEDDING_TOY", "").strip() in {"1", "true", "yes"}:
        from src.ml_runtime.onnx_embedder import ToySemanticEmbedder

        _SEMANTIC = ToySemanticEmbedder()
        _SEMANTIC_ERROR = None
        return _SEMANTIC
    from src.ml_runtime.onnx_embedder import get_process_onnx_embedder

    try:
        embedder = get_process_onnx_embedder(
            semantic_artifact_dir(),
            intra_op_threads=onnx_intra_threads(),
            max_batch_size=backfill_batch_size(),
        )
        expected = expected_manifest_sha()
        meta = embedder.artifact_metadata()
        if expected and meta and meta.model_sha256.lower() != expected:
            raise ArtifactIntegrityError(
                "configured FRONTLINE_SEMANTIC_MODEL_SHA256 does not match artifact"
            )
        _SEMANTIC = embedder
        _SEMANTIC_ERROR = None
        return embedder
    except Exception as e:
        _SEMANTIC_ERROR = f"{type(e).__name__}: {e}"
        raise


def semantic_embedder() -> Embedder:
    return _load_semantic()


def try_semantic_embedder() -> Embedder | None:
    try:
        return _load_semantic()
    except Exception as e:
        logger.warning("semantic embedder unavailable: %s", type(e).__name__)
        return None


def active_embedder() -> Embedder:
    if customer_visible_mode() == "semantic":
        return semantic_embedder()
    return hash_embedder()


def active_embedding_version() -> str:
    if customer_visible_mode() == "semantic":
        try:
            return semantic_embedder().version
        except Exception:
            raise EmbeddingUnavailableError(
                "semantic mode is active but the embedder is not ready"
            )
    return HASH_EMBEDDING_VERSION


def reset_embedding_runtime() -> None:
    """Drop cached semantic provider (tests)."""
    global _SEMANTIC, _SEMANTIC_ERROR
    _SEMANTIC = None
    _SEMANTIC_ERROR = None
    try:
        from src.ml_runtime.onnx_embedder import reset_process_onnx_embedder

        reset_process_onnx_embedder()
    except Exception:
        pass


def validate_startup_config() -> dict[str, Any]:
    """Reject incompatible active embedding / cluster-build pairs.

    Legacy and rollback do not require an artifact. Semantic mode fails closed
    unless the artifact loads and (when a cluster build id is set) the build
    declares the same embedding version. Partial backfill cannot become active
    unless FRONTLINE_EMBEDDING_ALLOW_PARTIAL=1.
    """
    mode = embedding_mode()
    report: dict[str, Any] = {
        "mode": mode,
        "visible": customer_visible_mode(),
        "hash_version": HASH_EMBEDDING_VERSION,
        "output_dimension": OUTPUT_DIMENSION,
        "ok": True,
        "errors": [],
    }
    if mode in {"legacy", "rollback"}:
        report["semantic_required"] = False
        return report
    report["semantic_required"] = mode == "semantic"
    try:
        sem = _load_semantic()
        report["semantic_version"] = sem.version
        report["semantic_ready"] = True
        if not sem.version.startswith(PRODUCTION_SEMANTIC_PREFIX) and not os.getenv(
            "FRONTLINE_EMBEDDING_TOY"
        ):
            report["errors"].append("semantic version is not a registered MiniLM revision")
    except Exception as e:
        report["semantic_ready"] = False
        report["semantic_error"] = type(e).__name__
        if mode == "semantic":
            report["errors"].append(f"semantic embedder unavailable: {type(e).__name__}")
        # shadow: hash remains visible; semantic matching is skipped per-call
    build_id = active_cluster_build_id()
    report["active_cluster_build_id"] = build_id or None
    if mode == "semantic":
        if not build_id:
            report["errors"].append(
                "FRONTLINE_ACTIVE_CLUSTER_BUILD_ID is required in semantic mode"
            )
        elif report.get("semantic_ready"):
            try:
                from src.ml_runtime.cluster_builds import load_cluster_build

                pack = os.getenv("DOMAIN_PACK") or "automotive_nhtsa"
                build = load_cluster_build(pack, build_id)
                if build is None:
                    report["errors"].append("active cluster build not found")
                elif build.get("embedding_version") != report.get("semantic_version"):
                    report["errors"].append(
                        "active cluster build embedding_version does not match the semantic embedder"
                    )
            except Exception as e:
                report["errors"].append(f"cluster build inspect failed: {type(e).__name__}")
        allow_partial = os.getenv("FRONTLINE_EMBEDDING_ALLOW_PARTIAL", "").strip() in {
            "1",
            "true",
            "yes",
        }
        if not allow_partial and report.get("semantic_ready"):
            try:
                from src.ml_runtime.embedding_store import coverage_for_version
                from src.config import settings as _settings

                cov = coverage_for_version(_settings.domain_pack, report["semantic_version"])
                report["coverage"] = cov
                if cov.get("eligible", 0) and cov.get("complete", 0) < cov.get("eligible", 0):
                    report["errors"].append(
                        "semantic backfill is incomplete; refuse activation "
                        "(set FRONTLINE_EMBEDDING_ALLOW_PARTIAL=1 to override)"
                    )
            except Exception as e:
                report["errors"].append(f"coverage inspect failed: {type(e).__name__}")
    if report["errors"]:
        report["ok"] = False
        if mode == "semantic":
            raise EmbeddingUnavailableError("; ".join(report["errors"]))
    return report


def health_payload() -> dict[str, Any]:
    """Safe diagnostics: no complaint text, no secret paths."""
    mode = embedding_mode()
    payload: dict[str, Any] = {
        "mode": mode,
        "visible_provider": customer_visible_mode(),
        "hash_version": HASH_EMBEDDING_VERSION,
        "shadow": shadow_enabled(),
        "shadow_killed": shadow_kill_switch(),
        "artifact_configured": bool(
            os.getenv("FRONTLINE_SEMANTIC_ARTIFACT_DIR") or (REPO_ROOT / "models" / "minilm").is_dir()
        ),
        "active_cluster_build_id": active_cluster_build_id() or None,
    }
    if mode in {"shadow", "semantic"}:
        try:
            sem = try_semantic_embedder()
            if sem is None:
                payload["semantic_ready"] = False
                payload["semantic_error"] = _SEMANTIC_ERROR or "unavailable"
            else:
                payload["semantic_ready"] = bool(sem.ready())
                payload["semantic_version"] = sem.version
                meta = sem.artifact_metadata()
                if meta:
                    payload["model_family"] = meta.model_family
                    payload["quantization"] = meta.quantization
                    payload["native_dimension"] = meta.native_dimension
                    payload["output_dimension"] = meta.output_dimension
                    payload["max_seq_length"] = meta.max_seq_length
                    payload["model_sha256_prefix"] = (meta.model_sha256 or "")[:12]
        except Exception as e:
            payload["semantic_ready"] = False
            payload["semantic_error"] = type(e).__name__
    else:
        payload["semantic_ready"] = False
        payload["semantic_required"] = False
    return payload


__all__ = [
    "MODES",
    "embedding_mode",
    "customer_visible_mode",
    "shadow_enabled",
    "shadow_kill_switch",
    "resource_budget",
    "budget_violations",
    "semantic_artifact_dir",
    "active_cluster_build_id",
    "backfill_batch_size",
    "inference_timeout_s",
    "onnx_intra_threads",
    "hash_embedder",
    "semantic_embedder",
    "try_semantic_embedder",
    "active_embedder",
    "active_embedding_version",
    "validate_startup_config",
    "health_payload",
    "reset_embedding_runtime",
]
