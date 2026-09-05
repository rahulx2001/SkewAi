"""Download and verify a local MiniLM ONNX artifact. Not used at runtime.

Runtime inference never calls this script and never hits the network.

Pinned source (Apache-2.0):
  model family: sentence-transformers/all-MiniLM-L6-v2
  ONNX export:  Xenova/all-MiniLM-L6-v2 (quantized int8)
  tokenizer:    matching Xenova tokenizer.json

Usage:
  python -m scripts.prepare_minilm_onnx --out models/minilm
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
import urllib.request
from pathlib import Path

from src.config import REPO_ROOT

# Pin both the HF repo and the revision. Update together after a reviewed bump.
HF_REPO = "Xenova/all-MiniLM-L6-v2"
HF_REVISION = "751bff37182d3f1213fa05d7196b954e230abad9"
UPSTREAM_MODEL = "sentence-transformers/all-MiniLM-L6-v2"
# Public sentence-transformers checkpoint this ONNX export tracks.
UPSTREAM_MODEL_REVISION = "c9745ed1d9f366e9d5b9aada2b23ac006d1b8c54"

# Files fetched from the Xenova repo (transformers.js ONNX layout).
FILES = {
    "model.onnx": "onnx/model_quantized.onnx",
    "tokenizer.json": "tokenizer.json",
    "config.json": "config.json",
    "tokenizer_config.json": "tokenizer_config.json",
    "LICENSE": "LICENSE",
}

NATIVE_DIM = 384
OUTPUT_DIM = 512
MAX_SEQ = 256


def _sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def _download(url: str, dest: Path) -> None:
    dest.parent.mkdir(parents=True, exist_ok=True)
    req = urllib.request.Request(url, headers={"User-Agent": "skewai-minilm-prepare/1"})
    with urllib.request.urlopen(req, timeout=120) as resp, dest.open("wb") as out:
        while True:
            chunk = resp.read(1024 * 1024)
            if not chunk:
                break
            out.write(chunk)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Prepare local MiniLM ONNX artifact")
    parser.add_argument("--out", default="models/minilm", help="artifact directory")
    parser.add_argument("--revision", default=HF_REVISION)
    args = parser.parse_args(argv)
    out = Path(args.out)
    if not out.is_absolute():
        out = REPO_ROOT / out
    out.mkdir(parents=True, exist_ok=True)
    base = f"https://huggingface.co/{HF_REPO}/resolve/{args.revision}"
    checksums: dict[str, str] = {}
    for local_name, remote in FILES.items():
        dest = out / local_name
        url = f"{base}/{remote}"
        print(f"fetch {remote} -> {dest.name}")
        try:
            _download(url, dest)
        except Exception as e:
            if local_name == "LICENSE":
                dest.write_text(
                    "Apache License 2.0 — see https://huggingface.co/sentence-transformers/all-MiniLM-L6-v2\n",
                    encoding="utf-8",
                )
            else:
                print(f"ERROR downloading {url}: {type(e).__name__}: {e}", file=sys.stderr)
                return 1
        checksums[local_name] = _sha256(dest)
        print(f"  sha256 {checksums[local_name]}  {dest.stat().st_size} bytes")
    manifest = {
        "model_family": "all-MiniLM-L6-v2",
        "upstream_model": UPSTREAM_MODEL,
        "upstream_model_revision": UPSTREAM_MODEL_REVISION,
        "model_revision": args.revision,
        "tokenizer_revision": args.revision,
        "onnx_source_repo": HF_REPO,
        "quantization": "onnx-int8",
        "pooling": "mean-pool",
        "normalization": "l2",
        "padding": "zeropad512",
        "schema_version": "v1",
        "native_dimension": NATIVE_DIM,
        "output_dimension": OUTPUT_DIM,
        "max_seq_length": MAX_SEQ,
        "truncation": "head",
        "export_tool": "Xenova transformers.js ONNX export (consumed as-is)",
        "onnx_opset": "see model.onnx",
        "model_sha256": checksums.get("model.onnx", ""),
        "tokenizer_sha256": checksums.get("tokenizer.json", ""),
        "license": "Apache-2.0",
    }
    (out / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    lines = [f"{digest}  {name}" for name, digest in checksums.items()]
    (out / "checksums.sha256").write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(json.dumps({"ok": True, "dir": str(out), "manifest": manifest}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
