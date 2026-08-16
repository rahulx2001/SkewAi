"""Investigator Agent — corpus RCA.

Runs once category + description are filled:
  1. similar_records retriever (v1 similar_complaints generalized) with
     description + entity filters → top-k with scores.
  2. cluster_themes → dominant cluster.
  3. spikes_in_window for category/entity.
  4. backtest_proof → historical lead time for the matched cluster.

Output: InvestigationBrief — all numbers straight from SQL. LLM writes only the
two-sentence console narration (citation-verified).
"""

from __future__ import annotations

from typing import Any

from src.agents.base import Agent
from src.data.warehouse import domain_con
from src.ledger import record_action


# ── SQL templates (canonical schema, pack-agnostic) ──────────────────────
# DuckDB's Python client binds `?` placeholders positionally, so every
# statement takes a flat list of parameters (repeated where a value is used
# in more than one placeholder).

_SIMILAR_SQL = """
SELECT r.record_id, r.category, r.severity_label, r.received_at,
       r.text, r.entity_1, r.entity_2, r.entity_3
FROM records r
WHERE (? IS NULL OR r.category = ?)
  AND (? IS NULL OR r.entity_2 = ?)
  AND (? IS NULL OR r.entity_3 = ?)
  AND (? IS NULL OR r.text ILIKE '%' || ? || '%')
LIMIT ?
"""

_CLUSTER_SQL = """
SELECT c.cluster_id, c.top_terms, c.category, c.record_count,
       c.first_seen, c.last_seen
FROM clusters c
WHERE c.pack_id = ?
  AND (c.category = ? OR ? IS NULL)
ORDER BY c.record_count DESC
LIMIT 1
"""

_SPIKE_SQL = """
SELECT iso_week, record_count, z_score, is_anomaly
FROM weekly_anomalies
WHERE pack_id = ?
  AND (category = ? OR ? IS NULL)
ORDER BY iso_week DESC
LIMIT 4
"""

_BACKTEST_SQL = """
SELECT b.cluster_id, b.advisory_id, b.lead_time_weeks, b.matched
FROM backtest_results b
WHERE b.cluster_id = ?
LIMIT 1
"""


class InvestigatorAgent(Agent):
    """Corpus RCA: similar records, cluster, spike, lead-time. No LLM."""

    name = "investigator"

    async def run(self, **kwargs: Any) -> dict[str, Any]:
        ctx = self.ctx
        category = ctx.slots.get("category")
        entity_2 = ctx.slots.get("entity_2")
        entity_3 = ctx.slots.get("entity_3")
        description = ctx.slots.get("description") or ""

        # Extract a keyword from the description for the ILIKE filter.
        keyword = self._extract_keyword(description)

        # ── Similar records (semantic rank over candidate pool + ILIKE fallback)
        retrieval_mode = "ilike"
        try:
            with domain_con(ctx.pack.id) as con:
                # Broad candidate pool for semantic re-rank (entity/category filter).
                candidate_rows = con.execute(
                    _SIMILAR_SQL,
                    [
                        category, category,
                        entity_2, entity_2,
                        entity_3, entity_3,
                        None, None,
                        40,
                    ],
                ).fetchall()
                similar_cols = [d[0] for d in con.description]
                candidates = [dict(zip(similar_cols, r)) for r in candidate_rows]

                if candidates:
                    try:
                        from src.ml_runtime.association import rank_by_association

                        query = {
                            "category": category,
                            "entity_2": entity_2,
                            "entity_3": entity_3,
                            "text": description,
                        }
                        similar = rank_by_association(
                            query, candidates, candidates, top_k=5
                        )
                        retrieval_mode = "association"
                    except Exception:
                        similar = []
                    if description:
                        try:
                            from src.ml_runtime.embeddings import rank_by_similarity

                            ranked = rank_by_similarity(
                                description, similar or candidates, top_k=5
                            )
                            if ranked and (ranked[0].get("sim_score") or 0) > 0.05:
                                # Keep association order when scores are close; prefer
                                # assoc-ranked list as the primary similar set.
                                if similar:
                                    retrieval_mode = "association"
                                else:
                                    similar = ranked
                                    retrieval_mode = "semantic"
                        except Exception:
                            pass
                else:
                    similar = []

                if not similar:
                    # Wider ILIKE pool, then association rank (not recency LIMIT 5).
                    similar_rows = con.execute(
                        _SIMILAR_SQL,
                        [
                            category, category,
                            entity_2, entity_2,
                            entity_3, entity_3,
                            keyword, keyword,
                            40,
                        ],
                    ).fetchall()
                    if not similar_rows and keyword:
                        similar_rows = con.execute(
                            _SIMILAR_SQL,
                            [
                                category, category,
                                entity_2, entity_2,
                                entity_3, entity_3,
                                None, None,
                                40,
                            ],
                        ).fetchall()
                    similar_cols = [d[0] for d in con.description]
                    pool = [dict(zip(similar_cols, r)) for r in similar_rows]
                    from src.ml_runtime.association import rank_by_association

                    query = {
                        "category": category,
                        "entity_2": entity_2,
                        "entity_3": entity_3,
                        "text": description,
                    }
                    similar = rank_by_association(query, pool, pool, top_k=5)
                    retrieval_mode = "association" if similar else "ilike"

                cluster_row = con.execute(
                    _CLUSTER_SQL, [ctx.pack.id, category, category]
                ).fetchone()
                cluster_cols = [d[0] for d in con.description]

                spike_rows = con.execute(
                    _SPIKE_SQL, [ctx.pack.id, category, category]
                ).fetchall()
                spike_cols = [d[0] for d in con.description]

                backtest_row = None
                backtest_cols: list[str] = []
                if cluster_row:
                    cluster_id = cluster_row[0]
                    backtest_row = con.execute(
                        _BACKTEST_SQL, [cluster_id]
                    ).fetchone()
                    backtest_cols = [d[0] for d in con.description]
        except FileNotFoundError:
            # Domain warehouse not built yet — degrade gracefully.
            record_action(self._action(
                action_type="similar_search",
                input_summary="domain warehouse not found",
                output_summary="investigator skipped; no corpus available",
                ok=False,
                error="domain warehouse missing",
            ))
            return {"skipped": True, "reason": "domain warehouse not built"}

        # ── Ledger: similar_search ───────────────────────────────────────
        similar_ids = [s["record_id"] for s in similar if s.get("record_id")]
        from src.qubot.claims import bound_claims_from_records

        claims = bound_claims_from_records(similar, prefer=keyword)
        record_action(self._action(
            action_type="similar_search",
            input_summary=(
                f"keyword='{keyword}', category={category}, entity_2={entity_2}, "
                f"entity_3={entity_3}, mode={retrieval_mode}"
            ),
            output_summary=f"found {len(similar)} similar records ({retrieval_mode})",
            evidence_ids=similar_ids,
            claims=claims,
        ))

        # ── Cluster match ─────────────────────────────────────────────────
        cluster_id = None
        cluster_top_terms: list = []
        cluster_count = 0
        if cluster_row:
            cd = dict(zip(cluster_cols, cluster_row))
            cluster_id = cd.get("cluster_id")
            cluster_count = cd.get("record_count", 0) or 0
            tt = cd.get("top_terms")
            if isinstance(tt, str):
                import json
                try:
                    cluster_top_terms = json.loads(tt)
                except json.JSONDecodeError:
                    cluster_top_terms = [tt]
            elif isinstance(tt, list):
                cluster_top_terms = tt
            ctx.investigation_brief = {
                "cluster_id": cluster_id,
                "cluster_count": cluster_count,
                "cluster_top_terms": cluster_top_terms,
            }
            record_action(self._action(
                action_type="cluster_matched",
                input_summary=f"category={category}",
                output_summary=f"cluster_id={cluster_id}, count={cluster_count}",
                evidence_ids=[str(cluster_id)] if cluster_id is not None else [],
            ))

        # ── Spike check ───────────────────────────────────────────────────
        spikes = [dict(zip(spike_cols, r)) for r in spike_rows]
        record_action(self._action(
            action_type="spike_checked",
            input_summary=f"category={category}",
            output_summary=f"recent weeks: {[(s.get('iso_week'), s.get('z_score'), s.get('is_anomaly')) for s in spikes]}",
        ))

        # ── Backtest lead-time + conclusion brief ─────────────────────────
        lead_time_weeks = None
        advisory_id = None
        if backtest_row:
            bd = dict(zip(backtest_cols, backtest_row))
            lead_time_weeks = bd.get("lead_time_weeks")
            advisory_id = bd.get("advisory_id")
        brief_ids = list(similar_ids)
        if advisory_id:
            brief_ids.append(str(advisory_id))
        record_action(self._action(
            action_type="brief_written",
            input_summary=f"cluster_id={cluster_id}",
            output_summary=(
                f"lead_time_weeks={lead_time_weeks}, matched_advisory={advisory_id}"
            ),
            evidence_ids=brief_ids,
            claims=claims,
        ))

        # ── InvestigationBrief ────────────────────────────────────────────
        brief = {
            "similar_records": similar[:5],
            "similar_record_count": len(similar),
            "cluster_id": cluster_id,
            "cluster_top_terms": cluster_top_terms,
            "cluster_count": cluster_count,
            "spikes": spikes,
            "lead_time_weeks": lead_time_weeks,
        }
        ctx.investigation_brief = brief

        # Two-sentence narration — deterministic in v2 (no LLM by default).
        narration = self._narrate(brief)
        return {
            "brief": brief,
            "narration": narration,
            "evidence_ids": similar_ids + ([str(cluster_id)] if cluster_id is not None else []),
        }

    # ── Helpers ────────────────────────────────────────────────────────────
    def _extract_keyword(self, description: str) -> str | None:
        """Pick the most informative word from the description for the ILIKE
        filter. Falls back to None (no text filter)."""
        if not description:
            return None
        # Strip common stopwords + verbs; pick the longest content word.
        stopwords = {
            "the", "a", "an", "my", "is", "are", "was", "were", "when", "i",
            "to", "on", "in", "at", "and", "or", "but", "of", "with", "for",
            "it", "that", "this", "there", "here",
        }
        words = [w.strip(".,!?;:'\"()[]").lower() for w in description.split()]
        cands = [w for w in words if w and w not in stopwords and len(w) >= 4]
        if not cands:
            return None
        cands.sort(key=len, reverse=True)
        return cands[0]

    def _narrate(self, brief: dict[str, Any]) -> str:
        """Two-sentence narration; LLM optional with deterministic fallback."""
        count = brief.get("similar_record_count", 0)
        cluster = brief.get("cluster_id")
        cluster_count = brief.get("cluster_count", 0)
        lead = brief.get("lead_time_weeks")
        evidence_ids = [
            s.get("record_id")
            for s in (brief.get("similar_records") or [])
            if s.get("record_id")
        ]

        s1 = f"Found {count} similar historical record(s)"
        if cluster is not None:
            s1 += f"; strongest match is cluster #{cluster} ({cluster_count} records)"
        s1 += "."

        s2 = ""
        if lead is not None:
            s2 = f"Historically, similar clusters preceded an advisory by {lead} weeks."
        elif brief.get("spikes"):
            recent = brief["spikes"][0]
            if recent.get("is_anomaly"):
                s2 = f"Volume spiked in {recent.get('iso_week')} (z-score {recent.get('z_score'):.1f})."
        fallback = (s1 + " " + s2).strip()

        try:
            from src.ai.narration import phrase_investigation_brief

            res = phrase_investigation_brief(
                similar_count=count,
                cluster_id=cluster,
                lead_time_weeks=lead,
                keyword=self._extract_keyword(self.ctx.slots.get("description") or "") or "",
                evidence_ids=[str(e) for e in evidence_ids[:5]],
            )
            return res.text
        except Exception:
            return fallback
