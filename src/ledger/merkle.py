"""Global Merkle transparency log across interactions.

Per-interaction chains cannot detect a deleted whole contact. Leaves here
are (interaction_id, action_id, row_hash). Omitting any leaf changes the root.

Tamper-evidence (item 9): the root alone is not self-verifying — verification
reads leaves from the same DB it checks. The fix is an externally anchored,
signed tree head (``anchor_tree_head``): a point-in-time (root, leaf_count)
signed with the locker Ed25519 key and stored/exported OUTSIDE the mutable
leaf table (locker bundles, regulator artifacts). ``verify_against_anchor``
recomputes from live leaves and compares to the anchor, so deleting or
modifying leaves/actions after anchoring fails verification. RFC3161
timestamping remains future work; the anchor abstraction (root + count +
signature + head chain) is in place.
"""

from __future__ import annotations

import hashlib
import json
from typing import Any, Sequence

from src.data.timeutil import utc_now
from src.data.warehouse import ops_con
from src.ids import new_ulid


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
    # Externally anchored tree heads (item 9): point-in-time signed roots.
    # The head row lives in ops for convenience, but the SECURITY property
    # comes from the exported/signed copy — verification compares live state
    # against the EXTERNAL anchor, never against this table alone.
    con.execute(
        """
        CREATE TABLE IF NOT EXISTS merkle_tree_heads (
            head_id      VARCHAR PRIMARY KEY,
            root         VARCHAR NOT NULL,
            leaf_count   INTEGER NOT NULL,
            scope        VARCHAR NOT NULL DEFAULT 'global',
            -- ISO-8601 string (not TIMESTAMP): the exact signed bytes must
            -- round-trip through the DB for offline signature verification.
            created_at   VARCHAR NOT NULL,
            prev_head    VARCHAR,
            signer       VARCHAR NOT NULL,
            signature    VARCHAR NOT NULL,
            public_key_pem TEXT
        )
        """
    )


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
    expected_root: str | None = None,
    expected_count: int | None = None,
) -> dict[str, Any]:
    """Check the stored log is complete.

    ``omit_interaction`` drops that contact's stored leaves (a vanished
    interaction) so the root must differ from the full log.

    Anchor semantics (item 9): ``expected_root``/``expected_count`` carry the
    EXTERNAL anchor (see ``anchor_tree_head``). When provided, verification
    compares live state against the anchor — deleting or modifying
    leaves/actions after anchoring fails. WITHOUT an anchor the check is
    self-consistency only (``anchored: False``) and MUST NOT be presented as
    tamper-evidence; export an anchored head for that.
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
    self_consistent = root == full_root and len(present) == len(full)
    out: dict[str, Any] = {
        "ok": self_consistent,
        "anchored": False,
        "root": root,
        "full_root": full_root,
        "leaf_count": len(present),
        "expected_count": len(full),
        "warning": (
            "self-consistency only: not tamper-evidence without an external "
            "anchor (use anchor_tree_head + verify_against_anchor)"
            if expected_root is None and expected_count is None
            else ""
        ),
    }
    if expected_root is not None or expected_count is not None:
        anchor_ok = True
        if expected_root is not None and root != expected_root:
            anchor_ok = False
        if expected_count is not None and len(present) != int(expected_count):
            anchor_ok = False
        out["anchored"] = True
        out["anchor_root"] = expected_root
        out["anchor_count"] = expected_count
        out["anchor_match"] = anchor_ok
        out["ok"] = bool(self_consistent and anchor_ok)
        out.pop("warning", None)
    else:
        out["latest_head"] = latest_head()
    return out


# ── Anchored tree heads (item 9) ────────────────────────────────────────────


def _head_bytes(
    head_id: str,
    root: str,
    leaf_count: int,
    created_at: str,
    prev_head: str,
    scope: str = "global",
) -> bytes:
    body = {
        "head_id": head_id,
        "root": root,
        "leaf_count": leaf_count,
        "scope": scope,
        "created_at": created_at,
        "prev_head": prev_head,
    }
    return json.dumps(body, sort_keys=True, separators=(",", ":")).encode("utf-8")


def _scope_label(interaction_ids: list[str] | None) -> str:
    if not interaction_ids:
        return "global"
    return "interactions:" + ",".join(sorted(interaction_ids))


def anchor_tree_head(
    *,
    signer: str = "local",
    interaction_ids: list[str] | None = None,
) -> dict[str, Any]:
    """Sign the current tree state and append a tree head. Returns the head.

    The returned dict is the EXTERNAL anchor: persist it outside the mutable
    DB (locker bundle ``merkle_proof.anchor_head``, regulator artifact, or a
    separate system) and later pass it to :func:`verify_against_anchor`.
    Heads form a hash-linked chain via ``prev_head`` so head-table rewrites
    are detectable during :func:`verify_head_chain`.

    ``interaction_ids`` scopes the anchor to one contact's leaves (locker
    exports); the default anchors the whole global log.
    """
    from src.qubot.locker import load_private_key

    scope = _scope_label(interaction_ids)
    with ops_con() as con:
        _ensure(con)
        try:
            con.execute("ALTER TABLE merkle_tree_heads ADD COLUMN scope VARCHAR")
        except Exception:
            pass
        if interaction_ids:
            ph = ",".join("?" * len(interaction_ids))
            leaves = con.execute(
                f"SELECT leaf FROM global_log_leaves WHERE interaction_id IN ({ph}) ORDER BY seq",
                list(interaction_ids),
            ).fetchall()
        else:
            leaves = con.execute(
                "SELECT leaf FROM global_log_leaves ORDER BY seq"
            ).fetchall()
        live = [str(r[0]) for r in leaves]
        root = merkle_root(live)
        try:
            prev = con.execute(
                "SELECT root FROM merkle_tree_heads ORDER BY created_at DESC, head_id DESC LIMIT 1"
            ).fetchone()
        except Exception:
            prev = None
        prev_head = str(prev[0]) if prev and prev[0] else "genesis"
        head_id = "head_" + new_ulid()
        created = utc_now().replace(tzinfo=None).isoformat()
        priv = load_private_key()
        sig = priv.sign(
            _head_bytes(head_id, root, len(live), created, prev_head, scope)
        ).hex()
        try:
            pub_pem = (
                priv.public_key()
                .public_bytes(
                    __import__(
                        "cryptography.hazmat.primitives.serialization",
                        fromlist=["Encoding"],
                    ).Encoding.PEM,
                    __import__(
                        "cryptography.hazmat.primitives.serialization",
                        fromlist=["PublicFormat"],
                    ).PublicFormat.SubjectPublicKeyInfo,
                )
                .decode("ascii")
            )
        except Exception:
            pub_pem = ""
        con.execute(
            """
            INSERT INTO merkle_tree_heads
            (head_id, root, leaf_count, scope, created_at, prev_head, signer,
             signature, public_key_pem)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            [head_id, root, len(live), scope, created, prev_head, signer, sig, pub_pem],
        )
    return {
        "head_id": head_id,
        "root": root,
        "leaf_count": len(live),
        "scope": scope,
        "created_at": created,
        "prev_head": prev_head,
        "signer": signer,
        "signature": sig,
        "public_key_pem": pub_pem,
    }


def latest_head() -> dict[str, Any] | None:
    """Return the most recent stored tree head (convenience, not an anchor)."""
    with ops_con(read_only=True) as con:
        try:
            _ensure(con)
            cur = con.execute(
                """
                SELECT head_id, root, leaf_count, created_at, prev_head,
                       signer, signature, public_key_pem
                FROM merkle_tree_heads
                ORDER BY created_at DESC, head_id DESC LIMIT 1
                """
            )
            row = cur.fetchone()
        except Exception:
            return None
        if not row:
            return None
        cols = [d[0] for d in cur.description]
        head = dict(zip(cols, row))
        head["created_at"] = str(head.get("created_at"))
        return head


def verify_head_signature(head: dict[str, Any]) -> bool:
    """Verify a head's Ed25519 signature (offline-capable)."""
    try:
        from cryptography.hazmat.primitives import serialization

        pem = head.get("public_key_pem") or ""
        if not pem:
            return False
        pub = serialization.load_pem_public_key(pem.encode("ascii"))
        pub.verify(
            bytes.fromhex(str(head.get("signature") or "")),
            _head_bytes(
                str(head.get("head_id") or ""),
                str(head.get("root") or ""),
                int(head.get("leaf_count") or 0),
                str(head.get("created_at") or ""),
                str(head.get("prev_head") or ""),
                str(head.get("scope") or "global"),
            ),
        )
        return True
    except Exception:
        return False


def verify_head_chain() -> dict[str, Any]:
    """Verify stored heads link correctly and every signature is valid."""
    with ops_con(read_only=True) as con:
        try:
            _ensure(con)
            cur = con.execute(
                """
                SELECT head_id, root, leaf_count, created_at, prev_head,
                       signer, signature, public_key_pem
                FROM merkle_tree_heads
                ORDER BY created_at ASC, head_id ASC
                """
            )
            cols = [d[0] for d in cur.description]
            heads = [dict(zip(cols, r)) for r in cur.fetchall()]
        except Exception:
            return {"ok": True, "heads": 0, "detail": "no head table"}
    prev = "genesis"
    for h in heads:
        h["created_at"] = str(h.get("created_at"))
        if h.get("prev_head") != prev:
            return {"ok": False, "heads": len(heads), "error": f"head chain break at {h.get('head_id')}"}
        if not verify_head_signature(h):
            return {"ok": False, "heads": len(heads), "error": f"bad head signature {h.get('head_id')}"}
        prev = str(h.get("root"))
    return {"ok": True, "heads": len(heads), "tip": prev}


def verify_against_anchor(
    anchor: dict[str, Any] | None,
    *,
    interaction_ids: list[str] | None = None,
) -> dict[str, Any]:
    """Verify live leaves against an EXTERNAL anchor head.

    Detects leaf deletion, leaf modification, action deletion (via missing
    leaves), and reordering relative to the anchor. The anchor is NOT read
    from the mutable DB — callers supply the exported copy.
    """
    if not anchor or not anchor.get("root"):
        return {"ok": False, "error": "no anchor supplied"}
    if not verify_head_signature(anchor):
        return {"ok": False, "error": "bad anchor signature"}
    stored = collect_leaves(interaction_ids=interaction_ids)
    live = [str(r["leaf"]) for r in stored]
    root = merkle_root(live)
    ok = root == str(anchor["root"]) and len(live) == int(anchor.get("leaf_count") or -1)
    return {
        "ok": ok,
        "root": root,
        "anchor_root": anchor.get("root"),
        "leaf_count": len(live),
        "anchor_count": anchor.get("leaf_count"),
        "head_id": anchor.get("head_id"),
    }


__all__ = [
    "leaf_hash",
    "merkle_root",
    "append_action_leaf",
    "append_action_leaf_on_con",
    "collect_leaves",
    "verify_completeness",
    "anchor_tree_head",
    "latest_head",
    "verify_head_signature",
    "verify_head_chain",
    "verify_against_anchor",
]
