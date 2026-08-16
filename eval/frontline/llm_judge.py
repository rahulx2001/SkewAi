"""Optional LLM-as-judge eval track (feature #6).

Scores intake empathy, question relevance, and narration faithfulness.
Reported separately from hermetic deterministic gates — never fails CI unless
``FRONTLINE_LLM_JUDGE=1`` and a provider is available. Offline mode uses a
deterministic heuristic judge so the module is always callable.
"""

from __future__ import annotations

import os
import re
from dataclasses import dataclass, asdict
from typing import Any


@dataclass
class JudgeScores:
    empathy: float
    relevance: float
    faithfulness: float
    method: str
    notes: str = ""

    @property
    def overall(self) -> float:
        return round((self.empathy + self.relevance + self.faithfulness) / 3.0, 3)

    def to_dict(self) -> dict[str, Any]:
        d = asdict(self)
        d["overall"] = self.overall
        return d


def _heuristic_judge(
    *,
    agent_turns: list[str],
    customer_turns: list[str],
    evidence_ids: list[str] | None = None,
    claimed_ids: list[str] | None = None,
) -> JudgeScores:
    agent_blob = " ".join(agent_turns).lower()
    cust_blob = " ".join(customer_turns).lower()
    # Empathy: acknowledgements / sorry / thank
    empathy_hits = sum(
        1
        for w in ("sorry", "understand", "thank", "appreciate", "hear you", "i'm here")
        if w in agent_blob
    )
    empathy = min(1.0, 0.4 + 0.15 * empathy_hits)
    # Relevance: overlap tokens between last customer and agent reply
    c_tokens = set(re.findall(r"[a-z]{3,}", cust_blob))
    a_tokens = set(re.findall(r"[a-z]{3,}", agent_blob))
    overlap = len(c_tokens & a_tokens) / max(1, len(c_tokens))
    relevance = min(1.0, 0.35 + overlap)
    # Faithfulness: claimed IDs subset of evidence
    evidence_ids = evidence_ids or []
    claimed_ids = claimed_ids or []
    if not claimed_ids:
        faithfulness = 1.0
    else:
        bad = [c for c in claimed_ids if c not in evidence_ids]
        faithfulness = 0.0 if bad else 1.0
    return JudgeScores(
        empathy=round(empathy, 3),
        relevance=round(relevance, 3),
        faithfulness=round(faithfulness, 3),
        method="heuristic",
        notes="offline pilot judge; set FRONTLINE_LLM_JUDGE=1 + LLM for model scores",
    )


def judge_interaction(
    *,
    agent_turns: list[str],
    customer_turns: list[str],
    evidence_ids: list[str] | None = None,
    claimed_ids: list[str] | None = None,
) -> JudgeScores:
    use_llm = os.getenv("FRONTLINE_LLM_JUDGE", "").strip().lower() in {"1", "true", "yes"}
    if use_llm:
        try:
            from src.ai.provider import narrate, llm_enabled

            if llm_enabled():
                system = (
                    "Score 0-1 each: empathy, relevance, faithfulness. "
                    "Reply JSON only: {empathy:n,relevance:n,faithfulness:n}"
                )
                user = (
                    f"CUSTOMER:\n" + "\n".join(customer_turns)
                    + "\n\nAGENT:\n" + "\n".join(agent_turns)
                )
                res = narrate(system=system, user=user)
                if res.ok and res.text:
                    import json

                    m = re.search(r"\{[^}]+\}", res.text)
                    if m:
                        data = json.loads(m.group())
                        return JudgeScores(
                            empathy=float(data.get("empathy", 0)),
                            relevance=float(data.get("relevance", 0)),
                            faithfulness=float(data.get("faithfulness", 0)),
                            method="llm",
                            notes=res.model_id or "",
                        )
        except Exception as e:
            h = _heuristic_judge(
                agent_turns=agent_turns,
                customer_turns=customer_turns,
                evidence_ids=evidence_ids,
                claimed_ids=claimed_ids,
            )
            h.notes = f"llm_failed:{type(e).__name__}; {h.notes}"
            return h
    return _heuristic_judge(
        agent_turns=agent_turns,
        customer_turns=customer_turns,
        evidence_ids=evidence_ids,
        claimed_ids=claimed_ids,
    )
