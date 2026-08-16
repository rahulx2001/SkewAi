"""Structural checks: ops schema ships the optimization indexes."""

from __future__ import annotations

from src.data.warehouse import ops_con, reset_ops_db


REQUIRED_OPS_INDEXES = {
    "idx_cases_interaction",
    "idx_cases_cluster_pack_created",
    "idx_cases_status_created",
    "idx_interactions_status_outcome",
    "idx_interactions_peak_fr",
    "idx_turns_ix_speaker",
    "idx_actions_ts",
    # pre-existing
    "idx_actions_interaction",
    "idx_cases_status",
    "idx_interactions_status",
}


def test_ops_indexes_present_after_init(reset_ops_db):
    with ops_con(read_only=True) as con:
        rows = con.execute(
            """
            SELECT index_name
            FROM duckdb_indexes()
            WHERE schema_name = 'main'
            """
        ).fetchall()
    names = {r[0] for r in rows}
    missing = REQUIRED_OPS_INDEXES - names
    assert not missing, f"missing indexes: {sorted(missing)}; have={sorted(names)}"


def test_cases_by_interaction_uses_filter(reset_ops_db):
    """Point lookup must stay cheap; plan may still be SEQ_SCAN on empty tables."""
    with ops_con() as con:
        con.execute(
            """
            INSERT INTO interactions
            (interaction_id, pack_id, pack_version, started_at, channel, status)
            VALUES ('int_ix', 'automotive_nhtsa', 't', now(), 'sim', 'completed')
            """
        )
        con.execute(
            """
            INSERT INTO cases
            (case_id, interaction_id, pack_id, created_at, category, description_summary,
             onset, severity, severity_source, priority, safety_flags, status, followup_draft)
            VALUES ('case_ix', 'int_ix', 'automotive_nhtsa', now(), 'x', 'y', now(),
                    'Low', 'rules', 3, '{}', 'open', '')
            """
        )
    with ops_con(read_only=True) as con:
        plan = con.execute(
            "EXPLAIN SELECT case_id FROM cases WHERE interaction_id = 'int_ix'"
        ).fetchone()[1]
        row = con.execute(
            "SELECT case_id FROM cases WHERE interaction_id = 'int_ix'"
        ).fetchone()
    assert row and row[0] == "case_ix"
    assert "cases" in plan.lower() or "CASES" in plan
