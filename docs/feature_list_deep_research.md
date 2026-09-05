# Frontline v2 (`v2_ai_rca_tool`) — Feature List Deep Research

*Generated: 2026-07-28; reconciled 2026-08-16 (Phase 0 Option C)*  
*Codebase: `/Users/rahulkumarsinghj/DeveloperFolder/Code/v2_ai_rca_tool`*  
*Sources: live tree audit + residual report + README + pack manifests + external compliance/product research*  
*Confidence: **High** on code status (read from tree); **Medium** on market/priority judgment*

---

## Chosen path: Option C (hybrid)

Do **not** clone Axion (batch fleet analytics, no voice). Keep voice/agents/Qubot as the high-signal front door and thicken the analytical spine on the existing two-warehouse schema: mapping-driven ingest, process-stable embeddings, audited-signal export.

> **2026-09 remediation update:** `src/ml_runtime/anomalies.py` now ships the
> statistical engine (quasi-Poisson residuals on zero-filled weekly buckets,
> BH-FDR, event-clock `occurred_at`) — `recompute_weekly_anomalies()` computes
> every `weekly_anomalies` row on live paths and investigation intercepts.
> Seed scripts still ship small literal fixture rows (6.0/2.0/0.0) so offline
> demos render without ingest; they are demo fixtures, recomputed on any live
> path, and `backtest_results` rows now carry `provenance` (`fixture` vs
> `computed`) so fixtures can never masquerade as observed evidence.

---

## Executive summary

You already have a **real, demoable, dual-pack product**: explicit orchestrator, six agents, ledger-before-emit, Qubot auditor, browser voice, supervisor takeover, early-warning board, entity memory, dual-pack offline eval, Docker pilot kit. That is more than most early AI startups ship.

The AI/ML trees are **populated**, not empty: `src/ai/` (optional LLM narration), `src/ml_runtime/` (512-dim bag-of-hash embeddings + clustering + statistical anomaly engine), `src/backtest/` (entity-gated lead-time engine), `src/domains/builder/` (Pack Builder MVP). What you **do not** have is **default** scale data (fixture ~10 records/pack unless `ingest_nhtsa` / a mapped CSV is run), **real telephony**, and **enterprise compliance** (SSO/multi-tenant). Seed anomaly rows remain literal demo fixtures (recomputed on live paths) — selling fixture spikes as detected anomalies would contradict the seed scripts.

**What you need to build depends on the next milestone:**

| Milestone | Need from the 56-list (core) |
|-----------|------------------------------|
| **A. Honest pilot / paid PoC** | Stabilize + (2) semantic similarity *or* stop claiming embeddings + (40) real-scale ingest + (31) hash-chain + (33) consent + wallboard/digest polish |
| **B. “Every README claim true”** | A + (1) LLM narration + (4) real backtest + (39) Pack Builder + (3) severity model honesty |
| **C. Call-center enterprise** | B + (8–9) telephony/STT + (32)(34) PII/DSR + (50) RBAC/SSO + (45–47) Postgres/queue/observability |
| **D. Self-serve SaaS** | C + (52) multi-tenant + (56) metering + (41) pack registry |

**If only six after critical bugfix** (aligned with the list’s own recommendation, validated against code):  
**1 LLM · 2 semantic · 4 backtest · 39 Pack Builder · 40 ingest · 31 hash-chain** — then **45–47** as follow-on.

---

## 1. What the product is today (code-grounded)

### Shipped and working

| Area | Evidence |
|------|----------|
| Domain-as-data packs | `domains/automotive_nhtsa`, `finance_cfpb`, `_template`; pack lint/loader |
| Agents | intake, sentiment, triage, sentinel, investigator, case + orchestrator |
| Browser voice | `web_voice.py` + dashboard CallWidget (Web Speech STT/TTS) |
| Channel abstraction | `ChannelAdapter` in `channels/base.py` |
| Supervisor path | takeover actions in ledger; Live Contact Console |
| Frustration → handoff | `frustration_threshold` in config; orchestrator/cli |
| Advisory + case + investigation | case_agent, alerts (`investigation_opened`, early warning) |
| Qubot audit + digests | `auditor.py`, CLI audit/digest, SHA256 export path |
| Enterprise ops (deterministic) | memory, risk, copilot SQL router, scenarios, timeline, root_cause |
| v3 registries | experiments, governance, learning (registry-level, not live traffic) |
| Pilot security | API key, auth required mode, URL SSRF guard, single-worker documented |

### Explicitly stub / honesty (must not market as computed or empty)

| Path | Status |
|------|--------|
| `src/ai/` | **Populated** — optional narration when `FRONTLINE_LLM_ENABLED=1` + key; default is still templates |
| `src/ml_runtime/` | **Populated** — process-stable bag-of-hash embeddings + in-process clustering |
| `src/backtest/` | **Populated** — lead-time engine; still typically run on fixture-scale data |
| `src/domains/builder/` | **Populated** — Pack Builder MVP (`make pack-init`) |
| `weekly_anomalies.z_score` | **Computed** by `src/ml_runtime/anomalies.py` (quasi-Poisson + BH-FDR) on every recompute/live path. Seed scripts still ship small literal fixture rows (6.0/2.0/0.0) for offline demos; recompute replaces them (`provenance='computed'`). |
| `src/channels/twilio_stub.py` | **NotImplementedError** on all methods |
| Corpus scale | **Default fixture ~10 / 2 / 3.** Mapping-driven ingest (`src/domains/mapping_ingest.py`, `make ingest-nhtsa`) can load real NHTSA rows. `ingest_scale` is synthetic and is not NHTSA proof. |

### Partial / “half-built”

| Capability | Reality |
|------------|---------|
| Similar records / RCA | **Association + embedding-fused cluster scoring** (`investigator.py`: full-corpus lift, semantic re-rank, entity-overlap cluster fuse) with ILIKE fallback when embeddings are missing |
| Severity XGBoost | Pack *advertises* `automotive_nhtsa/severity_xgb`; runtime missing → rules |
| Clusters | Hand-seeded fixtures, not auto-clustered |
| Entity memory | Exists (`contact_memory`); not voice biometrics / “case CS-1042” UX |
| Alerts | Webhook + dedup + dead-letter; thresholds env/hardcoded, not analyst UI rules |
| Auth | Shared pilot secret — not RBAC/SSO |
| Experiments | Control/candidate registry — not live A/B traffic |

---

## 2. Full matrix: features 1–56 vs codebase

**Legend:**  
**Built** = production-usable in tree · **Partial** = hooks/UI/schema without full capability · **Missing** = empty/stub/absent · **Need** = Must / Should / Later / Optional

### A. AI/ML layer

| # | Feature | Status | Need for *this* product | Notes |
|---|---------|--------|-------------------------|-------|
| 1 | LLM narration layer | **Missing** | **Should** (pilot wow) / Must for “AI” buyers | 3 call sites only; fallback deterministic is already your ethos |
| 2 | Semantic similarity | **Partial** — `embed_text` + cosine ranking shipped; investigator may still ILIKE-fallback | **Must** if selling corpus RCA | Embeddings are process-stable (blake2b); not MiniLM |
| 3 | Trained severity model | **Missing** runtime; **Partial** pack + triage hook | **Should** for auto pack honesty | Auto-discover registry + honest `severity_source` |
| 4 | Real backtest engine | **Partial** — `src/backtest/engine.py` computes lead time; volume still fixture-scale | **Must** for “weeks before recall” claim | Highest-credibility sales number |
| 5 | Auto-clustering | **Partial** — `src/ml_runtime/clustering.py`; demo clusters still seeded | **Should** once ingest scales | Fixture `weekly_anomalies` z-scores remain seed literals |
| 6 | LLM-as-judge eval | **Missing** | **Later** | Keep CI hermetic; optional online track |
| 7 | Prompt registry versioning | **Missing** | **Should** with #1 | Matches pack_version/trust architecture |

### B. Voice and channels

| # | Feature | Status | Need | Notes |
|---|---------|--------|------|-------|
| 8 | Twilio Media Streams | **Stub** | **Must** for call-center sales; Later for browser pilot | Biggest buyer credibility jump |
| 9 | Server STT/TTS | **Missing** | **Should** before telephony; Optional for demo | Browser STT Chrome-flaky |
| 10 | WhatsApp/SMS | **Missing** | **Later** | Proves adapter; market-dependent |
| 11 | Email intake | **Missing** | **Later** | Ticket inboxes without behavior change |
| 12 | Inbound webhook ingest | **Partial** (connectors exist) | **Should** for day-1 integration | Zendesk/Intercom pipe |
| 13 | Multilingual | **Missing** | **Later** (or Must for India/LATAM pilots) | Pack-configured |
| 14 | Voice biometrics | **Missing** | **Optional** | Memory exists; biometrics heavy/legal |

### C. Agent capabilities

| # | Feature | Status | Need | Notes |
|---|---------|--------|------|-------|
| 15 | Case-status by number | **Missing** UX | **Should** | Memory + cases already there |
| 16 | Resolution/remedy agent | **Missing** | **Should** for ROI story | Deflection = budget math |
| 17 | Dealer booking | **Missing** | **Later** / vertical-specific | OEM KPI |
| 18 | Multi-issue handling | **Missing** | **Should** | Real calls multi-issue |
| 19 | Confidence-gated escalate | **Partial** (frustration only) | **Should** | Two-signal handoff |
| 20 | Self-critique checklist | **Missing** | **Should** | Pre-emit integrity |
| 21 | Callback scheduling | **Missing** | **Later** | Call-center table stakes |
| 22 | Dynamic slot skipping | **Partial** (memory exists) | **Should** | Eval gates ≤12 turns |

### D. Early warning and analytics

| # | Feature | Status | Need | Notes |
|---|---------|--------|------|-------|
| 23 | Alert rules engine UI | **Partial** (env alerts) | **Should** | Analyst-owned product surface |
| 24 | Cluster volume forecast | **Missing** | **Later** | Strong sentence; after scale data |
| 25 | Cross-pack patterns | **Missing** | **Later** / differentiator | Unique to multi-pack schema |
| 26 | Geo/temporal maps | **Partial** (`region` column) | **Later** | Needs real geo data |
| 27 | Severity drift | **Missing** | **Should** | Cheap signal, high value |
| 28 | Cohort/batch analysis | **Missing** | **Should** for quality eng | VIN/batch after richer schema |
| 29 | Regulator-filing watch | **Missing** | **Should** with backtest | Continuous proof loop |
| 30 | Financial impact $ | **Missing** | **Later** | Buyers approve dollars |

### E. Trust, audit, compliance

| # | Feature | Status | Need | Notes |
|---|---------|--------|------|-------|
| 31 | Hash-chained ledger | **Missing** | **Must** for regulated pilots | ~100 lines; industry expects tamper-evident logs |
| 32 | PII redaction | **Missing** | **Must** for bank/OEM security review | First security questionnaire |
| 33 | Consent / recording disclosure | **Missing** | **Must** before real call recording | Legal in most jurisdictions |
| 34 | Data-subject requests | **Missing** | **Must** for EU/CA bank pilots | Multi-table delete/export |
| 35 | Immutable audit archive | **Partial** (SHA256 export) | **Should** | Package for regulator |
| 36 | Decision explainability UI | **Partial** (ledger data) | **Should** | Surface causal chain |
| 37 | Bias/fairness monitoring | **Missing** | **Should** for CFPB-adjacent | Escalation unevenness |
| 38 | Four-eyes approval | **Missing** | **Should** for high-impact actions | Fits action model |

External research: voice AI / call centers need **explicit consent**, **audit-ready logs**, **PII controls**, and increasingly **tamper-evident audit trails** (hash-chained logs appear in compliance guidance for AI agents and call centers).

### F. Onboarding and packs

| # | Feature | Status | Need | Notes |
|---|---------|--------|------|-------|
| 39 | Pack Builder MVP | **Missing** | **Must** for scale GTM | Biggest commercial lever |
| 40 | Real-scale ingest | **Partial** — `mapping.yaml` executed by `mapping_ingest` + `ingest_nhtsa`; default DB still 10-row fixture | **Must** for expert demos | `ingest_scale` is synthetic and is not NHTSA proof |
| 41 | Pack marketplace | **Missing** | **Later** | After Builder works |
| 42 | 3rd/4th verticals | **Partial** (_template) | **Should** after 2 solid | MAUDE / CPSC free |
| 43 | Live pack editor | **Missing** | **Later** | Product vs consulting |
| 44 | Pack A/B | **Partial** (v3 experiments) | **Later** | Wire live traffic carefully |

### G. Ops, reliability, scale

| # | Feature | Status | Need | Notes |
|---|---------|--------|------|-------|
| 45 | Postgres + Alembic | **Missing** | **Must** before multi-worker | DuckDB ops single-writer |
| 46 | Background job queue | **Missing** | **Must** with scale | Audits/ingest/cluster off loop |
| 47 | Observability stack | **Partial** | **Must** for production | Logs/metrics/traces/Sentry |
| 48 | Load/soak tests | **Missing** | **Should** | Find concurrency bugs |
| 49 | Chaos tests | **Missing** | **Should** | Defined failure states |
| 50 | RBAC then SSO | **Missing** | **Must** for multi-user pilot | Takeover needs identity |
| 51 | Blue-green / drain | **Missing** | **Should** | Deploy mid-call |
| 52 | Multi-tenancy | **Missing** | **Later** (SaaS) | Last intentionally |

### Bonus commercial UI

| # | Feature | Status | Need | Notes |
|---|---------|--------|------|-------|
| 53 | Supervisor whisper/coach | **Missing** | **Later** | After takeover solid |
| 54 | Wallboard | **Missing** | **Should** (cheap win) | Ops wall mount |
| 55 | Scheduled digests | **Partial** (CLI digest) | **Should** | Cron + Slack/email |
| 56 | Usage metering | **Missing** | **Later** | Pricing prerequisite |

---

## 3. What you *must* build vs *should not* build yet

### Must-build (honest product + next pilot)

These close gaps between **claims** and **code**, or unlock security reviews:

1. **#40 Real-scale ingest** — Without this, domain experts kill the demo.  
2. **#2 Semantic similarity** *or* rewrite all marketing to “SQL/gazetteer retrieval” (never “embeddings”).  
3. **#4 Real backtest** — Only path to the “N weeks before recall” proof.  
4. **#31 Hash-chained ledger** — Cheap trust upgrade.  
5. **#33 Consent disclosure** — Before any recording narrative.  
6. **#32 PII detection/redaction** — Bank/OEM questionnaire.  
7. **#39 Pack Builder (MVP)** — Or stay forever hand-onboarding (playbook only).  
8. **#1 LLM narration (capped + fallback)** — Optional for engineering purity; **required** for many buyers’ mental model of “AI agent.”  
9. **#3 Severity model *or* remove pack advertisement of XGBoost** — Honesty.  
10. **#45–47 + #50** — Before multi-user production, not before first demo.

### Should-build (product depth, after Must)

- #5 clustering, #15 case status, #16 remedy agent, #18 multi-issue, #19–20 confidence + self-critique  
- #23 alert rules UI, #27 severity drift, #29 regulator watch  
- #8–9 telephony path when a call-center pilot is signed  
- #35–38 explainability, four-eyes, fairness  
- #54–55 wallboard + scheduled reports  

### Later / deliberately last

- #14 biometrics, #41 marketplace, #44 live A/B, #52 multi-tenant, #56 metering  
- #42 extra verticals until Pack Builder + ingest mature  
- Full #37 fairness suite before you have demographic fields and legal cover  

### Do not build early (distraction risk)

| Feature | Why wait |
|---------|----------|
| Full Twilio (#8) before server STT (#9) and consent (#33) | Legal + architecture prerequisites |
| Multi-tenant (#52) before Postgres (#45) and RBAC (#50) | Will rework every table twice |
| LLM-as-judge (#6) before hermetic eval is green | CI noise |
| Cross-pack (#25) / geo maps (#26) before real data (#40) | Empty charts |
| Financial model (#30) before backtest credibility (#4) | Dollars on fake lead times |

---

## 4. Phased plan (what to build in what order)

### Phase 0 — Integrity (1–2 weeks)

- Close residual **H5** (API keys out of query strings) if still open  
- Fix any remaining concurrency/takeover issues with **#48** smoke load test  
- Document non-goals: no embeddings claim, no XGBoost claim, fixture scale honesty  

**Exit:** Demo script matches code; no false README bullets.

### Phase 1 — “Claims become true” (4–8 weeks) — *the six*

| Order | # | Outcome | Effort |
|------:|---|--------|--------|
| 1 | **40** ingest | Full NHTSA/CFPB (or large sample) loadable | M |
| 2 | **2** semantic sim | Cosine over MiniLM in DuckDB; ILIKE fallback | M |
| 3 | **4** backtest | Real lead-time weeks from replay | M |
| 4 | **31** hash-chain | Tamper-evident `agent_actions` | S |
| 5 | **1** LLM layer | 3 sites + cap + spend + deterministic fallback | M |
| 6 | **39** Pack Builder MVP | CSV → draft pack → lint → smoke | L (MVP slice) |

Also in Phase 1 honesty: **#3** ship model artifact *or* strip `model_artifact` from pack until ready.

**Exit:** Domain expert can search real-ish corpus; backtest number is real; audit chain hashable; pack onboard not only hand YAML.

### Phase 2 — Pilot enterprise (4–6 weeks)

| # | Focus |
|---|--------|
| 33, 32, 34, 35 | Consent, PII, DSR, regulator bundle |
| 15, 22, 19, 20 | Case status, skip known slots, confidence handoff, self-critique |
| 54, 55, 12 | Wallboard, scheduled digest, webhook ingest |
| 23, 27 | Alert rules UI, severity drift |

**Exit:** Security questionnaire answerable; ops wall mountable; ticket systems can inject.

### Phase 3 — Call center path (6–10 weeks)

| # | Focus |
|---|--------|
| 9 then 8 | Server STT/TTS → Twilio Media Streams |
| 50 | RBAC → OIDC |
| 45, 46, 47 | Postgres ops, queue, OTEL/Sentry |
| 51, 48, 49 | Drain drain, load, chaos |

**Exit:** Real phone number pilot; multi-user named supervisors.

### Phase 4 — Platform / SaaS (ongoing)

| # | Focus |
|---|--------|
| 5, 29, 28 | Clustering, regulator watch, cohort |
| 16, 17 | Remedy + booking |
| 41–44, 42 | Pack ecosystem + 3rd vertical |
| 52, 56 | Multi-tenant + metering |
| 10, 11, 13 | SMS/email/i18n as market demands |

---

## 5. Acceptance criteria for the “only six”

### 1 — LLM narration
- [ ] Provider interface: OpenAI-compatible + optional Anthropic + Ollama  
- [ ] Used only: intake phrasing, investigator brief, follow-up draft  
- [ ] `FRONTLINE_LLM_TURN_CAP` + daily spend ledger enforced  
- [ ] No key / cap / error → **identical deterministic templates** as today  
- [ ] Interaction stamps model id + prompt hash when LLM used  

### 2 — Semantic similarity
- [ ] Embeddings stored; `array_cosine_similarity` (or equivalent) primary path  
- [ ] ILIKE fallback if no embedding  
- [ ] Investigator evidence IDs still Qubot-verifiable  
- [ ] Latency budget documented on fixture + 10k-row pack  

### 4 — Real backtest
- [ ] Replays historical weeks; detects spikes; joins advisories  
- [ ] Writes `backtest_results.lead_time_weeks` from computation not fixtures  
- [ ] Demo script can cite real number for at least one pack  

### 39 — Pack Builder MVP
- [ ] CSV upload → column mapping UI or CLI → draft pack.yaml  
- [ ] Gazetteer stubs + seed sample → lint passes  
- [ ] Smoke `make contact` on generated pack  
- [ ] Document limitations (not full magic)  

### 40 — Real-scale ingest
- [ ] Stream/batch ≥10k NHTSA-shaped rows into domain DuckDB  
- [ ] Progress + resume; CI still uses fixtures  
- [ ] Demo uses large DB via config, not only seed script  

### 31 — Hash-chained ledger
- [ ] Each `agent_actions` row includes `prev_hash` + `row_hash`  
- [ ] Verification CLI fails on tamper  
- [ ] No performance regression on eval-frontline  

---

## 6. Market / product research (why this ordering)

**Your wedge is not “another chatbot.”** It is:

1. **Domain pack** abstraction (two verticals already),  
2. **Audit-first agents** (ledger + Qubot),  
3. **Early warning with lead-time proof** (backtest — currently fixture fiction).

Competitors in adjacent space (voice agents, VOC analytics, quality/safety surveillance) typically win on **integrations (phone, ticketing)**, **compliance (consent, PII, audit)**, and **credible analytics on real volume**. They often lose on **groundedness and pack portability** — your differentiators if you finish 2 + 4 + 31 and stay honest about deterministic fallback.

**Call-center / regulated buyers** (OEM quality, bank complaints) will block on:

- Recording **consent** and retention  
- **PII** handling  
- Named human **identity** for takeovers  
- Tamper-evident **audit**  
- Not on Prophet forecasts or biometrics  

**GTM implication:** Phase 1 makes the *science claim* true; Phase 2 makes *procurement* possible; Phase 3 makes *ops deployment* possible; Phase 4 makes *SaaS* possible.

---

## 7. Effort roll-up (rough)

| Phase | Features (main) | Calendar (1–2 strong eng) |
|-------|-----------------|---------------------------|
| 0 Integrity | residual + load smoke | 1–2 weeks |
| 1 Six core | 1,2,4,31,39,40 (+3 honesty) | 6–10 weeks |
| 2 Pilot enterprise | 12,15,19,20,22,23,27,32–35,54,55 | 4–6 weeks |
| 3 Telephony + scale | 8,9,45–51 | 6–10 weeks |
| 4 Platform | 5,10,11,16,17,25,28,29,41,42,52,56 | Ongoing |

**Total to “enterprise call-center pilot ready”:** roughly **4–6 months** focused; full 56-item list is **12–18+ months** and should not be treated as one backlog without phases.

---

## 8. Decision matrix: “What should *I* build next?”

Answer based on your goal:

| Your goal next 90 days | Build this subset |
|------------------------|-------------------|
| **Investor / technical demo credibility** | 40 → 2 → 4 → 31 → wallboard 54 |
| **First paid OEM/bank pilot** | 40 → 32 → 33 → 31 → 12 → 15 → 1 (optional polish) |
| **Self-serve “upload tickets” story** | 39 → 40 → 43 later |
| **Call-center RFP** | 33 → 9 → 8 → 50 → 45–47 |
| **Stay pure offline deterministic** | Skip 1 and 6; do 2,4,40,31,39; rewrite AI marketing |

---

## 9. Key takeaways

1. **Core product is real**; AI/ML dirs are populated. Honesty traps are fixture-scale data and **seed** `weekly_anomalies` demo rows (recomputed on live paths), not empty folders.  
2. **Fixture-scale data + ILIKE fallback** remain honesty traps — mapping ingest + stable embeddings shipped; spike detection is computed (quasi-Poisson + FDR) wherever recompute runs. Do not present seed fixtures as detections.  
3. **Pack Builder (39)** is the GTM multiplier; without it you are a services-shaped product.  
4. **Hash-chain (31) + consent (33) + PII (32)** are cheaper than Twilio and unlock regulated conversations.  
5. **Postgres/queue/observability (45–47)** and **RBAC (50)** before multi-tenant (52).  
6. Do **not** implement the full 56 list linearly — use phases 0→4.  
7. The list’s “only six” recommendation is **validated by this codebase audit** and remains the best engineering+sales combo after bugfixes.

---

## 10. Methodology

- Walked live tree: `src/*`, packs, schema, dashboard, Makefile, README, `docs/residual_audit_report.md`  
- Reconciled 2026-08-16: `src/ai/`, `src/ml_runtime/`, `src/backtest/`, `src/domains/builder/` are populated. `weekly_anomalies.z_score` is fixture/seed, not computed in `src`.  
- Reconciled 2026-09-05 (remediation): anomaly z-scores ARE computed in `src/ml_runtime/anomalies.py` (quasi-Poisson + BH-FDR); the 2026-08-16 "not computed" note above is superseded. Seed rows remain literal demo fixtures (`provenance='fixture'`). Investigator now fuses embeddings + full-corpus lift; backtest requires entity overlap.  
- Confirmed ILIKE path in `investigator.py`; rules-only severity in `triage.py`  
- Confirmed Twilio `NotImplementedError`; `FRONTLINE_LLM_TURN_CAP` reserved unused  
- Web research: GDPR/consent/audit expectations for voice AI and call centers (2024–2026 sources)  
- Sub-questions: (1) what exists, (2) what the list claims, (3) what pilots need, (4) sequencing  

---

## Sources (code + external)

**Internal (primary):**  
- `README.md`, `docs/residual_audit_report.md`, `docs/frontline_architecture.md`  
- `src/agents/investigator.py`, `triage.py`, `orchestrator.py`  
- `src/channels/*`, `src/data/schema.py`, `src/ledger/writer.py`  
- `domains/automotive_nhtsa/pack.yaml`  

**External (compliance context):**  
- [GDPR Compliance for AI Voice Agents](https://answeringagent.com/blog/gdpr-compliance-for-ai-voice-agents) — consent, ROPA, hash-chained audit trails  
- [ASC Technologies — Call center GDPR](https://www.asctechnologies.com/blog/post/gdpr-compliance-call-center/) — recording consent, retention  
- [How to Audit Voice AI Agents for Regulatory Compliance](https://www.linkedin.com/pulse/edition-48-how-audit-voice-ai-agents-regulatory-compliance-3jwuc) — disclosure, immutable trails  
- [Secure Privacy — Consent audit evidence](https://secureprivacy.ai/blog/gdpr-consent-audit-evidence-requirements) — burden of proof on controller  

---

*End of report. For implementation, start Phase 0 + Phase 1 acceptance criteria above.*
