"""CLI: resumable semantic/hash embedding backfill.

  python -m scripts.embedding_backfill --pack automotive_nhtsa --version <canonical> --dry-run
  python -m scripts.embedding_backfill --pack automotive_nhtsa --version <canonical>
"""

from __future__ import annotations

import argparse
import json
import sys

from src.ml_runtime.embedding_backfill import run_backfill
from src.ml_runtime.embedding_runtime import try_semantic_embedder
from src.ml_runtime.embedding_space import HASH_EMBEDDING_VERSION


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description="Resumable embedding backfill")
    p.add_argument("--pack", default="automotive_nhtsa")
    p.add_argument("--version", default="", help="canonical embedding version (default: active semantic or hash)")
    p.add_argument("--dry-run", action="store_true")
    p.add_argument("--batch-size", type=int, default=None)
    p.add_argument("--limit", type=int, default=None)
    p.add_argument("--no-retry", action="store_true")
    args = p.parse_args(argv)
    version = args.version.strip()
    if not version:
        sem = try_semantic_embedder()
        version = sem.version if sem is not None else HASH_EMBEDDING_VERSION
    report = run_backfill(
        args.pack,
        version,
        dry_run=args.dry_run,
        batch_size=args.batch_size,
        limit=args.limit,
        include_retry=not args.no_retry,
    )
    print(json.dumps(report, indent=2, default=str))
    return 0 if report.get("failed", 0) == 0 else 2


if __name__ == "__main__":
    raise SystemExit(main())
