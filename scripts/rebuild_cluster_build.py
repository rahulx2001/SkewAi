"""CLI: versioned cluster rebuild (does not wipe live hash-era clusters).

  python -m scripts.rebuild_cluster_build --pack automotive_nhtsa --version <canonical> --dry-run
  python -m scripts.rebuild_cluster_build --pack automotive_nhtsa --version <canonical>
  python -m scripts.rebuild_cluster_build --activate BUILD_ID --pack automotive_nhtsa
"""

from __future__ import annotations

import argparse
import json
import sys

from src.ml_runtime.cluster_builds import (
    activate_cluster_build,
    rebuild_cluster_build,
    rollback_cluster_build,
)
from src.ml_runtime.embedding_runtime import try_semantic_embedder
from src.ml_runtime.embedding_space import HASH_EMBEDDING_VERSION


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description="Versioned cluster rebuild")
    p.add_argument("--pack", default="automotive_nhtsa")
    p.add_argument("--version", default="")
    p.add_argument("--k", type=int, default=5)
    p.add_argument("--dry-run", action="store_true")
    p.add_argument("--activate", default="", help="activate an existing build id")
    p.add_argument("--rollback", default="", help="rollback an active build id")
    args = p.parse_args(argv)
    if args.activate:
        print(json.dumps(activate_cluster_build(args.pack, args.activate), indent=2, default=str))
        return 0
    if args.rollback:
        print(json.dumps(rollback_cluster_build(args.pack, args.rollback), indent=2, default=str))
        return 0
    version = args.version.strip()
    if not version:
        sem = try_semantic_embedder()
        version = sem.version if sem is not None else HASH_EMBEDDING_VERSION
    report = rebuild_cluster_build(
        args.pack, version, k=args.k, dry_run=args.dry_run
    )
    print(json.dumps(report, indent=2, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
