"""Qubot v2 CLI — `make audit ID=...` and `make ask Q="..."`.

Usage
-----
    python -m src.qubot.cli audit --interaction-id int_xxxx
    python -m src.qubot.cli ask "how many critical cases this week?"
    python -m src.qubot.cli digest [--window-days 1]
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from typing import Any

from src.qubot.auditor import audit_interaction, write_daily_digest
from src.qubot.retrievers import RETRIEVERS


def _cmd_audit(args: argparse.Namespace) -> int:
    if not args.interaction_id:
        print("error: --interaction-id is required", file=sys.stderr)
        return 2
    result = asyncio.run(audit_interaction(args.interaction_id, write_report=True))
    print(f"Audit complete for {result.interaction_id}")
    print(f"  Pack:           {result.pack_id} (v{result.pack_version})")
    print(f"  Overall verdict: {result.overall_verdict.upper()}")
    print(f"  Actions:        {result.total_actions} "
          f"(grounded={result.grounded_actions}, "
          f"unverifiable={result.unverifiable_actions}, "
          f"mismatch={result.mismatch_actions})")
    print(f"  Severity sane:  {result.severity_sane} ({result.severity_note})")
    print(f"  Peak frustration: {result.peak_frustration:.2f}")
    if result.supervised_segments:
        print(f"  Supervised turns: {len(result.supervised_segments)}")
    if result.flags:
        print("  Flags:")
        for f in result.flags:
            print(f"    - {f}")
    if result.report_path:
        print(f"  Report:         {result.report_path}")
    return 0 if result.overall_verdict == "grounded" else 1


EXAMPLE_QUESTIONS = (
    "how many contacts today",
    "contacts per day this week",
    "top components in automotive",
    "top merchants in finance",
    "show case funnel",
    "any critical cases this week?",
    "list open investigations",
    "agent error rate today",
    "which clusters are hot",
)


def _cmd_ask(args: argparse.Namespace) -> int:
    """Deterministic keyword router over RETRIEVERS — works offline, no LLM.

    Keeps answers honest: never hallucinates, only routes to SQL-backed
    retrievers. Unrecognized questions print a helpful suggestion list instead
    of a bare failure.
    """
    q = args.question.lower()

    # Day-count queries — most common "I just want a number" shape.
    if any(kw in q for kw in ("how many contacts", "contact count", "contacts per day", "contacts today", "how many today")):
        data: Any = RETRIEVERS["daily_counts"](days=args.window_days)
    # Top-N entity questions (pack-aware).
    elif any(kw in q for kw in ("top ", "most complained", "most reported", "worst ")):
        entity_hint = "automotive_nhtsa" if any(kw in q for kw in ("component", "vehicle", "nhtsa", "automotive")) else "finance_cfpb"
        data = RETRIEVERS["top_offenders"](pack_id=entity_hint)
    elif any(kw in q for kw in ("critical", "case", "funnel", "cases this week", "case count")):
        if "investigation" in q:
            data = RETRIEVERS["investigation_status"](window_days=args.window_days)
        elif "cluster" in q or "risk" in q:
            data = RETRIEVERS["live_risk"](window_days=args.window_days)
        else:
            data = RETRIEVERS["case_funnel"](window_days=args.window_days)
    elif "investigation" in q:
        data = RETRIEVERS["investigation_status"](window_days=args.window_days)
    elif "agent" in q and ("error" in q or "performance" in q):
        data = RETRIEVERS["agent_performance"](window_days=args.window_days)
    elif "cluster" in q or "risk" in q or "anomal" in q:
        data = RETRIEVERS["live_risk"](window_days=args.window_days)
    elif "funnel" in q or "started" in q or "completed" in q:
        data = RETRIEVERS["case_funnel"](window_days=args.window_days)
    else:
        print(f"Couldn't route question: '{args.question}'")
        print(f"Supported patterns ({len(EXAMPLE_QUESTIONS)} examples):")
        for ex in EXAMPLE_QUESTIONS:
            print(f"  • {ex}")
        print(f"Retrievers: {', '.join(RETRIEVERS)}")
        return 1

    print(json.dumps(data, indent=2, default=str))
    return 0


def _cmd_digest(args: argparse.Namespace) -> int:
    path = write_daily_digest(window_days=args.window_days)
    print(f"Daily digest written: {path}")
    return 0


def _main() -> int:
    parser = argparse.ArgumentParser(description="Qubot v2 — auditor + ask-data CLI")
    sub = parser.add_subparsers(dest="cmd", required=True)

    p_audit = sub.add_parser("audit", help="Run the post_contact_audit playbook on a contact")
    p_audit.add_argument("--interaction-id", required=True)
    p_audit.set_defaults(func=_cmd_audit)

    p_ask = sub.add_parser("ask", help="Ask the Qubot ask-data layer a question")
    p_ask.add_argument("question")
    p_ask.add_argument("--window-days", type=int, default=7)
    p_ask.set_defaults(func=_cmd_ask)

    p_digest = sub.add_parser("digest", help="Generate the daily_frontline_digest")
    p_digest.add_argument("--window-days", type=int, default=1)
    p_digest.set_defaults(func=_cmd_digest)

    args = parser.parse_args()
    return args.func(args)


if __name__ == "__main__":
    sys.exit(_main())
