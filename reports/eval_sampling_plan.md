# Sampling Plan & Human Annotation Protocol — Semantic Evaluation

**Status:** ACTIVE RECRUITMENT SPECIFICATION (Pending External Personnel)  
**Git Provenance:** `b0e923ea375c1eb8f86e3c5ec644cc8605c461f0` (tagged `v1.0-embed-setup`)  
**Acceptance Gate Status:** **CLOSED** (`acceptance_ready: false`)  
**Runtime Mode Lock:** `FRONTLINE_EMBEDDING_MODE=legacy`

---

## 1. Data Source & Sampling Mechanics

- **Corpus Source:** Real NHTSA complaint archive and secondary warranty/service records (`data/domains/automotive_nhtsa.duckdb`).
- **Sampling Tool:** `python -m scripts.eval_labels sample` generates stratified, de-duplicated, anonymized evaluation candidate pairs.
- **Quota Targets (Minimum Requirements for Statistical Validity):**
  - **Positive paraphrase pairs:** 200 pairs (semantically equivalent failure modes, differing vocabulary)
  - **Hard negatives (same entity/category, different failure):** 200 pairs
  - **Multi-symptom / compound failures:** 50 pairs
  - **Negation / hedged symptom mentions:** 50 pairs
  - **Novel / unmatched candidate failures:** 50 pairs
  - **Safety-critical language (loss of control, stall, fire, brakes):** 50 pairs
  - **Total Minimum Target:** $\ge 600$ pairs

---

## 2. Personnel Roles, Independence & Recruitment Profile

To prevent confirmation bias, **zero system authors or developers are permitted to annotate or adjudicate**.

| Role | Profile & Background | Key Responsibility | Disqualification Rule |
| :--- | :--- | :--- | :--- |
| **Annotator 1 (Domain Specialist)** | Automotive Quality / Warranty Systems Engineer | Evaluates whether technical failure mechanisms and vehicle sub-assemblies match. | Worked on ML code, embeddings, or prompts. |
| **Annotator 2 (Floor Specialist)** | Contact-Center Floor Supervisor / QA Lead | Evaluates customer intent, colloquial phrasing, and spoken phone complaint equivalence. | Worked on ML code, embeddings, or prompts. |
| **Adjudicator (Arbitrator)** | Senior Quality Director / Independent Systems Lead | Blindly resolves any discrepancy where Annotator 1 and Annotator 2 disagree. | Must not have served as Annotator 1 or 2; must not be system author. |

### Labeling Environment & Blind Controls:
- **Desk UI:** Web-based labeling portal at `/ui/#/label-desk`.
- **Blind Presentation:** Annotators see only verbatim complaint text, vehicle model, and component context.
- **Stripped Metadata:** Cluster IDs, model predictions, similarity scores, and provider identities are stripped from the payload.
- **Identifier Enclosure:** All annotator IDs must start with `human-*` (e.g. `human-ann-01`, `human-ann-02`, `human-adj-01`).

---

## 3. Operational Timeline & Execution Phases

- **Phase A (Week 1) — Recruitment & Onboarding:**
  1. Identify and recruit Annotator 1, Annotator 2, and the Adjudicator.
  2. Conduct 30-minute calibration walkthrough using 10 non-eval practice cases.
  3. Ensure labeling guidelines and class taxonomy definitions are memorized.
- **Phase B (Weeks 2–3) — Independent Annotation:**
  1. Generate stratified sample pairs: `python -m scripts.eval_labels sample --output eval/embeddings/unlabeled_eval_queue.jsonl`.
  2. Annotator 1 and Annotator 2 independently label pairs in blind rotation.
  3. Zero inter-annotator communication permitted during active labeling.
- **Phase C (Week 4) — Agreement Verification & Adjudication:**
  1. Execute agreement verification: `python -m scripts.eval_labels verify`.
  2. Calculate Cohen's $\kappa$ per class.
  3. Discrepancy queue automatically routed to the Adjudicator.
  4. Final adjudicated dataset committed to `eval/embeddings/pairs_human_v1.jsonl`.

---

## 4. Explicit Blocking Conditions (Hard Invariants)

The semantic activation gate (`FRONTLINE_EMBEDDING_MODE=semantic`) is **PROGRAMMATICALLY BLOCKED** under any of the following conditions:

1. **Ineligible Source Violation:** Any row originating from `coding_agent_seed`, `author_seed`, `synthetic`, or automated LLM generation is marked `acceptance_eligible: false` by `src/eval/embedding_gates.py`.
2. **Quota Deficit:** If any class quota in `decision_rules_v1.yaml` has fewer than the mandated sample count, `acceptance_ready` returns `False`.
3. **Inter-Annotator Agreement Failure:** If Cohen's $\kappa < 0.70$ (or class minimum $\kappa < 0.65$), the class is flagged as `blocked` and cannot be used to authorize production cutover.
4. **Unadjudicated Discrepancies:** If any disagreement between Annotator 1 and Annotator 2 lacks formal resolution by the Adjudicator, the dataset cannot be promoted.
5. **Threshold Drift:** If similarity distributions require adjusting `CLUSTER_MAX_DISTANCE` or `NOVELTY_MIN_SCORE`, cutover cannot proceed without calibrated cluster stability testing and formal engineering sign-off.
