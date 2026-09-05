"""ONNX pooling, manifest validation, toy provider, no-download guarantee."""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import patch

import numpy as np
import pytest

from src.ml_runtime.onnx_embedder import (
    REQUIRED_FILES,
    ToySemanticEmbedder,
    build_canonical_version,
    l2_normalize_rows,
    mean_pool,
    validate_artifact_dir,
)
from src.ml_runtime.embedding_space import (
    ArtifactIntegrityError,
    compare_embeddings,
    native_prefix,
)


def test_mean_pool_ignores_padding_tokens():
    hidden = np.zeros((1, 4, 384), dtype=np.float32)
    hidden[0, 0, 0] = 2.0
    hidden[0, 1, 0] = 4.0
    hidden[0, 2, 0] = 99.0  # pad
    hidden[0, 3, 0] = 99.0  # pad
    mask = np.array([[1, 1, 0, 0]], dtype=np.int64)
    pooled = mean_pool(hidden, mask)
    assert pooled.shape == (1, 384)
    assert pooled[0, 0] == pytest.approx(3.0)


def test_l2_normalize_rows():
    x = np.array([[3.0, 4.0] + [0.0] * 382], dtype=np.float32)
    n = l2_normalize_rows(x)
    assert n.shape == (1, 384)
    assert float(np.linalg.norm(n[0])) == pytest.approx(1.0, abs=1e-6)


def test_validate_artifact_missing_dir(tmp_path: Path):
    with pytest.raises(ArtifactIntegrityError):
        validate_artifact_dir(tmp_path / "nope")


def test_validate_artifact_checksum_mismatch(tmp_path: Path):
    d = tmp_path / "art"
    d.mkdir()
    (d / "model.onnx").write_bytes(b"fake-onnx")
    (d / "tokenizer.json").write_text("{}", encoding="utf-8")
    (d / "config.json").write_text("{}", encoding="utf-8")
    (d / "LICENSE").write_text("Apache-2.0\n", encoding="utf-8")
    (d / "checksums.sha256").write_text(
        "0" * 64 + "  model.onnx\n" + "1" * 64 + "  tokenizer.json\n",
        encoding="utf-8",
    )
    (d / "manifest.json").write_text(
        json.dumps(
            {
                "model_family": "all-MiniLM-L6-v2",
                "model_revision": "abc",
                "tokenizer_revision": "abc",
                "native_dimension": 384,
                "output_dimension": 512,
                "quantization": "onnx-int8",
            }
        ),
        encoding="utf-8",
    )
    with pytest.raises(ArtifactIntegrityError, match="checksum mismatch"):
        validate_artifact_dir(d)


def test_validate_revision_disagreement(tmp_path: Path):
    import hashlib

    d = tmp_path / "art"
    d.mkdir()
    model = b"fake-onnx"
    tok = b"{}"
    (d / "model.onnx").write_bytes(model)
    (d / "tokenizer.json").write_bytes(tok)
    (d / "config.json").write_text("{}", encoding="utf-8")
    (d / "LICENSE").write_text("Apache-2.0\n", encoding="utf-8")
    mh = hashlib.sha256(model).hexdigest()
    th = hashlib.sha256(tok).hexdigest()
    (d / "checksums.sha256").write_text(f"{mh}  model.onnx\n{th}  tokenizer.json\n", encoding="utf-8")
    (d / "manifest.json").write_text(
        json.dumps(
            {
                "model_family": "all-MiniLM-L6-v2",
                "model_revision": "aaa",
                "tokenizer_revision": "bbb",
                "native_dimension": 384,
                "output_dimension": 512,
            }
        ),
        encoding="utf-8",
    )
    with pytest.raises(ArtifactIntegrityError, match="disagrees"):
        validate_artifact_dir(d)


def test_canonical_version_is_complete():
    v = build_canonical_version(
        {
            "model_family": "all-MiniLM-L6-v2",
            "model_revision": "deadbeef",
            "tokenizer_revision": "deadbeef",
            "quantization": "onnx-int8",
            "pooling": "mean-pool",
            "normalization": "l2",
            "padding": "zeropad512",
            "schema_version": "v1",
            "model_sha256": "abc123",
        }
    )
    assert v.startswith("all-MiniLM-L6-v2@deadbeef")
    assert "onnx-int8" in v
    assert "mean-pool" in v
    assert "zeropad512" in v
    assert "modelsha256=abc123" in v
    assert v != "minilm-v1"


def test_toy_embedder_deterministic_and_padded():
    e = ToySemanticEmbedder()
    a = e.embed("vehicle stalled at 65 mph")
    b = e.embed("vehicle stalled at 65 mph")
    assert a.values == b.values
    assert a.native_dimension == 384
    assert a.output_dimension == 512
    assert list(a.values[384:]) == [0.0] * 128
    assert not any(math_isnan(x) for x in a.values)


def math_isnan(x: float) -> bool:
    return x != x


def test_toy_empty_text_is_zero_not_nan():
    e = ToySemanticEmbedder()
    z = e.embed("")
    assert z.is_zero
    assert all(x == 0.0 for x in z.values)


def test_toy_does_not_download():
    with patch("urllib.request.urlopen") as urlopen:
        ToySemanticEmbedder().embed("hello")
        urlopen.assert_not_called()


def test_required_files_include_manifest():
    assert "manifest.json" in REQUIRED_FILES
    assert "model.onnx" in REQUIRED_FILES
