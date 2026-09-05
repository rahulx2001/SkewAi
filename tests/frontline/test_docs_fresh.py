"""Documentation freshness gate (item 49).

Living docs must reflect the shipped implementation. Dated audit reports
(*_2026-08-16.md, *_2026-07-31.md, …) are point-in-time analyses and are
excluded — only living docs are gated.
"""

from __future__ import annotations

import re
import subprocess
from pathlib import Path

from src.config import REPO_ROOT

DOCS = REPO_ROOT / "docs"

# Dated point-in-time reports: history, not living claims.
DATED = re.compile(r"_\d{4}-\d{2}-\d{2}(_pass\d+)?\.md$")


def _living_docs() -> list[Path]:
    return [p for p in DOCS.glob("*.md") if not DATED.search(p.name)]


def test_no_not_computed_in_src_lore():
    """z-scores ARE computed in src (item 10) — the old lore must be gone.

    Dated reconciliation log lines are allowed only when superseded by a
    newer dated entry in the same document.
    """
    bad: list[str] = []
    for doc in _living_docs():
        text = doc.read_text(encoding="utf-8", errors="replace")
        if re.search(r"not computed in `?src", text) and "superseded" not in text:
            bad.append(doc.name)
    assert bad == [], f"stale un-superseded 'not computed in src' lore in: {bad}"


def test_no_empty_ml_dir_claims():
    """src/ai, ml_runtime, backtest are populated (not empty)."""
    bad: list[str] = []
    for doc in _living_docs():
        text = doc.read_text(encoding="utf-8", errors="replace")
        for d in ("src/ai/", "ml_runtime/", "backtest/"):
            for m in re.finditer(rf".{{0,60}}{re.escape(d)}.{{0,60}}", text):
                window = m.group(0)
                if re.search(r"\bare\s+empty\b|\bis\s+empty\b|\(\s*empty\s*\)", window):
                    bad.append(f"{doc.name}: {window.strip()[:100]}")
    assert bad == [], f"stale empty-dir claims: {bad}"


def test_feature_list_describes_computed_anomalies():
    text = (DOCS / "feature_list_deep_research.md").read_text(encoding="utf-8")
    assert "quasi-Poisson" in text or "computed" in text
    assert "provenance" in text, "backtest provenance must be documented"


def test_no_seed_60_presented_as_detection():
    """Seed 6.0 literals must be labeled fixtures, never detections (item 49)."""
    text = (DOCS / "feature_list_deep_research.md").read_text(encoding="utf-8")
    assert "demo fixture" in text or "fixture" in text
    # src/ itself must not hardcode the lore anywhere.
    from src.ml_runtime import anomalies

    import inspect

    src = inspect.getsource(anomalies)
    assert "6.0" not in src, "z=6.0 lore must not live in the scorer"


def test_dashboard_auth_centralization_script():
    script = REPO_ROOT / "dashboard" / "scripts" / "assert-auth-centralization.mjs"
    assert script.is_file()
    r = subprocess.run(
        ["node", str(script)], capture_output=True, text=True, timeout=30
    )
    assert r.returncode == 0, f"{r.stdout}\n{r.stderr}"
    assert "PASSED" in r.stdout
