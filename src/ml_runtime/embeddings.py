"""Lightweight bag-of-hash embeddings for semantic similarity (no heavy deps).

Produces fixed-dim float vectors from text via hashed character n-grams.
Stored in ``records.embedding`` when present; investigator ranks by cosine
similarity and falls back to ILIKE when embeddings are missing.
"""

from __future__ import annotations

import hashlib
import math
import re
from typing import Sequence

_DIM = 64
_TOKEN_RE = re.compile(r"[a-z0-9]+", re.I)


def _stable_bucket(gram: str, dim: int) -> int:
    """Process-stable bucket. Python's hash() is salted per process."""
    digest = hashlib.blake2b(gram.encode("utf-8"), digest_size=8).digest()
    return int.from_bytes(digest, "little") % dim


def embed_text(text: str, dim: int = _DIM) -> list[float]:
    """Hashing trick embedding — deterministic across processes, no model download."""
    vec = [0.0] * dim
    tokens = _TOKEN_RE.findall((text or "").lower())
    if not tokens:
        return vec
    for tok in tokens:
        # char bigrams + whole token
        grams = [tok] + [tok[i : i + 2] for i in range(max(0, len(tok) - 1))]
        for g in grams:
            h = _stable_bucket(g, dim)
            vec[h] += 1.0
    # L2 normalize
    norm = math.sqrt(sum(v * v for v in vec)) or 1.0
    return [v / norm for v in vec]


def cosine(a: Sequence[float], b: Sequence[float]) -> float:
    if not a or not b or len(a) != len(b):
        return 0.0
    return float(sum(x * y for x, y in zip(a, b)))


def rank_by_similarity(
    query: str,
    candidates: list[dict],
    *,
    text_key: str = "text",
    embedding_key: str = "embedding",
    top_k: int = 5,
) -> list[dict]:
    """Return candidates sorted by cosine sim to query (adds ``sim_score``)."""
    q = embed_text(query)
    scored: list[tuple[float, dict]] = []
    for c in candidates:
        emb = c.get(embedding_key)
        if emb is None:
            emb = embed_text(str(c.get(text_key) or ""))
        elif isinstance(emb, (list, tuple)):
            emb = list(emb)
        else:
            emb = embed_text(str(c.get(text_key) or ""))
        score = cosine(q, emb)
        row = dict(c)
        row["sim_score"] = score
        scored.append((score, row))
    scored.sort(key=lambda x: x[0], reverse=True)
    return [r for _, r in scored[:top_k]]


__all__ = ["embed_text", "cosine", "rank_by_similarity", "_DIM", "_stable_bucket"]
