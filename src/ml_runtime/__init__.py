"""Offline ML runtime — no sklearn / no external model downloads.

Public surface: bag-of-hash embeddings, in-module k-means clustering, and the
rules-path severity registry.
"""

from src.ml_runtime.anomalies import recompute_weekly_anomalies
from src.ml_runtime.association import rank_by_association
from src.ml_runtime.clustering import rebuild_clusters
from src.ml_runtime.embeddings import cosine, embed_text, rank_by_similarity
from src.ml_runtime.entity_resolution import same_entity
from src.ml_runtime.registry import predict_severity

__all__ = [
    "rebuild_clusters",
    "cosine",
    "embed_text",
    "rank_by_similarity",
    "rank_by_association",
    "recompute_weekly_anomalies",
    "same_entity",
    "predict_severity",
]
