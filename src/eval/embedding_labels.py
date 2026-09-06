"""Human embedding-label store, import/export, and inter-annotator agreement.

This module never proposes a label. Sampling yields unlabeled items.
Acceptance gates must refuse coding-agent seeds and classes with κ < 0.70.
"""

from __future__ import annotations

import json
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any, Iterable

from src.data.timeutil import utc_now
from src.data.warehouse import ops_con
from src.ids import new_ulid

LABEL_CLASSES = (
    "paraphrase_positive",
    "hard_negative_same_category",
    "hard_negative_same_components",
    "multi_symptom",
    "negation_mention",
    "safety_true_positive",
    "safety_false_positive_trigger",
    "novel_true",
    "novel_false",
    "cross_entity_same_symptom",
)

KAPPA_MIN = 0.70
INELIGIBLE_SOURCES = frozenset(
    {"coding_agent_seed", "author_seed", "synthetic", "agent_proposed"}
)

EVAL_ITEMS_DDL = """
CREATE TABLE IF NOT EXISTS embedding_eval_items (
    eval_id            VARCHAR PRIMARY KEY,
    source_record_id   VARCHAR,
    candidate_record_id VARCHAR,
    query_text         TEXT NOT NULL,
    candidate_text     TEXT NOT NULL,
    category           VARCHAR,
    entity_2           VARCHAR,
    entity_3           VARCHAR,
    created_at         TIMESTAMP NOT NULL
)
"""

EVAL_LABELS_DDL = """
CREATE TABLE IF NOT EXISTS embedding_eval_labels (
    label_row_id         VARCHAR PRIMARY KEY,
    eval_id              VARCHAR NOT NULL,
    source_record_id     VARCHAR,
    label                VARCHAR NOT NULL,
    annotator_id         VARCHAR NOT NULL,
    adjudication_status  VARCHAR NOT NULL,
    adjudicator_id       VARCHAR,
    created_at           TIMESTAMP NOT NULL,
    disagreement_notes   VARCHAR
)
"""


def ensure_eval_tables(con) -> None:
    con.execute(EVAL_ITEMS_DDL)
    con.execute(EVAL_LABELS_DDL)


def enqueue_unlabeled_item(
    *,
    query_text: str,
    candidate_text: str,
    source_record_id: str | None = None,
    candidate_record_id: str | None = None,
    category: str | None = None,
    entity_2: str | None = None,
    entity_3: str | None = None,
) -> str:
    """Queue a pair for humans. Does not write a label."""
    eid = "eval_" + new_ulid()
    now = utc_now().replace(tzinfo=None)
    with ops_con() as con:
        ensure_eval_tables(con)
        con.execute(
            """
            INSERT INTO embedding_eval_items (
                eval_id, source_record_id, candidate_record_id, query_text,
                candidate_text, category, entity_2, entity_3, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            [
                eid,
                source_record_id,
                candidate_record_id,
                query_text,
                candidate_text,
                category,
                entity_2,
                entity_3,
                now,
            ],
        )
    return eid


def next_unlabeled_item(annotator_id: str) -> dict[str, Any] | None:
    """Return one item this annotator has not labeled. No scores attached."""
    aid = (annotator_id or "").strip()
    if not aid:
        raise ValueError("annotator_id is required")
    with ops_con(read_only=True) as con:
        try:
            row = con.execute(
                """
                SELECT i.eval_id, i.source_record_id, i.candidate_record_id,
                       i.query_text, i.candidate_text, i.category, i.entity_2, i.entity_3
                FROM embedding_eval_items i
                WHERE NOT EXISTS (
                    SELECT 1 FROM embedding_eval_labels l
                    WHERE l.eval_id = i.eval_id AND l.annotator_id = ?
                )
                ORDER BY i.created_at
                LIMIT 1
                """,
                [aid],
            ).fetchone()
        except Exception:
            return None
    if not row:
        return None
    return {
        "eval_id": row[0],
        "source_record_id": row[1],
        "candidate_record_id": row[2],
        "query_text": row[3],
        "candidate_text": row[4],
        "category": row[5],
        "entity_2": row[6],
        "entity_3": row[7],
    }


def submit_label(
    *,
    eval_id: str,
    annotator_id: str,
    label: str,
    source_record_id: str | None = None,
    notes: str = "",
) -> str:
    if label not in LABEL_CLASSES:
        raise ValueError(f"unknown label class {label!r}")
    if annotator_id.startswith("agent") or annotator_id.startswith("coding"):
        raise ValueError("coding-agent annotator_id is not allowed")
    if not annotator_id.startswith("human-"):
        raise ValueError("annotator_id must start with 'human-'")
    now = utc_now().replace(tzinfo=None)
    rid = "elbl_" + new_ulid()
    with ops_con() as con:
        ensure_eval_tables(con)
        existing = con.execute(
            """
            SELECT COUNT(*) FROM embedding_eval_labels
            WHERE eval_id = ? AND annotator_id = ? AND adjudicator_id IS NULL
            """,
            [eval_id, annotator_id],
        ).fetchone()
        if existing and int(existing[0]) > 0:
            raise ValueError("annotator already labeled this item")
        con.execute(
            """
            INSERT INTO embedding_eval_labels (
                label_row_id, eval_id, source_record_id, label, annotator_id,
                adjudication_status, adjudicator_id, created_at, disagreement_notes
            ) VALUES (?, ?, ?, ?, ?, 'single', NULL, ?, ?)
            """,
            [rid, eval_id, source_record_id, label, annotator_id, now, notes or None],
        )
        _refresh_agreement_status(con, eval_id)
    return rid


def adjudicate(
    *,
    eval_id: str,
    adjudicator_id: str,
    label: str,
    notes: str,
) -> str:
    if not adjudicator_id.startswith("human-"):
        raise ValueError("adjudicator_id must start with 'human-'")
    if label not in LABEL_CLASSES:
        raise ValueError(f"unknown label class {label!r}")
    rid = "elbl_" + new_ulid()
    now = utc_now().replace(tzinfo=None)
    with ops_con() as con:
        ensure_eval_tables(con)
        annotators = [
            r[0]
            for r in con.execute(
                "SELECT DISTINCT annotator_id FROM embedding_eval_labels WHERE eval_id = ?",
                [eval_id],
            ).fetchall()
        ]
        if adjudicator_id in annotators:
            raise ValueError("adjudicator must be a third reviewer")
        con.execute(
            """
            INSERT INTO embedding_eval_labels (
                label_row_id, eval_id, source_record_id, label, annotator_id,
                adjudication_status, adjudicator_id, created_at, disagreement_notes
            ) VALUES (?, ?, NULL, ?, ?, 'adjudicated', ?, ?, ?)
            """,
            [rid, eval_id, label, adjudicator_id, adjudicator_id, now, notes],
        )
        con.execute(
            """
            UPDATE embedding_eval_labels
            SET adjudication_status = 'adjudicated'
            WHERE eval_id = ?
            """,
            [eval_id],
        )
    return rid


def _refresh_agreement_status(con, eval_id: str) -> None:
    rows = con.execute(
        """
        SELECT annotator_id, label FROM embedding_eval_labels
        WHERE eval_id = ? AND adjudicator_id IS NULL
        """,
        [eval_id],
    ).fetchall()
    if len(rows) < 2:
        return
    labels = {r[1] for r in rows}
    status = "agreed" if len(labels) == 1 else "disagreed"
    con.execute(
        "UPDATE embedding_eval_labels SET adjudication_status = ? WHERE eval_id = ? AND adjudicator_id IS NULL",
        [status, eval_id],
    )


def export_labels(path: Path) -> int:
    with ops_con(read_only=True) as con:
        try:
            cur = con.execute(
                """
                SELECT label_row_id, eval_id, source_record_id, label, annotator_id,
                       adjudication_status, adjudicator_id, created_at, disagreement_notes
                FROM embedding_eval_labels ORDER BY created_at
                """
            )
            cols = [d[0] for d in cur.description]
            rows = [dict(zip(cols, r)) for r in cur.fetchall()]
        except Exception:
            rows = []
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as fh:
        for row in rows:
            for k, v in list(row.items()):
                if hasattr(v, "isoformat"):
                    row[k] = v.isoformat()
            fh.write(json.dumps(row, default=str) + "\n")
    return len(rows)


def import_labels(path: Path) -> int:
    n = 0
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        rec = json.loads(line)
        if rec.get("label_source") in INELIGIBLE_SOURCES:
            continue
        submit_label(
            eval_id=rec["eval_id"],
            annotator_id=rec["annotator_id"],
            label=rec["label"],
            source_record_id=rec.get("source_record_id"),
            notes=rec.get("disagreement_notes") or "",
        )
        n += 1
    return n


def _cohen_kappa(a: list[int], b: list[int]) -> float | None:
    if len(a) != len(b) or not a:
        return None
    if len(a) == 1:
        return 1.0 if a[0] == b[0] else 0.0
    n = len(a)
    agree = sum(1 for x, y in zip(a, b) if x == y) / n
    pa = sum(a) / n
    pb = sum(b) / n
    exp = pa * pb + (1 - pa) * (1 - pb)
    if abs(exp - 1.0) < 1e-12:
        return 1.0 if agree == 1.0 else 0.0
    return (agree - exp) / (1.0 - exp)


def _krippendorff_alpha_nominal(coder_labels: list[list[str]]) -> float | None:
    """Nominal α for two-or-more coders on the same items (aligned)."""
    if len(coder_labels) < 2:
        return None
    n_items = len(coder_labels[0])
    if n_items < 2 or any(len(c) != n_items for c in coder_labels):
        return None
    values: list[str] = []
    for item_i in range(n_items):
        values.extend(c[item_i] for c in coder_labels)
    counts = Counter(values)
    n = len(values)
    if n < 2:
        return None
    coincidence_do = 0.0
    for item_i in range(n_items):
        labs = [c[item_i] for c in coder_labels]
        m = len(labs)
        if m < 2:
            continue
        for i in range(m):
            for j in range(m):
                if i == j:
                    continue
                if labs[i] != labs[j]:
                    coincidence_do += 1.0 / (m - 1)
    coincidence_do /= n
    de = 0.0
    labs_unique = list(counts)
    for i, u in enumerate(labs_unique):
        for v in labs_unique[i + 1 :]:
            de += (counts[u] * counts[v]) / (n - 1)
    de = 2 * de / n
    if de == 0:
        return 1.0
    return 1.0 - (coincidence_do / de)


def agreement_report() -> dict[str, Any]:
    """Per-class Cohen's κ (one-vs-rest, first two annotators) and overall α."""
    with ops_con(read_only=True) as con:
        try:
            rows = con.execute(
                """
                SELECT eval_id, annotator_id, label
                FROM embedding_eval_labels
                WHERE adjudicator_id IS NULL
                ORDER BY eval_id, created_at
                """
            ).fetchall()
        except Exception:
            rows = []
    by_item: dict[str, list[tuple[str, str]]] = defaultdict(list)
    for eid, aid, lab in rows:
        by_item[str(eid)].append((str(aid), str(lab)))
    paired = {eid: labs[:2] for eid, labs in by_item.items() if len(labs) >= 2}
    per_class: dict[str, Any] = {}
    for cls in LABEL_CLASSES:
        a, b = [], []
        annotators: set[str] = set()
        for labs in paired.values():
            a.append(1 if labs[0][1] == cls else 0)
            b.append(1 if labs[1][1] == cls else 0)
            annotators.add(labs[0][0])
            annotators.add(labs[1][0])
        kappa = _cohen_kappa(a, b) if a else None
        per_class[cls] = {
            "n_paired": len(a),
            "annotator_count": len(annotators),
            "cohens_kappa": None if kappa is None else round(kappa, 4),
            "eligible": bool(
                kappa is not None and kappa >= KAPPA_MIN and len(annotators) >= 2
            ),
        }
    coder_a = [paired[eid][0][1] for eid in paired]
    coder_b = [paired[eid][1][1] for eid in paired]
    alpha = _krippendorff_alpha_nominal([coder_a, coder_b]) if paired else None
    return {
        "paired_items": len(paired),
        "krippendorff_alpha_nominal": None if alpha is None else round(alpha, 4),
        "kappa_min": KAPPA_MIN,
        "per_class": per_class,
    }


def class_quota_counts() -> dict[str, int]:
    with ops_con(read_only=True) as con:
        try:
            rows = con.execute(
                """
                SELECT label, COUNT(DISTINCT eval_id)
                FROM embedding_eval_labels
                WHERE adjudication_status IN ('agreed', 'adjudicated')
                GROUP BY label
                """
            ).fetchall()
        except Exception:
            rows = []
    out = {c: 0 for c in LABEL_CLASSES}
    for lab, n in rows:
        if lab in out:
            out[str(lab)] = int(n)
    return out


__all__ = [
    "LABEL_CLASSES",
    "KAPPA_MIN",
    "INELIGIBLE_SOURCES",
    "enqueue_unlabeled_item",
    "next_unlabeled_item",
    "submit_label",
    "adjudicate",
    "export_labels",
    "import_labels",
    "agreement_report",
    "class_quota_counts",
    "ensure_eval_tables",
]
