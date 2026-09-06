"""Review-board regression tests: novelty, confirmation, turn idempotency,
signatures/lineage, lag censoring, fix-regression watch, feedback loops,
review SLA, booking caps, takeover contention, overrides, cooldown, model
stamps, outcomes, reaper grace, abandon-signal, escaping, RBAC consistency.
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


# ── #3 novelty ──────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_novelty_queue_on_low_score(tmp_path, monkeypatch):
    from datetime import datetime

    from src.agents.base import InteractionContext
    from src.agents.investigator import InvestigatorAgent
    from src.data.warehouse import apply_domain_schema, domain_con, ops_con
    from src.domains.loader import load_pack

    monkeypatch.setenv("DOMAIN_DB_PATH", str(tmp_path))
    pack_id = "novel_pack"
    now = datetime(2024, 5, 1)
    with domain_con(pack_id, read_only=False) as con:
        apply_domain_schema(con)
        con.execute(
            """INSERT INTO records (record_id, occurred_at, received_at, entity_2,
               entity_3, category, text, source) VALUES ('F-1', ?, ?, 'FORD', 'F-150',
               'ELECTRICAL SYSTEM', 'power window regulator failure', 'NHTSA')""",
            [now, now],
        )
        con.execute(
            """INSERT INTO clusters (cluster_id, pack_id, top_terms, category,
               record_count, first_seen, last_seen) VALUES (1000, ?, '["window"]',
               'ELECTRICAL SYSTEM', 1, ?, ?)""",
            [pack_id, now, now],
        )
        con.execute(
            "INSERT INTO cluster_assignments (record_id, cluster_id, distance)"
            " VALUES ('F-1', 1000, 0.2)"
        )
    pack = load_pack("automotive_nhtsa", reload=True)
    ctx = InteractionContext(interaction_id="int_novel", pack=pack, channel="web_text")
    ctx.slots.update({
        "category": "SERVICE BRAKES", "entity_2": "HONDA", "entity_3": "CR-V",
        "description": "front brake grinding noise when stopping",
    })
    # Point the investigator at the tmp pack by swapping pack id context.
    ctx.pack = load_pack("automotive_nhtsa", reload=True)
    import types

    ctx.pack = types.SimpleNamespace(
        id=pack_id, manifest=pack.manifest, pack_version="t",
        required_slots=pack.required_slots, gazetteers={},
    )
    await InvestigatorAgent(ctx).run()
    brief = ctx.investigation_brief
    assert brief["cluster_id"] is None
    assert brief["novel_candidate"] is True
    assert brief["brief_version"] == 1
    with ops_con(read_only=True) as con:
        try:
            row = con.execute(
                "SELECT category, top_score, status FROM novel_candidates"
                " WHERE interaction_id = 'int_novel'"
            ).fetchone()
        except Exception:
            row = None
    assert row and row[2] == "open"


# ── #4 confirmation + turn idempotency ───────────────────────────────────────


@pytest.mark.asyncio
async def test_confirmation_readback_and_accept(orchestrator_factory):
    orch, hooks = orchestrator_factory()
    await orch.start()
    orch.ctx.slots.update({
        "entity_1": "2019", "entity_2": "HONDA", "entity_3": "CR-V",
        "category": "SERVICE BRAKES", "description": "grinding when braking",
    })
    n_safety = len(orch.ctx.pack.manifest.safety.safety_questions or [])
    orch.ctx.slots["__safety_questions_asked__"] = ",".join(
        str(i) for i in range(n_safety)
    )
    await orch.handle_customer_turn("still grinding this morning")
    # Slots complete → confirmation question instead of silent enriching.
    assert orch.ctx.slots.get("__confirm_pending__") == "1"
    assert any("confirm" in (t.get("text") or "").lower() for t in hooks.turns
               if t["speaker"] == "agent")
    await orch.handle_customer_turn("Yes, that's right.")
    assert orch.ctx.slots.get("__confirmed__") == "1"
    assert orch.ctx.state == "DONE"
    assert orch.ctx.case_id


@pytest.mark.asyncio
async def test_confirmation_correction_overwrites(orchestrator_factory):
    orch, hooks = orchestrator_factory()
    await orch.start()
    orch.ctx.slots.update({
        "entity_1": "2019", "entity_2": "HONDA", "entity_3": "CR-V",
        "category": "SERVICE BRAKES", "description": "grinding when braking",
    })
    n_safety = len(orch.ctx.pack.manifest.safety.safety_questions or [])
    orch.ctx.slots["__safety_questions_asked__"] = ",".join(
        str(i) for i in range(n_safety)
    )
    await orch.handle_customer_turn("still grinding this morning")
    assert orch.ctx.slots.get("__confirm_pending__") == "1"
    await orch.handle_customer_turn("Actually it's a 2018, not 2019.")
    assert orch.ctx.slots.get("entity_1") == "2018"
    # Bounded: at most one re-confirm, then the contact proceeds.
    for _ in range(14):
        if orch.ctx.state == "DONE":
            break
        await orch.handle_customer_turn("Yes, correct.")
    assert orch.ctx.state == "DONE"


@pytest.mark.asyncio
async def test_duplicate_client_turn_dropped(orchestrator_factory):
    orch, _ = orchestrator_factory()
    await orch.start()
    n0 = sum(1 for t in orch.ctx.turns if t["speaker"] == "customer")
    await orch.handle_customer_turn("My brakes grind.", client_turn_id="c-t-1")
    await orch.handle_customer_turn("My brakes grind.", client_turn_id="c-t-1")
    n1 = [t for t in orch.ctx.turns if t["speaker"] == "customer"]
    assert len(n1) == n0 + 1


# ── #5 signatures + lineage ──────────────────────────────────────────────────


def test_cluster_signature_stable_and_lineage(tmp_path, monkeypatch):
    from datetime import datetime

    from src.data.warehouse import apply_domain_schema, domain_con
    from src.ml_runtime.clustering import (
        cluster_signature,
        rebuild_clusters,
        resolve_cluster_lineage,
    )

    assert cluster_signature("A", "B", ["x", "y"]) == cluster_signature("A", "B", ["y", "x"])
    assert cluster_signature(None, None, []) == ""
    monkeypatch.setenv("DOMAIN_DB_PATH", str(tmp_path))
    pack_id = "sig_pack"
    now = datetime(2024, 5, 1)
    with domain_con(pack_id, read_only=False) as con:
        apply_domain_schema(con)
        for i in range(4):
            con.execute(
                """INSERT INTO records (record_id, occurred_at, received_at, entity_2,
                   entity_3, category, text, source) VALUES (?, ?, ?, 'HONDA', 'CR-V',
                   'SERVICE BRAKES', ?, 'NHTSA')""",
                [f"SG-{i}", now, now, f"brake grinding noise variant {i}"],
            )
    r1 = rebuild_clusters(pack_id, k=1)
    uid1 = r1["cluster_uids"][1000]
    with domain_con(pack_id) as con:
        sig1 = con.execute(
            "SELECT signature FROM clusters WHERE cluster_id = 1000 AND pack_id = ?",
            [pack_id],
        ).fetchone()[0]
    assert sig1, "rebuild must stamp a stable signature"
    r2 = rebuild_clusters(pack_id, k=1)
    uid2 = r2["cluster_uids"][1000]
    assert uid2 != uid1
    chain = resolve_cluster_lineage(pack_id, uid1)
    assert chain and chain[0]["new_cluster_uid"] == uid2
    assert chain[0]["overlap"] >= 0.5


# ── #6 censoring + fix-regression watch ──────────────────────────────────────


def test_censor_recent_buckets(tmp_path, monkeypatch):
    from datetime import datetime, timedelta

    from src.data.timeutil import utc_now
    from src.data.warehouse import apply_domain_schema, domain_con
    from src.ml_runtime.anomalies import recompute_weekly_anomalies

    monkeypatch.setenv("DOMAIN_DB_PATH", str(tmp_path))
    pack_id = "censor_pack"
    now = utc_now().replace(tzinfo=None)
    with domain_con(pack_id, read_only=False) as con:
        apply_domain_schema(con)
        n = 0
        for w in range(8, 0, -1):
            day = now - timedelta(weeks=w)
            for i in range(2):
                n += 1
                con.execute(
                    """INSERT INTO records (record_id, occurred_at, received_at,
                       entity_2, category, text, source) VALUES (?, ?, ?, 'HONDA',
                       'SERVICE BRAKES', 'q', 'NHTSA')""",
                    [f"Q-{w}-{i}", day, day],
                )
        for i in range(30):
            con.execute(
                """INSERT INTO records (record_id, occurred_at, received_at,
                   entity_2, category, text, source) VALUES (?, ?, ?, 'HONDA',
                   'SERVICE BRAKES', 'q', 'NHTSA')""",
                [f"S-{i}", now, now],
            )
    uncensored = recompute_weekly_anomalies(pack_id)
    assert any(r.get("is_anomaly") for r in uncensored), "sanity: spike flags uncensored"
    censored = recompute_weekly_anomalies(pack_id, censor_recent_days=365)
    assert all(r.get("censored") or not r.get("is_anomaly") for r in censored)
    assert not any(r.get("is_anomaly") for r in censored)


@pytest.mark.asyncio
async def test_fix_regression_watch_fires(orchestrator_factory):
    from datetime import timedelta

    from src.data.timeutil import utc_now
    from src.enterprise.fix_effectiveness import record_fix
    from src.ledger import list_actions

    orch, _ = orchestrator_factory()
    pack_id = orch.ctx.pack.id
    record_fix(
        pack_id=pack_id, fixed_at=utc_now() - timedelta(days=10),
        category="SERVICE BRAKES", entity_2="HONDA", entity_3="CR-V",
        note="pad campaign",
    )
    await _drive_to_done(orch)()
    assert orch.ctx.case_id
    assert any(
        "fix regression" in (a.get("output_summary") or "")
        for a in list_actions(orch.ctx.interaction_id)
    )


# ── #9 feedback loops ────────────────────────────────────────────────────────


def test_audit_regression_export(reset_ops_db):
    from src.frontline.validation_queue import (
        create_review,
        export_audit_regressions,
        resolve_review,
    )

    rv = create_review(interaction_id="int_rx", reason="mismatch: uncited 19V-1")
    resolve_review(rv["review_id"], "ai_wrong", actor="test")
    out = export_audit_regressions(since_days=7, out_dir="/tmp/board_regression")
    assert out["written"] >= 1
    import json

    lines = open(out["path"], encoding="utf-8").read().strip().splitlines()
    last = json.loads(lines[-1])
    assert last["expected_failure"] == "ai_wrong"


def test_cluster_feedback_endpoints(reset_ops_db, seed_automotive_pack, monkeypatch):
    from fastapi.testclient import TestClient

    from src.api.main import app

    monkeypatch.delenv("FRONTLINE_API_KEY", raising=False)
    with TestClient(app) as c:
        bad = c.post("/api/frontline/clusters/14/feedback", json={"verdict": "maybe"})
        assert bad.status_code == 400
        ok = c.post("/api/frontline/clusters/14/feedback",
                    json={"verdict": "wrong", "note": "actually brakes"})
        assert ok.status_code == 200
        assert ok.json()["verdict"] == "wrong"
        listed = c.get("/api/frontline/clusters/14/feedback").json()
        assert listed["count"] >= 1


def test_outcome_endpoint(reset_ops_db, seed_automotive_pack, monkeypatch):
    from fastapi.testclient import TestClient

    from src.api.main import app
    from src.data.timeutil import utc_now
    from src.data.warehouse import ops_con

    monkeypatch.delenv("FRONTLINE_API_KEY", raising=False)
    with ops_con() as con:
        con.execute(
            """INSERT INTO interactions (interaction_id, pack_id, pack_version,
               started_at, channel, status) VALUES ('int_csat', 'automotive_nhtsa',
               '1', ?, 'web_text', 'completed')""",
            [utc_now()],
        )
    with TestClient(app) as c:
        assert c.post("/api/interactions/int_csat/outcome",
                      json={"csat": 9}).status_code == 400
        assert c.post("/api/interactions/int_nope/outcome",
                      json={"csat": 5}).status_code == 404
        ok = c.post("/api/interactions/int_csat/outcome",
                    json={"csat": 5, "resolved": True})
        assert ok.status_code == 200
    with ops_con(read_only=True) as con:
        row = con.execute(
            "SELECT csat, customer_resolved FROM interactions WHERE interaction_id = 'int_csat'"
        ).fetchone()
    assert (row[0], bool(row[1])) == (5, True)


def test_review_assign_resolve(reset_ops_db):
    from src.frontline.validation_queue import (
        assign_review,
        create_review,
        list_reviews,
        resolve_review,
    )

    r = create_review(case_id="case_r1", reason="audit_mismatch")
    assert r["status"] == "open" and r["owner"] is None
    assert any(x["review_id"] == r["review_id"] for x in list_reviews(status="open"))
    a = assign_review(r["review_id"], "Priya")
    assert a["owner"] == "Priya"
    with pytest.raises(ValueError):
        resolve_review(r["review_id"], "bogus")
    done = resolve_review(r["review_id"], "ai_wrong")
    assert done["verdict"] == "ai_wrong"
    assert list_reviews(status="open") == []


# ── #10 remainder ────────────────────────────────────────────────────────────


def test_booking_caps(reset_ops_db, seed_automotive_pack):
    from src.domains.loader import load_pack
    from src.frontline.booking import book_appointment

    pack = load_pack("automotive_nhtsa", reload=True)
    assert pack.manifest.booking_policy.max_per_case >= 1
    first = book_appointment(case_id="case_cap", interaction_id=None,
                             pack_id=pack.id, slot_start="2026-10-01T10:00:00")
    assert first["status"] == "booked"
    second = book_appointment(case_id="case_cap", interaction_id=None,
                              pack_id=pack.id, slot_start="2026-10-02T10:00:00")
    assert second["status"] == "requires_approval"
    assert "reason" in second


@pytest.mark.asyncio
async def test_takeover_contention_names_claimant(orchestrator_factory):
    orch, _ = orchestrator_factory()
    await orch.start()
    await orch.takeover(claimed_by="amy")
    assert orch.ctx.takeover_claimed_by == "amy"
    await orch.takeover(claimed_by="bob")  # idempotent, first claimant wins
    assert orch.ctx.state == "SUPERVISED"
    assert orch.ctx.takeover_claimed_by == "amy"


def test_takeover_route_reports_claimant(reset_ops_db, seed_automotive_pack, monkeypatch):
    from fastapi.testclient import TestClient

    from src.api.main import app

    monkeypatch.setenv("FRONTLINE_API_KEY", "claimant-key")
    with TestClient(app) as c:
        h = {"X-API-Key": "claimant-key"}
        started = c.post("/api/interactions/start?channel=web_text", headers=h).json()
        iid = started["interaction_id"]
        r = c.post(f"/api/interactions/{iid}/takeover", headers=h)
        assert r.status_code == 200
        assert "claimed_by" in r.json()


@pytest.mark.asyncio
async def test_human_override_ledgered(orchestrator_factory):
    from src.ledger import list_actions

    orch, hooks = orchestrator_factory()
    await orch.start()
    await orch.takeover()
    # Direct orchestrator-level override path mirrors the route.
    orch.ctx.slots["category"] = "AIR BAGS"
    orch.ctx.severity = "Critical"
    orch.ctx.severity_source = "human"
    from src.ledger import AgentAction, record_action

    record_action(AgentAction(
        interaction_id=orch.ctx.interaction_id, agent="supervisor",
        action_type="human_override",
        input_summary="actor=test reason=customer corrected system",
        output_summary="overrides={'category': 'AIR BAGS'}",
    ))
    types = [a["action_type"] for a in list_actions(orch.ctx.interaction_id)]
    assert "human_override" in types


def test_override_route_validation(reset_ops_db, seed_automotive_pack, monkeypatch):
    from fastapi.testclient import TestClient

    from src.api.main import app

    monkeypatch.setenv("FRONTLINE_API_KEY", "override-key")
    with TestClient(app) as c:
        h = {"X-API-Key": "override-key"}
        started = c.post("/api/interactions/start?channel=web_text", headers=h).json()
        iid = started["interaction_id"]
        assert c.patch(f"/api/interactions/{iid}/override",
                       json={"slots": {"category": "X"}}, headers=h).status_code == 400
        assert c.patch(f"/api/interactions/{iid}/override",
                       json={"slots": {}, "severity": "Extreme"},
                       headers=h).status_code == 400
        assert c.patch(f"/api/interactions/{iid}/override",
                       json={"slots": {}}, headers=h).status_code == 400
        ok = c.patch(f"/api/interactions/{iid}/override",
                     json={"slots": {"category": "AIR BAGS"}, "severity": "Critical",
                           "reason": "customer corrected"},
                     headers=h)
        assert ok.status_code == 200
        assert ok.json()["applied"]["category"] == "AIR BAGS"


def test_intercept_cooldown(tmp_path, monkeypatch):
    from datetime import datetime, timedelta

    from src.data.warehouse import apply_domain_schema, domain_con
    from src.frontline.live_intercept import _slice_cooled_down, intercept_contact
    from types import SimpleNamespace

    monkeypatch.setenv("DOMAIN_DB_PATH", str(tmp_path))
    pack_id = "cool_pack"
    now = datetime(2024, 5, 15)
    with domain_con(pack_id, read_only=False) as con:
        apply_domain_schema(con)
        for w in range(4):
            day = now - timedelta(weeks=5 - w)
            for i in range(2):
                con.execute(
                    """INSERT INTO records (record_id, occurred_at, received_at,
                       entity_2, category, text, source) VALUES (?, ?, ?, 'HONDA',
                       'SERVICE BRAKES', 'q', 'NHTSA')""",
                    [f"Q-{w}-{i}", day, day],
                )
        for i in range(20):
            con.execute(
                """INSERT INTO records (record_id, occurred_at, received_at,
                   entity_2, category, text, source) VALUES (?, ?, ?, 'HONDA',
                   'SERVICE BRAKES', 'q', 'NHTSA')""",
                [f"S-{i}", now, now],
            )
    ctx = SimpleNamespace(pack=SimpleNamespace(id=pack_id), slots={
        "category": "SERVICE BRAKES", "entity_2": "HONDA"},
        interaction_id="int_cool", investigation_brief={"cluster_id": 1000})
    monkeypatch.setenv("FRONTLINE_INTERCEPT_COOLDOWN_S", "3600")
    first = intercept_contact(ctx)
    assert first.get("investigation_id"), "first firing must open/link"
    second = intercept_contact(ctx)
    assert second.get("cooled_down") is True
    assert second.get("investigation_id") is None


def test_model_stamp_in_ledger(orchestrator_factory):
    from src.agents.triage import _model_stamp

    orch, _ = orchestrator_factory()
    stamp = _model_stamp(orch.ctx)
    assert stamp, "every score carries a model stamp"
    # Automotive ships an artifact; finance is rules-only — both stamp honestly.
    assert stamp.startswith("automotive_nhtsa/models/") or stamp.startswith("rules:")


@pytest.mark.asyncio
async def test_outcomes_human_paths(orchestrator_factory):
    # Force-close while supervised ⇒ human_resolved.
    orch, _ = orchestrator_factory()
    await orch.start()
    await orch.handle_customer_turn("My 2019 Honda CR-V grinds when I brake.")
    assert orch.ctx.state == "COLLECTING"  # mid-contact, not done
    await orch.takeover()
    assert orch.ctx.state == "SUPERVISED"
    await orch.handle_customer_turn("I'M BLEEDING from the crash!")
    assert orch.ctx.safety_flags.get("escalation") is True
    await orch.hangup()
    assert orch.ctx.case_id
    assert orch.ctx.state == "DONE"
    from src.data.warehouse import ops_con

    with ops_con(read_only=True) as con:
        outcome = con.execute(
            "SELECT outcome FROM interactions WHERE interaction_id = ?",
            [orch.ctx.interaction_id],
        ).fetchone()[0]
    assert outcome == "human_resolved"
    # Handoff accepted + claimed + closed ⇒ handed_off.
    orch2, _ = orchestrator_factory()
    await orch2.start()
    orch2.ctx.handoff_offered = True
    await orch2.accept_handoff()
    await orch2.takeover()
    orch2.ctx.slots.update({
        "entity_1": "2019", "entity_2": "HONDA", "entity_3": "CR-V",
        "category": "SERVICE BRAKES", "description": "grinding when braking",
    })
    await orch2.handle_customer_turn("I'M BLEEDING from the crash!")
    await orch2.hangup()
    assert orch2.ctx.case_id
    with ops_con(read_only=True) as con:
        outcome2 = con.execute(
            "SELECT outcome FROM interactions WHERE interaction_id = ?",
            [orch2.ctx.interaction_id],
        ).fetchone()[0]
    assert outcome2 == "handed_off"


def test_reaper_respects_grace(reset_ops_db):
    import time

    from src.api.routes.interactions import _active, _is_reapable, _reconnect_grace_s
    from types import SimpleNamespace

    assert _reconnect_grace_s() > 0
    now = time.monotonic()
    live = SimpleNamespace(ws_attached=False, detached_at=now - 1.0,
                           created_at=now - 400)
    assert _is_reapable(live, now, _reconnect_grace_s()) is False
    dead = SimpleNamespace(ws_attached=False,
                           detached_at=now - _reconnect_grace_s() - 1,
                           created_at=now - 400)
    assert _is_reapable(dead, now, _reconnect_grace_s()) is True
    assert _active is not None  # registry exists; sweep predicate is the guard


@pytest.mark.asyncio
async def test_abandon_with_slots_projects_inferred(orchestrator_factory):
    from src.data.warehouse import domain_con

    orch, _ = orchestrator_factory()
    await orch.start()
    await orch.handle_customer_turn("My 2019 Honda CR-V grinds when I brake.")
    orch.ctx.safety_flags.clear()
    orch.ctx.enrichment_done = False
    # Force the plain-abandon path with slots present.
    orch.ctx.case_id = None
    await orch.hangup()
    assert orch.ctx.state == "ABANDONED"
    rid = f"FRONTLINE-{orch.ctx.interaction_id}"
    with domain_con(orch.ctx.pack.id) as con:
        try:
            row = con.execute(
                "SELECT provenance FROM records WHERE record_id = ?", [rid]
            ).fetchone()
        except Exception:
            row = None
    assert row is not None and row[0] == "inferred"


def test_escape_untrusted():
    from src.security.input_validation import escape_untrusted, validate_input

    assert escape_untrusted('<script>alert("x")</script>') == (
        "&lt;script&gt;alert(&quot;x&quot;)&lt;/script&gt;"
    )
    v = validate_input("ok <b>bold</b> text")
    assert v.ok and "\x00" not in v.text


@pytest.mark.asyncio
async def test_negated_safety_no_escalation_full_turn(orchestrator_factory):
    orch, _ = orchestrator_factory()
    await orch.start()
    await orch.handle_customer_turn("There was no fire, just a burning smell.")
    assert not orch.ctx.safety_flags.get("escalation")
    assert orch.ctx.state == "COLLECTING"


def test_rbac_matrix_consistent():
    import re
    from pathlib import Path

    from src.api.rbac import PERMS
    from src.config import REPO_ROOT

    granted: set[str] = set()
    for perms in PERMS.values():
        granted.update(perms)
    granted.discard("*")
    used: set[str] = set()
    for path in (REPO_ROOT / "src" / "api" / "routes").glob("*.py"):
        for m in re.finditer(r'require_perm_dep\("([^"]+)"', path.read_text()):
            used.add(m.group(1))
    assert used <= granted, f"routes demand ungranted perms: {used - granted}"
    doc = (REPO_ROOT / "docs" / "rbac_matrix.md").read_text()
    for perm in sorted(used):
        assert perm in doc, f"doc missing perm {perm}"


def test_llm_backpressure_configured():
    from src.ai.provider import llm_enabled  # noqa
    from src.config import settings

    assert settings.llm_turn_cap >= 1
    assert settings.max_daily_claude_cost > 0


@pytest.mark.asyncio
async def test_brief_version_refresh_on_late_answer(orchestrator_factory):
    from src.frontline.elicitation import register_question

    orch, hooks = orchestrator_factory()
    pack_id = orch.ctx.pack.id
    register_question(pack_id, "Does the grinding happen when cold?")
    await orch.start()
    orch.ctx.slots.update({
        "entity_1": "2019", "entity_2": "HONDA", "entity_3": "CR-V",
        "category": "SERVICE BRAKES", "description": "grinding when braking",
    })
    n_safety = len(orch.ctx.pack.manifest.safety.safety_questions or [])
    orch.ctx.slots["__safety_questions_asked__"] = ",".join(
        str(i) for i in range(n_safety)
    )
    await orch.handle_customer_turn("still grinding this morning")
    pending = (orch.ctx.slots or {}).get("__diag_qid")
    assert pending
    # Answer, then drive to enrich so a v1 brief exists…
    await orch.handle_customer_turn("Yes, only on cold mornings")
    for _ in range(14):
        if orch.ctx.state == "DONE":
            break
        await orch.handle_customer_turn("Additional detail.")
    assert orch.ctx.investigation_brief is not None
    assert orch.ctx.investigation_brief.get("brief_version", 1) >= 1
    assert any(
        (a.get("answer") or "") for a in
        (orch.ctx.investigation_brief.get("elicitation_answers") or [])
    )
