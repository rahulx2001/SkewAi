"""Frontline CLI — text-mode interaction runner.

Used by `make contact` for development. Talks to the orchestrator via the
simulated channel adapter (no WebSocket, no LLM required).
"""

from __future__ import annotations

import argparse
import asyncio
import sys
from typing import Any

from src.agents.orchestrator import OrchestratorHooks, create_interaction
from src.config import settings


class StdioHooks(OrchestratorHooks):
    """Prints agent turns + activity to stdout for local dev."""

    def __init__(self) -> None:
        self.last_case_id: str | None = None
        self.last_audit_pending = False

    async def emit_customer_turn(self, text: str, meta: dict[str, Any]) -> None:
        speaker = meta.get("speaker", "agent")
        marker = "[HUMAN]" if speaker == "supervisor" else "[AGENT]"
        print(f"\n{marker} {text}\n")

    async def emit_activity(self, payload: dict[str, Any]) -> None:
        agent = payload.get("agent", "?")
        summary = payload.get("summary", "")
        evidence = payload.get("evidence_ids", [])
        print(f"   (activity) {agent}: {summary}" + (f"  evidence={evidence}" if evidence else ""))

    async def emit_slots_update(self, slots: dict[str, str]) -> None:
        # Strip private keys
        clean = {k: v for k, v in slots.items() if not k.startswith("__")}
        print(f"   (slots) {clean}")

    async def emit_handoff_offer(self) -> None:
        print("   ⚠️  frustration threshold crossed — handoff offered")

    async def emit_interaction_ended(self, payload: dict[str, Any]) -> None:
        self.last_case_id = payload.get("case_id")
        self.last_audit_pending = payload.get("audit_pending", False)
        print(f"\n✅ Interaction ended. case_id={payload.get('case_id')}")


async def run_scripted(script: list[str] | None = None, pack_id: str | None = None) -> int:
    """Run a scripted text interaction. If `script` is None, use a sensible default."""
    if script is None:
        script = [
            "My 2019 Honda CR-V grinds when I brake.",
            "It started about a week ago.",
            "Yes it happens at low speeds too.",
            "Nobody has been hurt and I'm pulled over safely.",
        ]
    pack_id = pack_id or settings.domain_pack

    hooks = StdioHooks()
    orch, greeting = await create_interaction(
        channel="web_text", pack_id=pack_id, hooks=hooks
    )
    print(f"\n=== Skew AI — text mode (pack: {orch.ctx.pack.display_name}) ===\n")

    for turn in script:
        print(f"\n[CUSTOMER] {turn}")
        await orch.handle_customer_turn(turn)
        if orch.ctx.state in ("DONE", "ABANDONED"):
            break

    if orch.ctx.state != "DONE":
        # Force a hangup if we still have state
        await orch.hangup()

    print(f"\n=== Done ===")
    print(f"  interaction_id: {orch.ctx.interaction_id}")
    print(f"  state:          {orch.ctx.state}")
    print(f"  case_id:        {orch.ctx.case_id}")
    print(f"  severity:       {orch.ctx.severity} (P{orch.ctx.priority})")
    print(f"  advisory_match: {orch.ctx.advisory_match is not None}")
    print(f"  peak_frustration: {orch.ctx.peak_frustration}")
    if orch.ctx.investigation_id:
        print(f"  investigation_id: {orch.ctx.investigation_id}")
    print(f"  pack_version:   {orch.ctx.pack.pack_version}")
    return 0


def _main() -> int:
    parser = argparse.ArgumentParser(description="Skew AI text-mode interaction runner")
    parser.add_argument("command", choices=["contact"], help="Subcommand")
    parser.add_argument("--pack", default=None, help="Pack id (default: from env)")
    parser.add_argument(
        "--script", default=None,
        help="Comma-separated customer turns (default: scripted brake-grinding complaint)",
    )
    args = parser.parse_args()

    script = None
    if args.script:
        script = [t.strip() for t in args.script.split("|")]
    return asyncio.run(run_scripted(script=script, pack_id=args.pack))


if __name__ == "__main__":
    sys.exit(_main())
