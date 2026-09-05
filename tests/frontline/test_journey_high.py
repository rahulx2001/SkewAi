"""Journey-audit regression tests — HIGH findings.

0.4 entity_key join keys + observed/inferred links; 0.5 migrate order +
    readiness; 1.1 start idempotency + returning-customer attach; 2.3
    negation/hedge downgrade; 2.4 handoff accept/timeout; 3.3 release
    recompute; 4.1 reenrich + escalation enrichment; 4.5 slice-claim
    single opener; 5.1 claim TTL + crash-retry single case; 7.2 case_kind
    corpus exclusion; 8.1 exposure rates + backtest as-of; 8.4 fix
    controls + COPQ range; X.5 ledger WAL fallback + replay.
"""

from __future__ import annotations

import pytest


def _drive_to_done(orch, max_turns: int = 14):
    async def _go():
        await orch.start()
        await orch.handle_customer_turn("My 2019 Honda CR-V grinds when I brake.")
        for _ in range(max_turns):
            if orch.ctx.state == "DONE":
                break
            await orch.handle_customer_turn("Additional detail for the record.")
        if orch.ctx.state != "DONE":
            await orch._move_to_closing()

    return _go


# ── 0.4 entity_key ───────────────────────────────────────────────────────────


def test_h04_entity_key_template_and_links(tmp_path, monkeypatch):
    from src.data.warehouse import domain_con
    from src.domains.mapping_ingest import load_mapping, map_row
    from src.domains.source_ingest import ingest_source

    from src.config import REPO_ROOT

    monkeypatch.setenv("DOMAIN_DB_PATH", str(tmp_path))
    auto = REPO_ROOT / "domains" / "automotive_nhtsa" / "data"
    mapping = load_mapping(auto / "mapping.warranty.yaml")
    rec = map_row(
        {
            "CLAIM_ID": "9", "CLAIM_DATE": "2024-03-01", "REPAIR_DATE": "2024-02-20",
            "MODEL_YR": "2019", "MAKETXT": "Honda", "MODELTXT": "CR-V",
            "COMPNAME": "SERVICE BRAKES", "TECH_NOTES": "grinding pads",
        },
        mapping["records"],
    )
    assert rec is not None
    assert rec["entity_key"] == "2019|HONDA|CR-V"
    # Unresolvable template → empty, never invented.
    rec2 = map_row({"CLAIM_ID": "10", "TECH_NOTES": "x" * 20}, {"record_id": "CLAIM_ID", "text": "TECH_NOTES"})
    assert rec2 is not None and rec2["entity_key"] == ""

    from src.agents.investigator import _cross_source_links

    links = _cross_source_links([
        {"record_id": "A", "category": "SERVICE BRAKES", "entity_2": "HONDA",
         "entity_3": "CR-V", "source": "NHTSA", "entity_key": "2019|HONDA|CR-V"},
        {"record_id": "B", "category": "SERVICE BRAKES", "entity_2": "HONDA",
         "entity_3": "CR-V", "source": "WARRANTY", "entity_key": "2019|HONDA|CR-V"},
        {"record_id": "C", "category": "AIR BAGS", "entity_2": "TOYOTA",
         "entity_3": "CAMRY", "source": "SERVICE", "entity_key": ""},
        {"record_id": "D", "category": "AIR BAGS", "entity_2": "TOYOTA",
         "entity_3": "CAMRY", "source": "NHTSA", "entity_key": ""},
    ])
    by_basis = {}
    for lk in links:
        by_basis.setdefault(lk["basis"], []).append(lk)
    assert len(by_basis.get("observed", [])) == 1
    assert by_basis["observed"][0]["entity_key"] == "2019|HONDA|CR-V"
    assert len(by_basis.get("inferred", [])) == 1


def test_h04_reingest_is_idempotent_upsert(tmp_path, monkeypatch):
    from src.data.warehouse import domain_con
    from src.domains.source_ingest import ingest_source

    from src.config import REPO_ROOT

    monkeypatch.setenv("DOMAIN_DB_PATH", str(tmp_path))
    auto = REPO_ROOT / "domains" / "automotive_nhtsa" / "data"
    csv = tmp_path / "w.csv"
    csv.write_text(
        "CLAIM_ID,CLAIM_DATE,REPAIR_DATE,MODEL_YR,MAKETXT,MODELTXT,COMPNAME,"
        "FAIL_CODE,TECH_NOTES,CLAIM_SEVERITY,STATE\n"
        "1,2024-03-01,2024-02-20,2019,HONDA,CR-V,SERVICE BRAKES,,grinding pads,Medium,CA\n",
        encoding="utf-8",
    )
    r1 = ingest_source("h04_pack", "warranty", csv, mapping_path=auto / "mapping.warranty.yaml")
    r2 = ingest_source("h04_pack", "warranty", csv, mapping_path=auto / "mapping.warranty.yaml")
    assert (r1["upserted"], r2["upserted"]) == (1, 1)
    with domain_con("h04_pack") as con:
        n = con.execute("SELECT COUNT(*) FROM records").fetchone()[0]
        ek = con.execute("SELECT entity_key FROM records").fetchone()[0]
    assert n == 1 and ek == "2019|HONDA|CR-V"


# ── 0.5 migrate order + readiness ────────────────────────────────────────────


def test_h05_schema_gate_and_stamp(tmp_path):
    import duckdb

    from scripts.migrate import require_schema_current, stamp_schema_current

    db = tmp_path / "gate.duckdb"
    con = duckdb.connect(str(db))
    con.execute("CREATE TABLE schema_migrations (version VARCHAR PRIMARY KEY, name VARCHAR NOT NULL)")
    con.execute("INSERT INTO schema_migrations VALUES ('000', 'test')")
    con.close()
    with pytest.raises(RuntimeError, match="behind migration HEAD"):
        require_schema_current(db, target="ops")
    stamped = stamp_schema_current(db, target="ops")
    assert stamped, "stamp must record available versions"
    require_schema_current(db, target="ops")  # no longer raises


def test_h05_readiness_section(reset_ops_db, seed_automotive_pack, monkeypatch):
    from fastapi.testclient import TestClient

    from src.api.main import app

    monkeypatch.delenv("FRONTLINE_API_KEY", raising=False)
    with TestClient(app) as c:
        r = c.get("/health")
    assert r.status_code == 200
    body = r.json()
    assert body["readiness"]["ready"] is True
    checks = body["readiness"]["checks"]
    assert checks["gazetteers"]["ok"] is True
    assert checks["triage"]["ok"] is True
    assert checks["cost_model"]["ok"] is True


# ── 1.1 start idempotency + returning customer ───────────────────────────────


def test_h11_start_idempotent(reset_ops_db, seed_automotive_pack, monkeypatch):
    from fastapi.testclient import TestClient

    from src.api.main import app

    monkeypatch.delenv("FRONTLINE_API_KEY", raising=False)
    with TestClient(app) as c:
        h = {"Idempotency-Key": "start-key-1"}
        r1 = c.post("/api/interactions/start?channel=web_text", headers=h)
        assert r1.status_code == 200
        r2 = c.post("/api/interactions/start?channel=web_text", headers=h)
        assert r2.status_code == 200
        assert r2.json()["interaction_id"] == r1.json()["interaction_id"]
        assert r2.json().get("deduped") is True
        r3 = c.post("/api/interactions/start?channel=web_text")
        assert r3.json()["interaction_id"] != r1.json()["interaction_id"]


@pytest.mark.asyncio
async def test_h11_returning_customer_attaches(orchestrator_factory):
    """Same customer_ref + entity/category + open case ⇒ attach, not new case."""
    import hashlib

    from src.data.warehouse import ops_con
    from src.ledger import list_actions

    ref = hashlib.sha256(b"+15551234567").hexdigest()
    orch1, _ = orchestrator_factory()
    orch1.ctx.customer_ref = ref
    await _drive_to_done(orch1)()
    first_case = orch1.ctx.case_id
    assert first_case
    orch2, _ = orchestrator_factory()
    orch2.ctx.customer_ref = ref
    await _drive_to_done(orch2)()
    assert orch2.ctx.case_id == first_case, "must attach, not open a second case"
    with ops_con(read_only=True) as con:
        n = con.execute(
            "SELECT COUNT(*) FROM cases WHERE customer_ref = ?", [ref]
        ).fetchone()[0]
    assert n == 1
    assert any(
        a["action_type"] == "case_attached_existing"
        for a in list_actions(orch2.ctx.interaction_id)
    )


# ── 2.3 negation downgrade ───────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_h23_negated_and_hedged_no_escalation(orchestrator_factory):
    from src.agents.intake import IntakeAgent

    orch, _ = orchestrator_factory()
    intake = IntakeAgent(orch.ctx)
    neg = await intake.run(customer_turn="There was no fire, just a smell.")
    assert neg.get("kill_switch") is None
    assert neg.get("safety_question") is True
    assert not orch.ctx.safety_flags.get("escalation")
    hedge = await intake.run(customer_turn="I'm worried it might catch fire.")
    assert hedge.get("kill_switch") is None
    assert hedge.get("safety_question") is True


@pytest.mark.asyncio
async def test_h23_affirmative_still_escalates(orchestrator_factory):
    from src.agents.intake import IntakeAgent

    orch, _ = orchestrator_factory()
    intake = IntakeAgent(orch.ctx)
    hit = await intake.run(customer_turn="My car caught fire while driving!")
    assert hit.get("kill_switch"), "affirmative term must escalate in ≤1 turn"


# ── 2.4 handoff accept + timeout ─────────────────────────────────────────────


@pytest.mark.asyncio
async def test_h24_accept_timeout_resume(orchestrator_factory):
    from datetime import timedelta

    from src.data.timeutil import utc_now
    from src.data.warehouse import ops_con
    from src.ledger import list_actions

    orch, hooks = orchestrator_factory()
    await orch.start()
    orch.ctx.handoff_offered = True
    out = await orch.accept_handoff()
    assert out["accepted"] is True
    assert orch.ctx.state == "HANDOFF_PENDING"
    # Supervisor claims via takeover: queue row closes.
    await orch.takeover()
    assert orch.ctx.state == "SUPERVISED"
    with ops_con(read_only=True) as con:
        st = con.execute(
            "SELECT status FROM handoff_requests WHERE interaction_id = ?",
            [orch.ctx.interaction_id],
        ).fetchone()[0]
    assert st == "claimed"

    orch2, hooks2 = orchestrator_factory()
    await orch2.start()
    orch2.ctx.handoff_offered = True
    await orch2.accept_handoff()
    # Backdate SLA into the past → sweep restores + apologises.
    with ops_con() as con:
        con.execute(
            "UPDATE handoff_requests SET sla_due_at = ? WHERE interaction_id = ?",
            [utc_now() - timedelta(seconds=5), orch2.ctx.interaction_id],
        )
    assert await orch2.sweep_handoff_timeout() is True
    assert orch2.ctx.state == "COLLECTING"
    types = [a["action_type"] for a in list_actions(orch2.ctx.interaction_id)]
    assert "handoff_accepted" in types and "handoff_unfulfilled" in types
    assert any("sorry" in (t.get("text") or "").lower() for t in hooks2.turns if t["speaker"] == "agent")


def test_h24_digest_lists_handoffs(reset_ops_db, seed_automotive_pack):
    from src.qubot.auditor import write_daily_digest

    path = write_daily_digest(window_days=1)
    text = path.read_text(encoding="utf-8")
    assert "## Handoffs" in text


# ── 3.3 release recompute ────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_h33_release_with_safety_delivers_script(orchestrator_factory):
    orch, hooks = orchestrator_factory()
    await orch.start()
    await orch.takeover()
    await orch.handle_customer_turn("I'M BLEEDING from the crash!")
    assert orch.ctx.state == "SUPERVISED"
    await orch.release()
    # Recomputed: escalation delivered, contact closed — never dropped.
    assert orch.ctx.state == "DONE"
    assert orch.ctx.severity == "Critical" and orch.ctx.priority == 1
    assert orch.ctx.case_id
    from src.ledger import list_actions

    types = [a["action_type"] for a in list_actions(orch.ctx.interaction_id)]
    assert "escalation_script_emitted" in types


@pytest.mark.asyncio
async def test_h33_release_with_full_slots_enriches(orchestrator_factory):
    orch, _ = orchestrator_factory()
    await orch.start()
    await orch.handle_customer_turn("My 2019 Honda CR-V grinds when I brake.")
    assert orch.ctx.has_required_slots()
    await orch.takeover()
    await orch.release()
    assert orch.ctx.state == "DONE"
    assert orch.ctx.case_id


# ── 4.1 reenrich + escalation enrichment ─────────────────────────────────────


@pytest.mark.asyncio
async def test_h41_investigator_failure_enqueues_reenrich(orchestrator_factory):
    from src.agents import orchestrator as orch_mod
    from src.data.warehouse import ops_con

    orch, _ = orchestrator_factory()
    await orch.start()
    await orch.handle_customer_turn("My 2019 Honda CR-V grinds when I brake.")
    orig = orch_mod.InvestigatorAgent
    try:
        class _Fail(orig):
            async def run(self, **kwargs):
                raise RuntimeError("ml backend down")

        orch_mod.InvestigatorAgent = _Fail
        await orch._enter_enriching()
    finally:
        orch_mod.InvestigatorAgent = orig
    assert orch.ctx.state == "DONE"
    with ops_con(read_only=True) as con:
        row = con.execute(
            "SELECT job_type, status FROM job_queue WHERE job_type = 'reenrich'"
            " ORDER BY created_at DESC LIMIT 1"
        ).fetchone()
    assert row is not None and row[0] == "reenrich"


@pytest.mark.asyncio
async def test_h41_backfill_patches_case(orchestrator_factory):
    from src.data.warehouse import ops_con
    from src.frontline.reenrich import backfill_brief
    from src.ledger import list_actions

    orch, _ = orchestrator_factory()
    await _drive_to_done(orch)()
    assert orch.ctx.case_id
    report = backfill_brief(orch.ctx.interaction_id, case_id=orch.ctx.case_id)
    assert report["ok"] is True
    assert report["provenance"] == "backfilled"
    assert report["cluster_id"] is not None
    with ops_con(read_only=True) as con:
        row = con.execute(
            "SELECT cluster_match_id FROM cases WHERE case_id = ?",
            [orch.ctx.case_id],
        ).fetchone()
    assert row and row[0] is not None
    assert any(
        "backfilled" in (a.get("output_summary") or "")
        for a in list_actions(orch.ctx.interaction_id)
    )


@pytest.mark.asyncio
async def test_h41_escalation_path_has_evidence(orchestrator_factory):
    orch, _ = orchestrator_factory()
    await orch.start()
    await orch.handle_customer_turn("My 2019 Honda CR-V caught FIRE while driving!")
    assert orch.ctx.state == "DONE"
    assert orch.ctx.investigation_brief is not None, (
        "Critical escalation close must carry enrichment evidence"
    )


# ── 4.5 single opener ────────────────────────────────────────────────────────


def test_h45_concurrent_open_single_row(reset_ops_db):
    import concurrent.futures as _fut

    from src.data.warehouse import ops_con
    from src.frontline.live_intercept import open_or_link_investigation

    with _fut.ThreadPoolExecutor(max_workers=4) as ex:
        ids = list(
            ex.map(
                lambda i: open_or_link_investigation(
                    pack_id="automotive_nhtsa", cluster_id=14, title="race"
                ),
                range(4),
            )
        )
    assert len(set(ids)) == 1
    with ops_con(read_only=True) as con:
        n = con.execute(
            "SELECT COUNT(*) FROM investigations WHERE pack_id = 'automotive_nhtsa'"
            " AND cluster_id = 14 AND status = 'open'"
        ).fetchone()[0]
    assert n == 1


def test_h45_claim_loser_links_or_stands_down(reset_ops_db):
    from src.frontline.live_intercept import open_or_link_investigation
    from src.jobs.registry import acquire_slice_claim

    assert acquire_slice_claim("inv:automotive_nhtsa:15", "other-worker") is True
    # Winner hasn't inserted yet: loser must NOT invent a row.
    with pytest.raises(RuntimeError, match="claimed by another worker"):
        open_or_link_investigation(pack_id="automotive_nhtsa", cluster_id=15)
    inv = open_or_link_investigation(pack_id="automotive_nhtsa", cluster_id=16)
    assert inv.startswith("inv_")
    assert open_or_link_investigation(pack_id="automotive_nhtsa", cluster_id=16) == inv


# ── 5.1 claim TTL + crash retry ──────────────────────────────────────────────


def test_h51_claim_expiry_takeover_and_heartbeat(reset_ops_db):
    from datetime import timedelta

    from src.data.timeutil import utc_now
    from src.data.warehouse import ops_con
    from src.jobs.registry import (
        acquire_close_claim,
        close_claim_owner,
        heartbeat_close_claim,
    )

    assert acquire_close_claim("int_ttl_1", "worker-a") is True
    assert acquire_close_claim("int_ttl_1", "worker-b") is False
    assert heartbeat_close_claim("int_ttl_1", "worker-a") is True
    assert heartbeat_close_claim("int_ttl_1", "worker-b") is False
    # Simulate crash: backdate beyond TTL → takeover succeeds.
    with ops_con() as con:
        con.execute(
            "UPDATE interaction_close_claims SET claimed_at = ? WHERE interaction_id = ?",
            [utc_now() - timedelta(seconds=3600), "int_ttl_1"],
        )
    assert acquire_close_claim("int_ttl_1", "worker-b") is True
    assert close_claim_owner("int_ttl_1") == "worker-b"


@pytest.mark.asyncio
async def test_h51_crash_retry_reuses_case(orchestrator_factory):
    """Worker dies after claim; retry takes over and reuses the case."""
    from datetime import timedelta

    from src.data.timeutil import utc_now
    from src.data.warehouse import ops_con
    from src.jobs.registry import acquire_close_claim

    orch, _ = orchestrator_factory()
    await orch.start()
    await orch.handle_customer_turn("My 2019 Honda CR-V grinds when I brake.")
    orch.ctx.slots.update({
        "entity_1": "2019", "entity_2": "HONDA", "entity_3": "CR-V",
        "category": "SERVICE BRAKES", "description": "grinding",
    })
    iid = orch.ctx.interaction_id
    # Dead worker: claimed, inserted a case, died before DONE.
    assert acquire_close_claim(iid, "dead-worker") is True
    with ops_con() as con:
        con.execute(
            """INSERT INTO cases (case_id, interaction_id, pack_id, created_at,
               category, description_summary, onset, severity, severity_source,
               priority, safety_flags, status)
               VALUES ('case_crash_1', ?, 'automotive_nhtsa', ?, 'SERVICE BRAKES',
               'd', ?, 'Medium', 'rules', 2, '{}', 'open')""",
            [iid, utc_now(), utc_now()],
        )
        con.execute(
            "UPDATE interaction_close_claims SET claimed_at = ? WHERE interaction_id = ?",
            [utc_now() - timedelta(seconds=3600), iid],
        )
    # Retry takes over the expired claim and must reuse, not duplicate.
    await orch._move_to_closing()
    assert orch.ctx.case_id == "case_crash_1"
    assert orch.ctx.state == "DONE"
    with ops_con(read_only=True) as con:
        n = con.execute(
            "SELECT COUNT(*) FROM cases WHERE interaction_id = ?", [iid]
        ).fetchone()[0]
    assert n == 1


# ── 7.2 case_kind ────────────────────────────────────────────────────────────


def test_h72_audit_reviews_excluded_from_corpus(reset_ops_db, seed_automotive_pack):
    from datetime import timedelta

    from src.data.timeutil import utc_now
    from src.data.warehouse import ops_con
    from src.frontline.analytics import cross_pack_patterns, financial_impact
    from src.qubot.retrievers import case_funnel, live_risk

    now = utc_now()
    with ops_con() as con:
        for cid, kind in (("case_real_1", "customer"), ("case_audit_1", "audit_review")):
            con.execute(
                """INSERT INTO cases (case_id, interaction_id, pack_id, created_at,
                   category, description_summary, onset, severity, severity_source,
                   priority, safety_flags, status, case_kind, cluster_match_id)
                   VALUES (?, 'int_k', 'automotive_nhtsa', ?, 'SERVICE BRAKES', 'd',
                   ?, 'Medium', 'rules', 2, '{}', 'open', ?, 14)""",
                [cid, now, now, kind],
            )
    assert case_funnel()["cases_created"] == 1
    risks = live_risk(30)
    mine = [r for r in risks if int(r["cluster_id"]) == 14]
    assert mine and mine[0]["live_case_count"] == 1
    fin = financial_impact(pack_id="automotive_nhtsa")
    assert sum(e["case_count"] for e in fin["estimates"]) == 1
    pats = cross_pack_patterns()
    assert pats["count"] == 0  # single pack → pack_specific, not a pattern


@pytest.mark.asyncio
async def test_h72_mismatch_tags_audit_review(orchestrator_factory):
    from src.data.warehouse import ops_con
    from src.qubot.auditor import _mark_case_needs_review

    orch, _ = orchestrator_factory()
    await _drive_to_done(orch)()
    _mark_case_needs_review(orch.ctx.case_id)
    with ops_con(read_only=True) as con:
        row = con.execute(
            "SELECT status, case_kind FROM cases WHERE case_id = ?",
            [orch.ctx.case_id],
        ).fetchone()
    assert row[0] == "pending_followup" and row[1] == "audit_review"


# ── 8.1 exposure + as-of ─────────────────────────────────────────────────────


def test_h81_exposure_rates_and_labels():
    from src.ml_runtime.anomalies import score_weekly_slices, set_exposure  # noqa

    counts = {}
    for w in range(10, 15):
        counts[(f"2024-W{w:02d}", "CAT", "ENT")] = 2
    counts[("2024-W15", "CAT", "ENT")] = 20
    plain = score_weekly_slices(counts, pack_id="p")
    spike = next(r for r in plain if r["iso_week"] == "2024-W15")
    assert spike["is_anomaly"] is True and spike["normalized"] is False
    # Same counts, but exposure doubled in W15 (sales spike): rate is flat.
    exp = {(f"2024-W{w:02d}", "CAT", "ENT"): 100.0 for w in range(10, 16)}
    exp[("2024-W15", "CAT", "ENT")] = 1000.0
    normed = score_weekly_slices(counts, pack_id="p", exposure=exp)
    spike2 = next(r for r in normed if r["iso_week"] == "2024-W15")
    assert spike2["normalized"] is True
    assert spike2["is_anomaly"] is False, "rate did not move — must not flag"


def test_h81_backtest_as_of(tmp_path, monkeypatch):
    from datetime import datetime, timedelta

    from src.backtest.engine import run_backtest
    from src.data.warehouse import apply_domain_schema, domain_con

    monkeypatch.setenv("DOMAIN_DB_PATH", str(tmp_path))
    pack = "asof_pack"
    t0 = datetime(2024, 1, 1)
    with domain_con(pack, read_only=False) as con:
        apply_domain_schema(con)
        con.execute(
            """INSERT INTO records (record_id, occurred_at, received_at, entity_2,
               category, text, source) VALUES ('R1', ?, ?, 'HONDA', 'SERVICE BRAKES', 'q', 'NHTSA')""",
            [t0, t0],
        )
        con.execute(
            """INSERT INTO clusters (cluster_id, pack_id, top_terms, category,
               record_count, first_seen, last_seen) VALUES (1000, ?, '["q"]',
               'SERVICE BRAKES', 1, ?, ?)""",
            [pack, t0, t0 + timedelta(days=7)],
        )
        con.execute(
            "INSERT INTO cluster_assignments (record_id, cluster_id, distance) VALUES ('R1', 1000, 0.2)"
        )
        con.execute(
            """INSERT INTO advisories (advisory_id, issued_at, scope_category, summary)
               VALUES ('ADV-EARLY', ?, 'SERVICE BRAKES', 'x')""",
            [t0 + timedelta(days=60)],
        )
        con.execute(
            """INSERT INTO advisories (advisory_id, issued_at, scope_category, summary)
               VALUES ('ADV-LATE', ?, 'SERVICE BRAKES', 'x')""",
            [t0 + timedelta(days=300)],
        )
    # As of day 100: only the early advisory existed → late one excluded.
    rows = run_backtest(pack, as_of=t0 + timedelta(days=100))
    advs = {r["advisory_id"] for r in rows}
    assert "ADV-EARLY" in advs and "ADV-LATE" not in advs
    assert all(r["as_of"] is not None for r in rows)
    full = run_backtest(pack)
    assert {r["advisory_id"] for r in full} == {"ADV-EARLY", "ADV-LATE"}


# ── 8.4 fix controls ─────────────────────────────────────────────────────────


def test_h84_controls_inconclusive_reopen_copq(tmp_path, monkeypatch):
    from datetime import datetime, timedelta

    from src.data.warehouse import apply_domain_schema, domain_con
    from src.enterprise.fix_effectiveness import (
        is_reopen,
        measure_effectiveness,
        reopen_window_days,
    )
    from src.frontline.analytics import financial_impact

    monkeypatch.setenv("DOMAIN_DB_PATH", str(tmp_path))
    pack = "fix_pack"
    pivot = datetime(2024, 6, 1)
    with domain_con(pack, read_only=False) as con:
        apply_domain_schema(con)
        n = 0
        for w in range(4):  # 4 pre weeks, 6 each
            for i in range(6):
                n += 1
                con.execute(
                    """INSERT INTO records (record_id, occurred_at, received_at,
                       entity_2, category, text, source) VALUES (?, ?, ?, 'HONDA',
                       'SERVICE BRAKES', 'q', 'NHTSA')""",
                    [f"B-{w}-{i}", pivot - timedelta(weeks=4 - w), pivot - timedelta(weeks=4 - w)],
                )
        for i in range(2):  # post: fixed slice drops to ~0
            con.execute(
                """INSERT INTO records (record_id, occurred_at, received_at,
                   entity_2, category, text, source) VALUES (?, ?, ?, 'HONDA',
                   'SERVICE BRAKES', 'q', 'NHTSA')""",
                [f"A-{i}", pivot + timedelta(weeks=9), pivot + timedelta(weeks=9)],
            )
        for w in range(4):  # control slice flat at 6 throughout
            for i in range(6):
                con.execute(
                    """INSERT INTO records (record_id, occurred_at, received_at,
                       entity_2, category, text, source) VALUES (?, ?, ?, 'FORD',
                       'SERVICE BRAKES', 'q', 'NHTSA')""",
                    [f"C-{w}-{i}", pivot - timedelta(weeks=4 - w), pivot - timedelta(weeks=4 - w)],
                )
        for i in range(6):
            con.execute(
                """INSERT INTO records (record_id, occurred_at, received_at,
                   entity_2, category, text, source) VALUES (?, ?, ?, 'FORD',
                   'SERVICE BRAKES', 'q', 'NHTSA')""",
                [f"C9-{i}", pivot + timedelta(weeks=9), pivot + timedelta(weeks=9)],
            )
        con.execute(
            """INSERT INTO records (record_id, occurred_at, received_at, entity_2,
               category, entity_key, text, source) VALUES ('REOPEN-1', ?, ?, 'HONDA',
               'SERVICE BRAKES', '2019|HONDA|CR-V', 'q', 'NHTSA')""",
            [pivot + timedelta(days=30), pivot + timedelta(days=30)],
        )
    m = measure_effectiveness(
        pack_id=pack, fixed_at=pivot, category="SERVICE BRAKES",
        entity_2="HONDA", window_days=70, control_entity_2="FORD",
    )
    assert m["conclusive"] is True
    assert m["diff_in_diff"] is not None and m["diff_in_diff"] < 0
    short = measure_effectiveness(
        pack_id=pack, fixed_at=pivot, category="SERVICE BRAKES",
        entity_2="HONDA", window_days=14,
    )
    assert short["conclusive"] is False and short["improved"] is False
    assert reopen_window_days() == 90
    assert is_reopen(pack, entity_key="2019|HONDA|CR-V", category="SERVICE BRAKES",
                     fixed_at=pivot)["reopened"] is True
    assert is_reopen(pack, entity_key="2019|HONDA|CR-V", category="SERVICE BRAKES",
                     fixed_at=pivot - timedelta(days=400))["reopened"] is False
    fin = financial_impact(pack_id="automotive_nhtsa")
    assert "portfolio_risk_range_usd" in fin
    lo, hi = fin["portfolio_risk_range_usd"]
    assert lo <= fin["portfolio_risk_usd"] <= hi


# ── X.5 WAL fallback ─────────────────────────────────────────────────────────


def test_hx5_safety_wal_and_replay(reset_ops_db, seed_automotive_pack, monkeypatch):
    import src.ledger.writer as _w
    from src.ledger import AgentAction, record_action
    from src.ledger.writer import replay_ledger_wal

    real_con = _w.ops_con

    def _down(*a, **k):
        raise ConnectionError("db is down")

    monkeypatch.setattr(_w, "ops_con", _down)
    try:
        aid = record_action(AgentAction(
            interaction_id="int_wal", agent="orchestrator",
            action_type="escalation_script_emitted",
            output_summary="pull over now",
        ))
        assert aid, "safety output must be delivered from WAL, not raise"
        with pytest.raises(ConnectionError):
            record_action(AgentAction(
                interaction_id="int_wal", agent="orchestrator",
                action_type="greeting_emitted", output_summary="hi",
            ))
        from src.ledger.writer import _wal_path

        assert _wal_path().is_file()
    finally:
        monkeypatch.setattr(_w, "ops_con", real_con)
    report = replay_ledger_wal()
    assert report["replayed"] == 1 and report["remaining"] == 0
    from src.data.warehouse import ops_con
    from src.ledger import list_actions

    assert any(
        "replayed-from-wal" in (a.get("output_summary") or "")
        for a in list_actions("int_wal")
    )
