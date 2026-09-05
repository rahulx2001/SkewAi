"""Style-leakage check: same meaning, different register.

This is not an eval label. It restyles a string and reports whether
similarity is driven by NHTSA-formal vs colloquial surface form.
"""

from __future__ import annotations

from typing import Any

from src.ml_runtime.embedding_space import compare_embeddings


def restyle_formal(text: str) -> str:
    return (
        "CONSUMER STATES THE FOLLOWING: "
        + text.strip().rstrip(".")
        + ". THIS COMPLAINT IS FILED FOR RECORD."
    )


def restyle_colloquial(text: str) -> str:
    t = text.strip()
    return "yeah so um " + t[0].lower() + t[1:] if t else t


def restyle_typos(text: str) -> str:
    return (
        text.replace("the ", "teh ")
        .replace("brake", "break")
        .replace("engine", "engne")
    )


def style_bias_report(embedder: Any, texts: list[str]) -> dict[str, Any]:
    formal, colloq, typo, trunc = [], [], [], []
    for t in texts:
        if not (t or "").strip():
            continue
        base = embedder.embed(t)
        formal.append(compare_embeddings(base, embedder.embed(restyle_formal(t))))
        colloq.append(compare_embeddings(base, embedder.embed(restyle_colloquial(t))))
        typo.append(compare_embeddings(base, embedder.embed(restyle_typos(t))))
        trunc.append(compare_embeddings(base, embedder.embed(t[: max(12, len(t) // 2)])))
    def _mean(xs: list[float]) -> float:
        return round(sum(xs) / len(xs), 4) if xs else 0.0
    return {
        "n": len(formal),
        "mean_sim_formal_register": _mean(formal),
        "mean_sim_colloquial_register": _mean(colloq),
        "mean_sim_typos": _mean(typo),
        "mean_sim_truncated": _mean(trunc),
        "style_gap_formal_minus_colloquial": round(_mean(formal) - _mean(colloq), 4),
        "note": "A large formal-colloquial gap means the model clusters writing style, not meaning.",
    }
