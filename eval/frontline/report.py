"""Eval report formatter — prints a markdown summary of gate results."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass
class GateResult:
    """Result of one CI gate for one pack."""

    name: str
    pack_id: str
    passed: bool
    detail: str = ""
    expected: Any = None
    actual: Any = None


def format_eval_report(results: list[GateResult]) -> str:
    """Build a markdown summary table of all gate results."""
    lines: list[str] = []
    lines.append("# Frontline v2 Eval Report")
    lines.append("")

    # Group by pack
    packs: dict[str, list[GateResult]] = {}
    for r in results:
        packs.setdefault(r.pack_id, []).append(r)

    for pack_id, gate_results in packs.items():
        lines.append(f"## Pack: `{pack_id}`")
        lines.append("")
        passed = sum(1 for r in gate_results if r.passed)
        total = len(gate_results)
        emoji = "✅" if passed == total else "❌"
        lines.append(f"{emoji} {passed}/{total} gates passed")
        lines.append("")
        lines.append("| Gate | Passed | Expected | Actual | Detail |")
        lines.append("|---|---|---|---|---|")
        for r in gate_results:
            mark = "✅" if r.passed else "❌"
            exp = r.expected if r.expected is not None else "—"
            act = r.actual if r.actual is not None else "—"
            lines.append(f"| {r.name} | {mark} | {exp} | {act} | {r.detail[:80]} |")
        lines.append("")

    # Overall verdict
    all_passed = all(r.passed for r in results)
    lines.append("## Overall Verdict")
    lines.append("")
    if all_passed:
        lines.append("✅ **ALL GATES PASSED** — genericity proven in CI.")
    else:
        n_failed = sum(1 for r in results if not r.passed)
        lines.append(f"❌ **{n_failed} GATE(S) FAILED** — see table above.")
    return "\n".join(lines)


__all__ = ["GateResult", "format_eval_report"]
