# Skew AI — What to ADD to Become the Best (vs Axion, Option C)

**Date:** 2026-08-16
**Method:** 13-agent workflow — 6 product-strategy lenses proposed 36 feature bets → 6 adversarial critics
(5 killed, 31 survived) → ranked synthesis. Grounded in the verified codebase + Axion capability map.
**Definition of "best" (user-confirmed):** Win vs Axion — category-leading, lead on the audited-grounding + live-voice axes.

---

## Thesis

"Best" is not "most features." It is: **the only quality platform where every root-cause conclusion is a
tamper-evident, machine-checked, independently re-verifiable object rather than a consultant's assertion — and
where the highest-signal evidence is captured live and customer-confirmed while the line is still open.**

Everything below serves one wedge: **convert trust from a human's word ("eight engineers checked it") into a
re-executable cryptographic artifact the buyer's own regulator can re-run offline — and feed that engine with
live-voice evidence Axion structurally cannot obtain because it only reads cold transcripts.**

Axion's pipeline is CONNECT → NORMALIZE → DETECT → INVESTIGATE → TRACK-FIX, validated by expensive humans.
Skew credibly owns INVESTIGATE and has a real ledger/audit spine. Plan: (1) make the rest of the pipeline real
(table stakes), (2) weaponize the proof-and-voice moat Axion can't copy (win conditions), (3) go category-defining
on reproducibility (moonshots).

---

## Tier 1 — Table Stakes (without these you're a demo, not a platform)

| # | Add | Effort | Why it wins | Build on |
|---|---|---|---|---|
| 1 | **Deterministic embedding fix** | **S** | Silent correctness bug: process-salted `hash()` poisons clustering, "similar-case" retrieval, and *any* reproducibility claim. Highest leverage in the whole plan — hours of work unblocks the moat. | `ml_runtime/embeddings.py` (make blake2b the only path) |
| 2 | **Real anomaly engine** (make DETECT real) | **M** | Today "detection" is theater — `weekly_anomalies` z-scores are hardcoded literals. Can't sell against Axion's core verb while your anomalies are constants. Also the substrate for live interception (T2-5). | `qubot/retrievers.py::live_risk()`, `weekly_anomalies` |
| 3 | **Fix-effectiveness / recurrence loop** (make TRACK-FIX real) | **M** | A named Axion stage that's entirely absent. Turns you from "finds problems" into "proves fixes worked" — what quality VPs actually buy. | `learning_proposals` CAPA skeleton + `live_risk()` window |
| 4 | **Real cross-signal correlation** | **L** | Root-cause credibility collapses if "related signals" = the 5 most recent rows (`WHERE status/outcome LIMIT 5`). Replace with co-occurrence/association scoring. This is the analytical spine the audited conclusions sit on. | `qubot/retrievers.py`, `records(entity_1/2/3, category)` |
| 5 | **Multi-source inbound ingestion** (parallel long-pole) | **XL** | Axion's real moat is normalization over messy sources. Execute `mapping.yaml` so connectors ingest inbound, not just alert outbound. **Staff as a separate track — do NOT let it block the moat demos.** | domain-pack `mapping.yaml` spec + `records` schema |

---

## Tier 2 — Win Conditions (what makes you THE BEST, not merely present)

*All `axion-lacks-entirely` or `we-do-better`; survived critique with high impact. Ranked by leverage.*

**1. Content-addressed evidence + source-drift detection** — *M · axion-lacks-entirely*
On the write path, snapshot + hash each cited row's content into `evidence_snapshots`; the auditor then verifies the ID exists **and** content still matches — new `source-drifted` verdict. Fixes a confirmed bug (`_verify_evidence_id` re-queries the *live* warehouse, so an edited source row silently false-passes). No human process detects post-hoc drift in siloed PLM/ERP at scale. **Build first — it's the substrate the Locker + replay depend on.** → `qubot/auditor.py`, reuse `chain.py::_canon`.

**2. Evidence Locker: signed, self-verifying regulator/litigation bundle** — *M · we-do-better*
One-click bundle: full case trace + snapshotted cited evidence + hash-chain + `verify_chain` result + version stamp, **Ed25519-signed**, shipped with a **standalone offline verifier** so a regulator re-verifies *without Skew running*. The buyer's regulator becomes the verifier — vs Axion's hand-assembled consultant binders. ~60% built already. → `frontline/archive.py`, `dsr.py`, `ledger/chain.py`. *Drop "court-admissible" framing; defer the PDF.*

**3. Claim-level entailment auditor (span-bound)** — *M · axion-lacks-entirely*
Extend Qubot from ID-level to **claim-level**: each conclusion must cite an `evidence_id`, every asserted entity/category must match the cited row, and bind the **exact supporting char-span** in `records.text`. New `unsupported-claim` → report red → `needs_review`. This is *precisely the transcript-reading task Axion pays engineers for* — done deterministically across the whole corpus at zero marginal cost. *Scope to templated claims; defer free-text/numeric/negation NLP.* → `qubot/auditor.py`.

**4. Active Elicitation: engineering-directed questions injected mid-call** — *L · axion-lacks-entirely*
A diagnostic-question registry bound to cluster/category scope; when a live contact matches, Intake appends the engineer's question as a required slot and attaches the structured answer to the investigation. The purest "only voice can do this" — Axion mines what customers *happened* to say; it can never ask a follow-up. Elicits evidence that exists in *no* historical corpus → un-copyable data flywheel. → `frontline/dynamic_slots.py`, `agents/intake.py`.

**5. Live Cluster Interception: instant fleet re-score + in-call action** — *M · axion-lacks-entirely*
Wire `live_risk()` into the orchestrator's ENRICHING step so one live contact re-scores its cluster (including the in-flight call), checks the auto-open threshold live, delivers a grounded remedy, and fires a real-time "cluster crossing" alert to engineering. A batch tool learns the pattern days later; Skew acts within the same call. **Depends on T1-2.** → `qubot/retrievers.py`, `agents/orchestrator.py::_run_enrichment`, `alerts.py`, `remedy.py`.

**6. Customer-confirmed spoken evidence with hash-chained provenance** — *M · we-do-better*
Make every spoken datum a first-class evidence record (turn id, verbatim span, extraction method, `row_hash`); add a read-back confirmation ("So the warning only appears when cold — correct?") and ledger the yes/no. Qubot then verifies evidence as *customer-confirmed on the record with an unbroken chain* — something a cold transcript can never produce. → `ledger/writer.py`, `agents/intake.py`, `consent.py`.

---

## Tier 3 — Moonshots (compounding, category-defining)

**1. Global tamper-evident anchoring (Merkle transparency log)** — *M · axion-lacks-entirely*
Close the confirmed hole that chains are **per-interaction** (`verify_chain` scoped `WHERE interaction_id=?`), so a whole interaction could be dropped undetectably. Merkle-batch all row-hashes into a signed tree head with per-row inclusion proofs; add `verify_inclusion()`. Turns "we hash our rows" into "omission of any record anywhere is cryptographically detectable." *Defer external RFC-3161/public-ledger anchoring to enterprise-hardening.* → `ledger/chain.py`, `ledger/writer.py`, `jobs/queue.py`.

**2. Reproducible-by-construction replay harness (semantic)** — *L · axion-lacks-entirely*
A "REPRODUCE" button that re-runs the deterministic pipeline from recorded version stamps + cited-row snapshots and asserts the same cases/severities/cluster-matches/bindings re-derive. "Grounded by code" becomes literally executable. *Re-scope from bit-identical to semantic; contingent on T2-1.* → `interaction_version_stamps`, `backtest/engine.py`, `retrievers.py`.

---

## Sequencing: the 6-move game plan

Each move compounds and ends with a concrete proof point. (T1-5 ingestion runs as a **separate parallel track** — it gates scale, not the demos.)

1. **Make detection real + fix the vectors.** Deterministic embeddings (T1-1) + computed anomaly engine (T1-2). *Proof: an anomaly that recomputes live from data; clusters that reproduce across runs.*
2. **Pin evidence to the data that justified it.** Content-addressed snapshots + `source-drifted` verdict (T2-1). *Proof: edit a source row, re-run the audit, watch it flag drift no human catches.*
3. **Ground conclusions to the span.** Claim-level entailment auditor (T2-3). *Proof: click a conclusion → exact supporting span highlights; plant an unsupported claim → report goes red, case flips to needs_review.*
4. **Ship the Evidence Locker + offline verifier** (T2-2). *Proof: hand a "regulator" the bundle + standalone script; they re-verify signature + chain on an air-gapped laptop with Skew off.* **← This is the sales demo.**
5. **Turn voice into a fleet sensor.** Active Elicitation (T2-4) + Live Cluster Interception (T2-5) + confirmed spoken evidence (T2-6). *Proof: a live call answers an engineer's registered question AND tips a cluster into auto-open in the same call — hash-chained into the Locker.*
6. **Prove completeness + reproducibility.** Global Merkle log (T3-1), then semantic replay (T3-2). *Proof: prove no interaction was dropped; hit REPRODUCE and re-derive identical results.*

---

## What NOT to build (the traps)

- **KILLED — Calibrated-confidence precision SLAs in the contract.** With `experiment_trials`=0, `learning_proposals`=1, interactions=7, isotonic/Platt fits are noise; the "ground-truth" labels are circular (Qubot grading itself), and the "overturned" signal cited **doesn't exist in the code**. Putting a per-bin precision number in an MSA off ~10-row fixtures is a liability trap. Revisit only after real scale + independently adjudicated labels.
- **Don't compete on Axion's strengths.** No forward-deployed human validators, no services/consulting motion, no racing to PLM/ERP/Agentforce parity as move one. Staffing humans to validate insights *concedes your entire moat.*
- **Don't over-scope the crypto.** No bit-identical replay (needs deterministic clock+ID injection everywhere). No external timestamp-authority/public-ledger anchoring first. No full point-in-time warehouse snapshots — snapshot only cited rows.
- **Don't gold-plate.** Skip the Evidence Locker PDF (JSON + offline verifier *is* the proof). Skip the free-text claim decomposer with numeric/negation parsing (brittle without an LLM).
- **Don't let XL ingestion block the moat.** Foundational for scale, but staff it as its own track; the six moves prove the wedge on current data while it lands.
