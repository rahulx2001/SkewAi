"""CLI: python -m src.domains.builder --src tickets.csv --pack-id my_pack"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from src.domains.builder.pack_builder import build_draft_pack, profile_csv


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Pack Builder MVP")
    ap.add_argument("--src", required=True, help="Input CSV path")
    ap.add_argument("--pack-id", default="generated_pack")
    ap.add_argument("--name", default="Generated Pack")
    ap.add_argument("--advisories", default="", help="Optional advisories CSV (ignored in MVP)")
    ap.add_argument("--profile-only", action="store_true")
    args = ap.parse_args(argv)

    src_path = Path(args.src)
    if not src_path.exists():
        print(f"error: --src not found: {args.src}", file=sys.stderr)
        return 2
    if not src_path.is_file():
        print(f"error: --src is not a file: {args.src}", file=sys.stderr)
        return 2
    if src_path.stat().st_size == 0:
        print(f"error: --src is empty: {args.src}", file=sys.stderr)
        return 2

    if args.profile_only:
        print(profile_csv(args.src))
        return 0
    out = build_draft_pack(
        pack_id=args.pack_id,
        display_name=args.name,
        csv_path=args.src,
    )
    print(out)
    print(f"Next: make pack-lint PACK={args.pack_id}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
