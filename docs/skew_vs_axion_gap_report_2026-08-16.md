# Skew AI → Axion: Gap Report & Strategic Roadmap

**Date:** 2026-08-16
**Method:** 27-agent parallel analysis — 12 subsystem code readers (ground-truth, not docstrings) +
4 Axion research angles + 10-category gap matrix + synthesis. All load-bearing claims verified against source.
**One-line verdict:** Axion and Skew are *different products at opposite ends of the same value chain*.
A full "clone Axion" pivot is ~80% a rebuild. The right move is **Option C**: build Axion's analytical
core on your existing spine, and make **provably-grounded, audited root-cause the wedge Axion doesn't have.**

---

## 1. What axion.com actually is

`axion.com` = **Axion** (formerly *Axion Ray*; the domain rebrand is in progress, `axionray.com` 308-redirects to `axion.com`).

- **Category:** AI **product-quality / "customer quality intelligence"** platform for manufacturers of complex products (aerospace, automotive, medical device, HVAC, industrial, consumer).
- **What it does:** ingests fragmented, mostly-**unstructured** field data (telematics/fault codes, warranty claims, service/repair records, technician notes, NCRs, supplier audits, end-of-line test data, call-center logs, customer reviews, even unboxing videos), **normalizes** it into "a single coherent model" (their "product quality brain" / "Issue 360"), auto-**detects** emerging issues months earlier, lets engineers **investigate** root cause in a unified workspace ~85%/3× faster, and **tracks fix effectiveness** over time.
- **Shape:** batch, fleet-scale, System-2 analytics for a **quality/reliability engineer**. **No voice agent. No live customer conversation.** Call transcripts are just one more cold data source.
- **Moat:** (a) the data-integration/normalization layer across messy siloed sources; (b) **forward-deployed domain engineers who "validate every AI insight"** — a Palantir-style services-to-software flywheel ("eight engineers in a box"); (c) deep Salesforce (Agentforce/Field Service) + PLM/ERP integration.
- **Traction:** founded 2021 (Daniel First). ~$64M raised total (Series A $17M 2023; Series B ~$37.5M led by Salesforce Ventures, w/ Bessemer, Schneider Electric Ventures), ~$300M valuation. Customers: Boeing (seed investor), Cummins, SharkNinja, Daikin, Harley-Davidson, Medtronic, Pratt & Whitney/RTX, DENSO, PennEngineering. ROI proof: "$10M+ verified in 5 months" (HVAC), "$13M avoidable warranty" (aerospace), "10× first-year ROI" (Cummins).

---

## 2. The core mismatch

| Dimension | **Skew AI (what you built)** | **Axion (what you're pointing at)** |
|---|---|---|
| Primary input | A **live human conversation** (browser STT → agent swarm), one contact at a time | **Warehoused fleet data at rest**: telematics, warranty, service records, inspection logs, returned parts |
| Processing mode | **Real-time / System 1** — respond within a turn | **Batch / System 2** — deliberate correlation over months of history |
| Core user | The **customer** (talking) + a **supervisor** (watching) | A **quality / reliability engineer** working an issue queue |
| Unit of analysis | One `interaction_id` (`root_cause.py:22` is per-interaction) | A **population**: model / build-lot / VIN cohort |
| "Root cause" means | *Why did this conversation fail* (agent errored, frustrated, slots unfilled) | *Why is this physical part failing across the fleet* |
| Data scale (measured live) | ops: **7 interactions / 161 actions / 6 cases**; domains: **10 records, 3 anomalies, 2 backtest rows** each | Millions of claims + continuous telematics |
| Trust model | **Deterministic code audit** (Qubot re-queries every cited ID) | **Human services layer** ("expert team validates every AI insight") |

**Implication:** the assets that make Skew *distinctive* — voice channel, specialist-agent orchestrator, STT/TTS, live sentiment/sentinel loop — are **orthogonal to what Axion sells**. A full pivot discards your differentiated ~60% and keeps only thin analytical scaffolding that today runs on ~10 hand-written rows. The three things Axion is genuinely hard at — **multi-source ingestion, fleet-scale correlation, and the closed fix-effectiveness loop** — are exactly the three things Skew has essentially none of.

So the real question isn't "how do I become Axion." It's **"which of my real assets is a wedge into Axion's category that Axion itself lacks?"** (Answer: §6.)

---

## 3. What Skew genuinely already has (verified real, tested, wired — not stubs)

| Asset | Where | Why it matters for an Axion-like product |
|---|---|---|
| **Qubot groundedness auditor** ⭐ | `qubot/auditor.py:102-233` | The crown jewel. For every agent action it re-queries the source warehouse to confirm each cited evidence ID exists *and matches scope*, emits `grounded\|unverifiable\|mismatch`, and catches *uncited* IDs in output text. Deterministic, domain-agnostic, no LLM. **This is the moat.** |
| **Tamper-evident action ledger** | `ledger/chain.py:41-71`, `schema.py:155-156` | `prev_hash`/`row_hash` sha256 chain; `verify_chain` detects any insert/edit/delete. RCA that is *auditable by construction* — the enterprise-trust story Axion sells via humans. |
| **Two-warehouse spine + canonical schema** | `warehouse.py:39-95`, `schema.py:375-457` | The data model is *already multi-source-shaped*: `records` has `source` (NHTSA\|CFPB\|internal), `entity_1/2/3`, `category`, `region`, `embedding`. A legitimate normalization target. |
| **Real backtest engine** (lead-time) | `backtest/engine.py:33-143` | *Corrects the common assumption:* this is real code — computes `lead_time_weeks` from cluster first-seen vs advisory `issued_at`. Caveats: fixture-scale clusters, a synthetic-window fallback (`:113-117`), and shipped numbers (11/8 wks) are still seed literals until run on real data. But the skeleton is implemented, not faked. |
| **Clustering** | `clustering.py:46-186` | Hand-rolled k-means over embeddings, writes `clusters`/`cluster_assignments` w/ `top_terms`. Toy algorithm, but the table contract + rebuild job are real and consumed by live-risk + auditor. |
| **Domain-pack abstraction + mapping contract** | `domains/*/data/mapping.yaml`, `loader.py` | `pack_id` threads through the whole system as a clean product-line/tenant boundary. `mapping.yaml` already declares source→canonical column maps — the ETL *spec* exists; only the executor is missing. |
| **Learning-proposals CAPA skeleton** | `v3/learning.py:91-255` | `proposed→approved→deployed` workflow w/ taxonomy, reviewer, audit fields. A genuine corrective-action skeleton — retarget the taxonomy from conversation failures to failure modes. |
| **Alert transport** | `alerts.py:47-324` | Production-grade: SSRF guard, exponential backoff, success-gated dedup, dead-letter + single-shot replay, full ledgering. Keep as-is; add channels. |
| **RBAC + signed sessions + append-only security log** | `api/rbac.py:28-77`, `security/audit_log.py` | Real 5-role matrix, HMAC sessions, `require_perm` enforcement. A credible enterprise-controls *baseline* (SSO is still a stub). |
| **End-to-end wiring + tests** | `enterprise.py`, `frontline.py`, `tests/frontline/*` | RCA/timeline/decision-flow/risk/graph/memory are live FastAPI routes with a React page and passing tests. A working product skeleton, not a notebook. |

---

## 4. The hard gaps, ranked by difficulty

| # | Gap | Difficulty | Current state (evidence) |
|---|---|---|---|
| 1 | **Multi-source inbound ingestion** | **XL** | `connectors.py:1-4` is **outbound-only** ("not Salesforce/ServiceNow/Twilio"). Only real inbound = one live complaint or regex email. `mapping.yaml` is never executed (`warehouse.py:73` "full CSV ingest not shipped"). |
| 2 | **Scale: 10 → millions** | **XL** | Single-file DuckDB, all access under one lock (`warehouse.py:53-64`). `ingest_scale` templates rows but leaves them cluster-unassigned (`ingest_scale.py:139`). |
| 3 | **Real anomaly / statistics engine** | **High** | **The "we detected the spike early" headline is fixtures.** `weekly_anomalies.z_score` is hardcoded (6.0/2.0/0.0 literals, `seed_domains.py:112-118`); computed *nowhere* in `src`. Rule engine only does `count≥N` / `severity≥X`; `window_days` stored but unused. |
| 4 | **Cross-signal correlation / causal chains** | **High** | `similar_historical` is `WHERE status=? OR outcome=? LIMIT 5` (`root_cause.py:158-175`) — recency, not association. No statistical or graph correlation across sources. |
| 5 | **Investigation workspace (assignment + SLAs)** | **Med-High** | `investigations` table has only `open/monitoring/closed` (`schema.py:123-133`); RCA output is read-only JSON. No assignee, hypotheses, comments, SLA timers. |
| 6 | **Fix-effectiveness / recurrence loop** | **Med-High** | **Absent.** `learning.py` tracks proposal *review* status only; no before/after cohort, no `resolved_at`/reopen-rate anywhere in `src`. |
| 7 | **Entity resolution across sources** | **Med-High** | Only exact-hash single-source match (`memory.py:16-27`). No VIN/serial/customer multi-key, no fuzzy/survivorship. |
| 8 | **Deterministic embeddings / real semantic search** ⚠️ | **Med** | `embed_text` uses process-salted `hash()` (`embeddings.py:28`), **no `PYTHONHASHSEED` pin**. Persisted vectors are **incomparable across processes** — a silent correctness bug on the exact scale path. 64-dim, linear scan, no ANN. |
| 9 | **Enterprise readiness** | **Med** (well-trodden) | Single-tenant, not SOC 2. SSO is a discovery-doc stub (`rbac.py:229-244`); no object-level ACLs; no encryption at rest; `tenant_clause()` never called. |
| 10 | **Scheduled/continuous evaluation** | **Med** | No scheduler scans clusters. `subscriptions.tick_due` is a **stub** (`:113-147`); job queue allows only `audit_contact/rebuild_clusters/ingest_scale`. |

*(Full 10-category, ~40-row gap matrix with per-row effort + build guidance in the workflow output; condensed here.)*

---

## 5. Three strategic options

### Option A — Full pivot to an Axion clone
Rebuild as batch, fleet-scale, multi-source quality analytics for manufacturing engineers.
- **Reuse:** schema, backtest engine, clustering shape, alert transport, React chrome.
- **Build:** essentially everything Axion is.
- **Risk:** **Very high** — head-on vs a $64M-funded incumbent that owns the QE relationship + a human-validation moat, while you *discard your only differentiation*.
- **Time to credible demo:** 6–9 months to a believable fleet-scale RCA demo; 18+ to sellable.

### Option B — "Front door": VoC capture + audited signal layer feeding someone else's backend
Position Skew as the real-time capture + grounding layer that normalizes live contacts into clean, audited, structured signals and pipes them into an analytics backend (Axion, Foundry, warehouse).
- **Reuse:** the *entire* agent stack (your strength), Qubot audit, `records` schema as output contract, `connectors.dispatch_event`.
- **Build:** hardened outbound connectors + a clean signal-export API. Small.
- **Risk:** **Medium but capped** — you become a *feature*; the analytics vendor owns the customer and margin.
- **Time to credible demo:** **2–4 weeks** (you nearly have this).

### Option C — Hybrid: build the analytical core **and** keep audited-agent trust as the moat ✅ **RECOMMENDED**
Build a genuine (initially single-source) batch analytical core — ingestion → normalization → real anomaly detection → correlation → investigation workspace → fix-effectiveness — **on the schema you already have**, and make **provably-grounded, audited RCA (Qubot) the product's defining feature**. Keep voice as a *differentiated high-signal inbound connector*, not the whole product.
- **Reuse:** the whole spine + Qubot auditor + hash chain (the marketing wedge) + CAPA skeleton + FastAPI/React/tests harness.
- **Build:** one real inbound connector + mapping-driven ETL, a real statistical anomaly engine, cross-signal correlation, an assignment/SLA workspace, a fix-effectiveness loop.
- **Risk:** **Medium** — you compete in Axion's category on a *differentiated axis Axion can't cheaply copy* (deterministic, scalable grounding vs. expensive human validators).
- **Time to credible demo:** **6–8 weeks** to a differentiated single-source demo; 3–6 months to a defensible MVP.

| | Reuse of existing code | New build | Strategic risk | Time to demo |
|---|---|---|---|---|
| **A · Full clone** | Low (schemas only) | Enormous | Very high | 6–9 mo |
| **B · Front door** | Very high (agent stack) | Small | Medium — capped upside | 2–4 wks |
| **C · Hybrid** ✅ | High | Moderate, focused | Medium — differentiated | 6–8 wks |

**Recommendation: Option C, sequenced so its early phases *look like* Option B** (ship the audited-signal front door first, then thicken into the analytical core). A is a losing fight; B alone caps you at "feature"; **C is the only option that compounds your actual assets.**

---

## 6. The sharp differentiator bet

**Build the RCA platform whose every claim is provably grounded and tamper-evident — the trust layer Axion pays humans to fake.**

Axion's own answer to "can I trust the AI's root cause?" is a **services layer**: *"our expert team validates every AI insight."* That is expensive, slow, and doesn't scale — the most fragile, highest-cost part of their model. Skew already has the *software* answer, and it's your single most production-grade asset:

- **Qubot groundedness audit** (`auditor.py:102-233`) re-queries the source for **every cited evidence ID**, confirms existence + scope, flags `mismatch`, catches *uncited* IDs. Deterministic, no LLM in the verification path.
- **Tamper-evident hash chain** (`chain.py:41-71`) makes the entire reasoning ledger auditable by construction.

Together: **RCA where every conclusion carries a machine-checked, tamper-evident chain of custody back to source records — no human validators required.** For regulated buyers (auto, medical, aerospace) who must defend a root cause to a regulator or in litigation, this is the whole job, not a nice-to-have.

**The sellable sentence:**
> *"Every other AI quality tool asks you to trust the model — or pays humans to spot-check it. Skew is the only root-cause platform where each finding is automatically re-verified against source data and sealed in a tamper-evident chain. Grounded by code, not by consultants."*

It's **built**, it **reframes voice as an advantage** (audited-at-source VoC is higher-provenance than cold transcript scraping), it **attacks the incumbent where it's weakest**, and it **compounds** across every roadmap phase.

---

## 7. Phased roadmap (reuse-first; files named are ones to *extend*)

### Phase 0 — Weeks 0–4 · "Real data in, audited signal out"
- **Goal:** prove the normalization spine on **one real batch source**; ship the Option-B front-door artifact.
- **Deliverables:** (1) mapping-driven loader that *executes* `mapping.yaml` (DuckDB `read_csv`/`COPY` → canonical upsert), registered as a new `job_queue` type; (2) load a **real** NHTSA complaints CSV at 10k–100k rows into `records`, replacing the 10 fixtures; (3) **fix the embedding determinism bug** (`embeddings.py:28` → stable hash or real sentence-transformer; backfill vectors); (4) harden `connectors.dispatch_event` into a clean audited-signal export.
- **Extend:** `scripts/ingest_scale.py`, `mapping.yaml`, `warehouse.py`, `embeddings.py`, `connectors.py`, `jobs/queue.py`.
- **Demo:** "50k real NHTSA complaints ingested through the declared mapping, clustered, and every record Qubot cites re-verifies against source — with a tamper-evident chain."

### Phase 1 — Months 1–3 · "Real early warning + real correlation"
- **Goal:** replace fixture anomalies with a genuine detector + real cross-signal join; add a second source.
- **Deliverables:** (1) **statistical anomaly engine** that computes `weekly_anomalies` (rolling mean/std z-score, rate-of-change) — retire the hardcoded 6.0; feed `alert_rules` so triggers are statistical; (2) run the **real backtest at volume** so lead-time is computed, not seeded; drop the synthetic fallback on the demo path; (3) a **second source** (warranty/service CSV) landing in `records` with `source` set; (4) correlation v1: replace `similar_historical`'s `LIMIT 5` with real association (co-occurrence/lift across `source`, `category`, `entity_2`).
- **Extend:** new `src/ml_runtime/anomaly.py`; `alert_rules.py`; `backtest/engine.py`; `root_cause.py:158-175`; `analytics.py`.
- **Demo:** "On real data, the system flagged this cluster rising **N weeks before** the recall — lead time computed from data, not a fixture."

### Phase 2 — Months 3–6 · "Investigation workspace + fix-effectiveness"
- **Goal:** turn read-only RCA JSON into a workable investigation loop with a closed fix-effectiveness measurement — the two capabilities that make Axion "a platform."
- **Deliverables:** (1) extend `investigations` with `assignee`, `sla_due`, `hypotheses`, richer status transitions; wire assignment + SLA timers into routes + React; (2) **fix-effectiveness loop**: before/after cohort analysis by build-date/entity; add `resolved_at`/recurrence; retarget the `learning_proposals` CAPA taxonomy from conversation weaknesses to failure modes; (3) **entity resolution v1**: promote `contact_memory`'s hash-match into a multi-key (VIN/serial/customer) linker w/ survivorship; (4) make `subscriptions.tick_due` actually render + send on schedule.
- **Extend:** `enterprise/root_cause.py`, `v3/learning.py`, `enterprise/memory.py`, `frontline/subscriptions.py`, `schema.py`, dashboard.
- **Demo:** "Open a flagged issue, assign it with an SLA, work it to a documented fix, then watch recurrence on the affected cohort drop over the following weeks — every insight audit-verified."

### Phase 3 — Months 6–12 · "Scale + enterprise + the voice moat"
- **Goal:** re-platform storage, add enterprise controls, light up the differentiated voice-capture channel.
- **Deliverables:** (1) storage re-platform off single-file DuckDB (`postgres_backend.py` is the seam) + real vector index (pgvector/FAISS); (2) multi-tenant isolation (thread `pack_id`/`ops/tenant.py`), real SSO (OIDC/JWKS), object-level RBAC, SOC 2 track; (3) **voice-as-connector**: reframe the live agent stack as a *premium inbound source* — structured, audited VoC captured at the moment of conversation, landing in `records` alongside warranty/telematics.
- **Extend:** `data/postgres_backend.py`, `ops/tenant.py`, `api/rbac.py`, `api/auth.py`, orchestrator-as-producer.
- **Demo:** "A customer reports a brake problem by voice; within seconds it's a structured, source-audited record correlated against 100k warranty claims — and it moved the fleet anomaly score in real time. No competitor turns a live conversation into fleet-grade quality signal."

---

## 8. Do this week (regardless of which option)

1. ⚠️ **Fix the embedding non-determinism bug** (`embeddings.py:28`). It's a silent correctness bug: vectors persisted by `ingest_scale` (one process) are incomparable to query vectors in the API process. Pin `PYTHONHASHSEED`, switch to `hashlib`/blake2, or drop in a real sentence-transformer. Everything "semantic" is quietly broken across process boundaries until this is fixed.
2. **Reconcile your docs with reality.** `docs/feature_list_deep_research.md` (2026-07-28) still calls `src/ai/`, `src/ml_runtime/`, `src/backtest/`, `src/domains/builder/` *empty* — they're now populated. And `weekly_anomalies` z-scores are seed literals, not computed; say so or compute them. Honesty here is cheap and protects the trust story.
3. **Pick the option.** If you want an investor/design-partner demo fast, do Phase 0 (front door) now. If you're committing to the category, commit to Option C.

---

## 9. Bottom line

You did not build "an Axion." You built something Axion *doesn't have*: a real-time, audited, grounded agent layer. Cloning Axion head-on wastes that. **Build Axion's analytical core on the spine you already have, and lead with the one claim the funded incumbent can't make — provably-grounded, tamper-evident AI root cause. Grounded by code, not by consultants.**
