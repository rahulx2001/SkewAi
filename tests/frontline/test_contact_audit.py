"""Contact audit (groundedness) tests (per blueprint §15.2).

Covers:
  - Groundedness verdicts on a real end-to-end interaction
  - The audit report is written to disk
  - Good evidence (matched advisory, verified records) is "grounded"
"""

from __future__ import annotations

import pytest

from src.qubot.auditor import AuditResult, REPORTS_DIR, audit_interaction


async def _run_complete_contact(orchestrator_factory):
    """Run a full automotive contact end-to-end. Returns the interaction_id."""
    orch, _ = orchestrator_factory()
    await orch.start()
    await orch.handle_customer_turn("My 2019 Honda CR-V grinds when I brake.")
    await orch.handle_customer_turn("Nobody is hurt and I'm safe.")
    await orch.handle_customer_turn("Yes, I'm in a safe location.")
    assert orch.ctx.state == "DONE"
    return orch.ctx.interaction_id


# ── Audit runs on a real interaction ────────────────────────────────────────


async def test_audit_returns_audit_result(orchestrator_factory, reset_ops_db):
    iid = await _run_complete_contact(orchestrator_factory)
    result = await audit_interaction(iid, write_report=False)
    assert isinstance(result, AuditResult)
    assert result.interaction_id == iid
    assert result.pack_id == "automotive_nhtsa"
    assert result.pack_version  # non-empty
    assert result.total_actions > 0


async def test_audit_overall_verdict_grounded(orchestrator_factory, reset_ops_db):
    """A clean end-to-end contact should produce a 'grounded' overall verdict."""
    iid = await _run_complete_contact(orchestrator_factory)
    result = await audit_interaction(iid, write_report=False)
    # All evidence should verify against the seeded domain warehouse.
    assert result.overall_verdict == "grounded", (
        f"expected grounded, got {result.overall_verdict}; "
        f"mismatch_actions={result.mismatch_actions}, flags={result.flags}"
    )
    assert result.mismatch_actions == 0


# ── Report written to disk ────────────────────────────────────────────────────


async def test_audit_report_written(orchestrator_factory, reset_ops_db):
    iid = await _run_complete_contact(orchestrator_factory)
    result = await audit_interaction(iid, write_report=True)
    assert result.report_path is not None
    assert result.report_path.exists()
    # The report file is a markdown file named after the interaction_id.
    assert result.report_path.suffix == ".md"
    assert result.report_path.name == f"{iid}.md"
    # The report contains the headline verdict.
    content = result.report_path.read_text(encoding="utf-8")
    assert "Contact Audit Report" in content
    assert "Overall verdict" in content
    assert "GROUND" in content.upper()


# ── Good evidence is "grounded" ──────────────────────────────────────────────


async def test_advisory_evidence_is_grounded(orchestrator_factory, reset_ops_db):
    """The advisory_notified action's evidence_ids (19V-12345) must verify."""
    iid = await _run_complete_contact(orchestrator_factory)
    result = await audit_interaction(iid, write_report=False)
    # Find the advisory_notified action verdict.
    advisory_verdicts = [
        v for v in result.action_verdicts if v.action_type == "advisory_notified"
    ]
    assert advisory_verdicts, "expected an advisory_notified action in the ledger"
    for v in advisory_verdicts:
        assert v.verdict == "grounded", (
            f"advisory evidence should be grounded; got {v.verdict} ({v.detail})"
        )
        assert v.evidence_confirmed >= 1


async def test_record_evidence_is_grounded(orchestrator_factory, reset_ops_db):
    """The similar_search action's evidence_ids (NHTSA-XXXXX records) must verify."""
    iid = await _run_complete_contact(orchestrator_factory)
    result = await audit_interaction(iid, write_report=False)
    similar_verdicts = [
        v for v in result.action_verdicts if v.action_type == "similar_search"
    ]
    assert similar_verdicts
    for v in similar_verdicts:
        # Either grounded (every cited record exists) or the evidence list was empty.
        assert v.verdict in ("grounded",), (
            f"similar_search evidence should be grounded; got {v.verdict} ({v.detail})"
        )


async def test_cluster_evidence_is_grounded(orchestrator_factory, reset_ops_db):
    """The cluster_matched action's evidence_id (cluster 14) must verify."""
    iid = await _run_complete_contact(orchestrator_factory)
    result = await audit_interaction(iid, write_report=False)
    cluster_verdicts = [
        v for v in result.action_verdicts if v.action_type == "cluster_matched"
    ]
    assert cluster_verdicts
    for v in cluster_verdicts:
        assert v.verdict == "grounded"


# ── Severity sanity ────────────────────────────────────────────────────────────


async def test_severity_sane_for_clean_contact(orchestrator_factory, reset_ops_db):
    iid = await _run_complete_contact(orchestrator_factory)
    result = await audit_interaction(iid, write_report=False)
    assert result.severity_sane is True


# ── Uncited IDs ──────────────────────────────────────────────────────────────


async def test_no_uncited_ids_in_outputs(orchestrator_factory, reset_ops_db):
    """No agent action should reference an ID in its output that isn't in evidence_ids."""
    iid = await _run_complete_contact(orchestrator_factory)
    result = await audit_interaction(iid, write_report=False)
    for v in result.action_verdicts:
        assert v.uncited_ids_in_output == [], (
            f"action {v.action_id} ({v.action_type}) has uncited IDs: {v.uncited_ids_in_output}"
        )
