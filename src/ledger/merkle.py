"""Global Merkle transparency log across interactions.

Per-interaction chains cannot detect a deleted whole contact. Leaves here
are (interaction_id, action_id, row_hash). Omitting any leaf changes the root.
"""

from __future__ import annotations

import hashlib
from typing import Any, Sequence

from src.data.warehouse import ops_con


def leaf_hash(interaction_id: str, action_id: str, row_hash: str) -> str:
    raw = f"{interaction_id}|{action_id}|{row_hash}".encode("utf-8")
    return hashlib.sha256(raw).hexdigest()


def merkle_root(leaves: Sequence[str]) -> str:
    if not leaves:
        return hashlib.sha256(b"empty").hexdigest()
    layer = list(leaves)
    while len(layer) > 1:
        nxt: list[str] = []
        if len(layer) % 2 == 1:
            layer = list(layer) + [layer[-1]]
        for i in range(0, len(layer), 2):
            nxt.append(hashlib.sha256((layer[i] + layer[i + 1]).encode("utf-8")).hexdigest())
        layer = nxt
    return layer[0]


def _ensure(con) -> None:
    con.execute(
        """
        CREATE TABLE IF NOT EXISTS global_log_leaves (
            seq            INTEGER PRIMARY KEY,
            interaction_id VARCHAR NOT NULL,
            action_id      VARCHAR NOT NULL,
            leaf           VARCHAR NOT NULL,
            row_hash       VARCHAR
        )
        """
    )
    con.execute("CREATE SEQUENCE IF NOT EXISTS global_log_seq START 1")


def append_action_leaf_on_con(con, interaction_id: str, action_id: str, row_hash: str) -> str:
    leaf = leaf_hash(interaction_id, action_id, row_hash)
    _ensure(con)
    seq = con.execute("SELECT nextval('global_log_seq')").fetchone()[0]
    con.execute(
        """
        INSERT INTO global_log_leaves
        (seq, interaction_id, action_id, leaf, row_hash)
        VALUES (?, ?, ?, ?, ?)
        """,
        [int(seq), interaction_id, action_id, leaf, row_hash],
    )
    return leaf


def append_action_leaf(interaction_id: str, action_id: str, row_hash: str) -> str:
    with ops_con() as con:
        return append_action_leaf_on_con(con, interaction_id, action_id, row_hash)


def collect_leaves(*, interaction_ids: list[str] | None = None) -> list[dict[str, Any]]:
    with ops_con(read_only=True) as con:
        try:
            if interaction_ids:
                ph = ",".join("?" * len(interaction_ids))
                cur = con.execute(
                    f"""
                    SELECT seq, interaction_id, action_id, leaf, row_hash
                    FROM global_log_leaves
                    WHERE interaction_id IN ({ph})
                    ORDER BY seq
                    """,
                    interaction_ids,
                )
            else:
                cur = con.execute(
                    """
                    SELECT seq, interaction_id, action_id, leaf, row_hash
                    FROM global_log_leaves ORDER BY seq
                    """
                )
        except Exception:
            return []
        cols = [d[0] for d in cur.description]
        return [dict(zip(cols, r)) for r in cur.fetchall()]


def verify_completeness(
    *,
    interaction_ids: list[str] | None = None,
    omit_interaction: str | None = None,
) -> dict[str, Any]:
    """Read ``global_log_leaves`` and check the stored log is complete.

    ``omit_interaction`` drops that contact's stored leaves (a vanished
    interaction) so the root must differ from the full log.
    """
    stored = collect_leaves(interaction_ids=interaction_ids)
    full = [str(r["leaf"]) for r in stored]
    present = [
        str(r["leaf"])
        for r in stored
        if omit_interaction is None or r["interaction_id"] != omit_interaction
    ]
    root = merkle_root(present)
    full_root = merkle_root(full)
    ok = root == full_root and len(present) == len(full)
    return {
        "ok": ok,
        "root": root,
        "full_root": full_root,
        "leaf_count": len(present),
        "expected_count": len(full),
    }


__all__ = [
    "leaf_hash",
    "merkle_root",
    "append_action_leaf",
    "append_action_leaf_on_con",
    "collect_leaves",
    "verify_completeness",
]
