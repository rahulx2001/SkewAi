"""Human-label tooling. Never writes a class on its own.

  python -m scripts.eval_labels sample --pack automotive_nhtsa --n 20
  python -m scripts.eval_labels agreement
  python -m scripts.eval_labels export --out eval/embeddings/human_labels.jsonl
"""

from __future__ import annotations

import argparse
import json

from src.eval.embedding_gates import acceptance_eligibility
from src.eval.embedding_labels import agreement_report, export_labels, import_labels
from src.eval.sample_eval_queue import sample_unlabeled


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser()
    sub = p.add_subparsers(dest="cmd", required=True)
    s = sub.add_parser("sample")
    s.add_argument("--pack", default="automotive_nhtsa")
    s.add_argument("--n", type=int, default=20)
    s.add_argument("--strategy", default="random", choices=["random", "same_category"])
    s.add_argument("--seed", type=int, default=0)
    sub.add_parser("agreement")
    e = sub.add_parser("export")
    e.add_argument("--out", required=True)
    i = sub.add_parser("import")
    i.add_argument("--src", required=True)
    args = p.parse_args(argv)
    if args.cmd == "sample":
        ids = sample_unlabeled(args.pack, n=args.n, strategy=args.strategy, seed=args.seed)
        print(json.dumps({"enqueued": len(ids), "eval_ids": ids}, indent=2))
        return 0
    if args.cmd == "agreement":
        print(json.dumps({"agreement": agreement_report(), "eligibility": acceptance_eligibility()}, indent=2))
        return 0
    if args.cmd == "export":
        from pathlib import Path

        n = export_labels(Path(args.out))
        print(json.dumps({"exported": n}))
        return 0
    if args.cmd == "import":
        from pathlib import Path

        n = import_labels(Path(args.src))
        print(json.dumps({"imported": n}))
        return 0
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
