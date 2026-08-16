"""Per-pack cluster rebuild from embeddings (feature #5).

Uses bag-of-hash embeddings + simple k-means-style assignment (no sklearn).
Writes ``clusters`` and ``cluster_assignments`` tables agents already read.
"""

from __future__ import annotations

import json
import math
import re
from collections import Counter, defaultdict
from typing import Any

from src.data.warehouse import apply_domain_schema, domain_con
from src.ml_runtime.embeddings import cosine, embed_text

_TOKEN = re.compile(r"[a-z0-9]+", re.I)
_STOP = {
    "the",
    "a",
    "an",
    "and",
    "or",
    "when",
    "with",
    "from",
    "that",
    "this",
    "for",
    "to",
    "of",
    "in",
    "on",
    "is",
    "are",
    "was",
    "at",
}


def _tokens(text: str) -> list[str]:
    return [t.lower() for t in _TOKEN.findall(text or "") if t.lower() not in _STOP and len(t) > 2]


def _kmeans(vectors: list[list[float]], k: int, rounds: int = 8) -> list[int]:
    if not vectors:
        return []
    k = max(1, min(k, len(vectors)))
    # init: evenly spaced
    centroids = [vectors[i * len(vectors) // k][:] for i in range(k)]
    labels = [0] * len(vectors)
    for _ in range(rounds):
        # assign
        for i, v in enumerate(vectors):
            best, bi = -1.0, 0
            for j, c in enumerate(centroids):
                s = cosine(v, c)
                if s > best:
                    best, bi = s, j
            labels[i] = bi
        # update
        buckets: list[list[list[float]]] = [[] for _ in range(k)]
        for i, lab in enumerate(labels):
            buckets[lab].append(vectors[i])
        for j in range(k):
            if not buckets[j]:
                continue
            dim = len(buckets[j][0])
            avg = [0.0] * dim
            for v in buckets[j]:
                for d in range(dim):
                    avg[d] += v[d]
            n = float(len(buckets[j]))
            centroids[j] = [x / n for x in avg]
            norm = math.sqrt(sum(x * x for x in centroids[j])) or 1.0
            centroids[j] = [x / norm for x in centroids[j]]
    return labels


def rebuild_clusters(pack_id: str, *, k: int = 5) -> dict[str, Any]:
    """Rebuild clusters for pack from records text/embeddings."""
    with domain_con(pack_id, read_only=False) as con:
        apply_domain_schema(con)
        try:
            con.execute("ALTER TABLE records ADD COLUMN embedding FLOAT[]")
        except Exception:
            pass
        rows = con.execute(
            """
            SELECT record_id, text, category, embedding, received_at
            FROM records
            ORDER BY received_at
            """
        ).fetchall()
        if not rows:
            return {"pack_id": pack_id, "clusters": 0, "assignments": 0}

        records = []
        vectors = []
        for rid, text, cat, emb, rec_at in rows:
            if emb is None:
                emb = embed_text(text or "")
                try:
                    con.execute(
                        "UPDATE records SET embedding = ? WHERE record_id = ?",
                        [list(emb), rid],
                    )
                except Exception:
                    pass
            else:
                emb = list(emb)
            records.append(
                {
                    "record_id": rid,
                    "text": text or "",
                    "category": cat,
                    "received_at": rec_at,
                }
            )
            vectors.append(emb)

        kk = min(k, max(1, len(records) // 2))
        labels = _kmeans(vectors, kk)

        # wipe old clusters for this pack
        con.execute(
            "DELETE FROM cluster_assignments WHERE record_id IN (SELECT record_id FROM records)"
        )
        # delete clusters for pack
        old = con.execute(
            "SELECT cluster_id FROM clusters WHERE pack_id = ?", [pack_id]
        ).fetchall()
        for (cid,) in old:
            con.execute("DELETE FROM clusters WHERE cluster_id = ?", [cid])

        by_lab: dict[int, list[int]] = defaultdict(list)
        for i, lab in enumerate(labels):
            by_lab[lab].append(i)

        # stable cluster ids: 1000+lab
        written = 0
        for lab, idxs in sorted(by_lab.items()):
            cid = 1000 + lab
            texts = [records[i]["text"] for i in idxs]
            tok_counts: Counter[str] = Counter()
            for t in texts:
                tok_counts.update(_tokens(t))
            top = [w for w, _ in tok_counts.most_common(5)]
            cats = Counter(records[i]["category"] for i in idxs if records[i]["category"])
            category = cats.most_common(1)[0][0] if cats else None
            times = [records[i]["received_at"] for i in idxs if records[i]["received_at"]]
            first_seen = min(times) if times else None
            last_seen = max(times) if times else None
            con.execute(
                """
                INSERT INTO clusters
                (cluster_id, pack_id, top_terms, category, record_count, first_seen, last_seen)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                [
                    cid,
                    pack_id,
                    json.dumps(top),
                    category,
                    len(idxs),
                    first_seen,
                    last_seen,
                ],
            )
            for i in idxs:
                con.execute(
                    """
                    INSERT INTO cluster_assignments (record_id, cluster_id, distance)
                    VALUES (?, ?, ?)
                    """,
                    [records[i]["record_id"], cid, 0.1],
                )
                written += 1

        return {
            "pack_id": pack_id,
            "clusters": len(by_lab),
            "assignments": written,
            "k": kk,
        }


__all__ = ["rebuild_clusters"]
