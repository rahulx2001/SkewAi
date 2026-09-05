"""Weekly trend chrome: reserved slots, not a stray vertical bar."""

from __future__ import annotations

import subprocess
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
DASH = REPO / "dashboard"
ASSERT = DASH / "scripts" / "assert-week-spark.mjs"
BOARD = DASH / "routes" / "EarlyWarningBoard.jsx"
RETRIEVERS = REPO / "src" / "qubot" / "retrievers.py"


def test_week_spark_helper_pads_single_week() -> None:
    assert ASSERT.is_file()
    r = subprocess.run(
        ["node", str(ASSERT)],
        cwd=DASH,
        capture_output=True,
        text=True,
        timeout=20,
    )
    assert r.returncode == 0, f"{r.stdout}\n{r.stderr}"
    assert "assert-week-spark: PASSED" in r.stdout
    assert "one week sits in a 6-slot track" in r.stdout


def test_early_warning_uses_week_spark_not_orphan_bar() -> None:
    src = BOARD.read_text(encoding="utf-8")
    assert "WeekSpark" in src
    assert 'className="spark"' not in src
    assert "width: 4px" not in src
    assert "from \"../src/ui/WeekSpark.jsx\"" in src or "from '../src/ui/WeekSpark.jsx'" in src


def test_live_risk_trend_query_groups_by_week() -> None:
    src = RETRIEVERS.read_text(encoding="utf-8")
    # Item 27: trends are scoped to the cluster's own (category, entity_2)
    # slice — still grouped by week, never a global trend.
    assert "GROUP BY category, entity_2, iso_week" in src
    assert "SUM(record_count)" in src
    assert "trend_scope" in src
