# Frontline v2 — Residual risk audit report

| Field | Value |
|-------|--------|
| **Date** | 2026-07-21 |
| **Tree** | `/Users/rahulkumarsinghj/DeveloperFolder/Code/v2_ai_rca_tool` |
| **Kind** | Analysis (2026-07-21) + residual-defect closure pass same day |
| **Scope** | Live tree only (`ai_rca_platform/v2_ai_rca` is empty and out of scope) |
| **Method** | Systematic surface review of `src/**`, `dashboard/routes/**`, `docs/**`, `tests/frontline/**`, Docker/CI/Makefile, domain packs, eval, scripts; re-verification of previously claimed pilot fixes against shipped code |

**Note on exhaustiveness:** This report aims for full *surface* coverage of every major package, route family, and stub listed below. It is not a formal line-by-line proof of every LOC. Net-new findings (beyond prior audit essays) are marked **[NEW]**.

---

## Executive summary

The **deterministic core** (domain packs, six agents, ledger-before-emit on critical paths, dual-pack offline eval, Qubot auditor, pilot kit: Docker, auth, export, alert retry) is real and industrial-grade for a **single-tenant demo / paid pilot** on fixture data.

What still fails is almost always at **concurrency, multi-user ops, honesty vs claims, and dashboard wiring under pilot auth**. The product is safe to demo as “offline-proven dual-vertical contact intelligence with audit ledger.” It is **not** safe to market as multi-worker SaaS, real telephony, semantic ML RCA, or enterprise-ready security/compliance without the residual list below.

---

## 0. Verified fixed (prior pilot / week-one work)

These were claimed fixed in earlier passes; re-checked against live code on 2026-07-21.

| Item | Evidence (shipped path) | Status |
|------|-------------------------|--------|
| Pack switcher | `src/domains/active_pack.py` → `resolve_active_pack_id()`; used by `interactions.start`, `/health`, `create_interaction`, `simulator.simulate` | **Fixed** |
| Vite `/ui/` base | `dashboard/vite.config.js` `base: "/ui/"`; dist assets under `/ui/assets/` | **Fixed** |
| `FRONTLINE_ENABLED` gates HTTP + WS | `src/api/frontline_gate.py` + pure ASGI `FrontlineEnabledASGI` in `src/api/main.py`; WS handlers also check | **Fixed** |
| Console JSON-safe activity | `activity_frame_from_row` / `_json_safe` in `src/api/routes/interactions.py` | **Fixed** |
| Read auth when key set | Router `dependencies=[Depends(require_api_key)]` on interactions + frontline | **Fixed** (see **H-NEW-1**: dashboard pages that omit headers) |
| WS crash not left `active` | Broad `except` + `_mark_failed` in `interaction_ws` | **Fixed** |
| Exclusive customer WS + orphan TTL | `_attach_customer_ws`, `ActiveEntry.lock`, `reap_orphans` | **Fixed** |
| Simulator active pack | `src/frontline/simulator.py` uses `resolve_active_pack_id()` | **Fixed** |
| Alert retry + dead-letter | `ALERT_RETRY_ATTEMPTS`, `_post_webhook_with_meta`, `alert_dead_letter` table | **Fixed** |
| Dedup only on success | `_stamp_dedup` after successful send; fail leaves no stamp | **Fixed** (was M-NEW-1) |
| Safety → Critical/P1 | CaseAgent safety floor + kill-switch sets severity/priority | **Fixed** (was C-OPEN-1) |
| Dashboard API keys on Case/EW/Audits | `apiHeaders()` on CaseQueue, EarlyWarningBoard, AuditReports | **Fixed** (was H-NEW-1) |
| Simulate offload | `asyncio.to_thread(_simulate_in_thread, …)` on simulate route | **Fixed** (was H4) |
| Console turn/slots/frustration fan-out | `_WSHooks` + `_broadcast_console` | **Fixed** (was H6) |
| Max-turns wrap-up | `max_turns_reached` → `_move_to_closing` | **Fixed** (was M1) |
| Deep health + CORS env + report rotation | `/health` db_ok/pack_ok; `CORS_ALLOW_ORIGINS`; `report_rotation.py` | **Fixed** (was M4/M5/M8) |
| CSV export + SHA256 manifest | `build_audit_export_csv`, `format=csv` on export route | **Fixed** |
| Dockerfile file-backed install | `COPY requirements-docker.txt` + `pip install -r` | **Fixed** |

---

## 1. Agents / orchestrator

### Status: Core strong; safety-path severity still wrong; max-turns soft

| ID | Sev | Finding | Path / behavior |
|----|-----|---------|-----------------|
| **C-OPEN-1** | Critical | ~~Kill-switch → Low/P3~~ **CLOSED**: CaseAgent + kill-switch set Critical/P1. | `case_agent.py`, `orchestrator.py` |
| **H4** | High | ~~Simulate blocks event loop~~ **CLOSED**: `asyncio.to_thread` offload. | `frontline.py` |
| **M1** | Medium | ~~Max-turns silent~~ **CLOSED**: `max_turns_reached` → wrap-up/closing. | `intake.py`, `orchestrator.py` |
| **M2** | Medium | ~~Investigation race~~ **CLOSED**: process lock + re-check before open. | `case_agent.py` `_investigation_open_lock` |
| **M3** | Medium | ~~Case/ledger non-atomic~~ **CLOSED**: case row + `case_created` in one `BEGIN`/`COMMIT`. | `case_agent.py`, `record_action_on_con` |
| **L1** | Low | Orchestrator enrichment emits advisory **notice** after sentinel ledger (OK for notice content) but activity cards to hooks are best-effort. | `orchestrator.py` 345–386 |
| **Pass** | — | Dual-pack agents are pack-generic; state machine explicit; ledger-before-emit on escalation script, handoff, goodbye, human_turn. | `orchestrator.py` |

---

## 2. API (HTTP + WebSocket + auth)

### Status: Pilot single-tenant usable; several ops holes remain

| ID | Sev | Finding | Path / behavior |
|----|-----|---------|-----------------|
| **H5** | High | **API keys still travel in URL query strings** for REST fallback and all WebSocket auth. Dashboard builds `?api_key=` via `withApiKeyQuery`. Keys land in access logs, proxies, browser history. | `auth.py` 11, 69–71; `interactions.py` 352, 432; `dashboard/src/apiAuth.js` 27–34 |
| **H-NEW-2** | High | In-process registry is single-worker — **documented**: `/health` `single_worker: true` + README deploy constraint (HA still non-goal). | `main.py` health; README |
| **DD-P0 auth** | High | ~~Unset key always open~~ **HARDENED**: `FRONTLINE_AUTH_REQUIRED=1` fail-closed; WS first-message auth (query key deprecated). Not OIDC/SSO. | `auth.py`, dashboard `sendWsAuth` |
| **DD-P0 SSRF** | High | ~~Arbitrary connector URLs~~ **HARDENED**: `validate_outbound_url` blocks private/metadata; secrets not echoed. | `security/url_guard.py`, connectors |
| **DD-P1 enrich** | Medium | ~~Sequential enrichment~~ **HARDENED**: concurrent `asyncio.gather` for sentinel/triage/investigator. | `orchestrator.py` |
| **DD-P1 turns** | Medium | ~~Turns only at finalize~~ **HARDENED**: mid-contact `persist_turn`. | `data/turns.py` |
| **DD-P2 ledger** | Medium | ~~Unknown action_type allowed~~ **HARDENED**: `record_action` raises on unknown type. | `ledger/writer.py` |
| **H6** | High | ~~Console missing turn/slots/frustration~~ **CLOSED**: `_broadcast_console` from `_WSHooks`. Reconnect/ping still optional. | `interactions.py` |
| **M-NEW-2** | Medium | ~~Raw datetime on list~~ **CLOSED**: `json_safe_rows` / `json_safe` on interactions + cases lists. | `jsonutil.py` |
| **M4** | Medium | ~~CORS hard-coded~~ **CLOSED**: `CORS_ALLOW_ORIGINS` env (TLS reverse-proxy still non-goal). | `main.py` |
| **M5** | Medium | ~~Shallow health~~ **CLOSED**: `db_ok` + `pack_ok` on `/health`. | `main.py` |
| **M6** | Medium | **Rate limiting is process-local** (`slowapi` + in-memory). Multi-instance or restart resets limits; no Redis. | `src/api/limiter.py` |
| **L2** | Low | Pack list/detail GET remain open without API key (intentional for Settings discovery). | `packs.py` |
| **L3** | Low | ~~No dead-letter HTTP/UI~~ **CLOSED**: API + Settings dead-letter list/replay UI. | `frontline.py`, `Settings.jsx` |
| **Pass** | — | Write + read routes gated when `FRONTLINE_API_KEY` set; WS disabled when `FRONTLINE_ENABLED=0`; exclusive attach; crash finalization. | see §0 |

---

## 3. Dashboard

### Status: Demo UI complete; pilot-auth wiring incomplete on several pages **[NEW]**

| ID | Sev | Finding | Path / behavior |
|----|-----|---------|-----------------|
| **H-NEW-1** | High | ~~Missing API headers~~ **CLOSED**: CaseQueue / EarlyWarning / AuditReports use `apiHeaders()`. | dashboard routes |
| **H6** | High | Live Console fan-out **CLOSED** (see §2). Client reconnect still optional. | `LiveContactConsole.jsx` |
| **H5** | High | WS URLs append `api_key` query (see §2). | `apiAuth.js`, CallWidget, LiveConsole |
| **L4** | Low | ~~No reconnect~~ **CLOSED**: Live Console + Call Widget backoff reconnect + status. | CallWidget / LiveConsole |
| **Pass** | — | Settings stores pilot key; export JSON/CSV; pack switch UI; voice widget with STT/TTS. | |

---

## 4. Ops alerts

### Status: Retry + dead-letter shipped; dedup semantics still sharp

| ID | Sev | Finding | Path / behavior |
|----|-----|---------|-----------------|
| **M-NEW-1** | Medium | ~~Dedup before success~~ **CLOSED**: stamp only after successful webhook; fail → dead-letter without stamp. | `alerts.py` |
| **Pass** | — | 3 attempts + backoff; dead-letter table; failures never raise into call path; ledger `alert_sent`. | `alerts.py`, `schema.py` `alert_dead_letter` |

---

## 5. Audit export

### Status: JSON + CSV + manifest OK for pilot

| ID | Sev | Finding | Path / behavior |
|----|-----|---------|-----------------|
| **L5** | Low | Manifest for JSON hashes a canonical subset (`count` + `interactions`), not the full response including `exported_at` — intentional for stability; document so compliance does not hash the whole HTTP body. | `export.py` `build_audit_export` |
| **L6** | Low | CSV is one row per interaction (flattened); action-level detail stays in JSON only. | `export_to_csv` |
| **Pass** | — | Real export path; auth; CSV parseable; SHA256 matches body. | `export.py`, `frontline.py` export route |

---

## 6. Domain packs / loader / builder

### Status: Dual packs real; Builder CLI MVP shipped; fixtures tiny

| ID | Sev | Finding | Path / behavior |
|----|-----|---------|-----------------|
| **H7** | High (demo credibility) | **Domain data is fixture-scale (~10 records / pack).** `scripts/seed_domains.py` hardcodes ~10 NHTSA-shaped rows; finance similarly. Not NHTSA/CFPB volume. Fatal for domain-expert demos claiming “corpus RCA on real history.” | `scripts/seed_domains.py`; measured: 10 records, 2 advisories, 3 clusters each pack |
| **H8** | High (sales moat) | ~~Pack Builder not shipped~~ **CLOSED**: `src/domains/builder/pack_builder.py` ships `profile_csv` + `build_draft_pack` (CSV → draft pack CLI); `Makefile pack-init` is wired (`python -m src.domains.builder --src …`). Generated mapping still requires human review before lint — no builder UI. | `src/domains/builder/pack_builder.py`; `Makefile pack-init` |
| **Pass** | — | Loader + lint; active pack store; automotive + finance packs; template pack under `domains/_template`. | `src/domains/loader.py` |

---

## 7. Warehouses / schema

### Status: DuckDB fine for pilot; not multi-writer ops

| ID | Sev | Finding | Path / behavior |
|----|-----|---------|-----------------|
| **H9** | High (deploy) | **DuckDB ops warehouse is single-writer.** Concurrent API processes / multi-worker will lock or fail (`Conflicting lock`). | `warehouse.py` `ops_con` |
| **M7** | Medium | ~~List timestamps raw~~ **CLOSED** for list routes: `json_safe` → ISO UTC/Z on interactions + cases lists. Full DB TZ migrate still N/A. | `src/api/jsonutil.py` |
| **M8** | Medium | ~~No report rotation~~ **CLOSED**: `src/qubot/report_rotation.py` after each written contact audit. | `report_rotation.py`, `auditor.py` |
| **Pass** | — | Ops schema includes interactions, turns, cases, investigations, agent_actions, alert_dedup, alert_dead_letter. | `schema.py` |

---

## 8. Channels

### Status: Browser + simulated real; telephony stub only

| ID | Sev | Finding | Path / behavior |
|----|-----|---------|-----------------|
| **H10** | High (call-center buyers) | **No real PSTN.** `src/channels/twilio_stub.py` is design-note only. Browser STT/TTS only. | `twilio_stub.py`, `web_voice.py` |
| **Pass** | — | `ChannelAdapter` abstraction; SimulatedChannel for eval; WebVoiceChannel text-over-WS. | `channels/*` |

---

## 9. Qubot

### Status: Deterministic auditor real; ask-data is keyword router

| ID | Sev | Finding | Path / behavior |
|----|-----|---------|-----------------|
| **M9** | Medium | **Ask-data is keyword routing, not LLM.** Documented offline; do not oversell as free-form BI. | `qubot/cli.py` |
| **Pass** | — | Post-contact groundedness audit; playbooks; severity_sane will catch C-OPEN-1. | `auditor.py`, `retrievers.py` |

---

## 10. Config / Docker / CI / docs honesty

### Status: Much improved; residual honesty edges

| ID | Sev | Finding | Path / behavior |
|----|-----|---------|-----------------|
| **Pass** | — | LLM keys optional; `llm_available` reflects settings (`FRONTLINE_LLM_ENABLED` + provider key), False without keys; FRONTLINE_ENABLED real; Docker requirements file; CI workflow present. | `config.py`, `.env.example`, Dockerfile, `.github/workflows/frontline.yml` |
| **L7** | Low | ~~Forced embeddings dep~~ **CLOSED**: `sentence-transformers` commented out as optional until MiniLM is wired. | `requirements.txt` |
| **L8** | Low | Architecture doc still says “DB computes, LLM narrates” in places; config/README largely corrected to deterministic-only. Spot-check remaining marketing lines when selling. | `docs/frontline_architecture.md` |

---

## 11. Empty / stub packages (must not be sold as shipped)

| Package / surface | Path | Status |
|-------------------|------|--------|
| LLM provider | `src/ai/` | **Shipped** (provider + turn/daily spend caps; template fallback) |
| ML runtime | `src/ml_runtime/` | **Shipped** (bag-of-hash + clustering, no sklearn) |
| Backtest engine | `src/backtest/` | **Shipped** (`make backtest`) |
| Pack Builder | `src/domains/builder/` | **Shipped as MVP** (CSV→draft pack CLI; no UI) |
| Twilio adapter | `src/channels/twilio_stub.py` | **Stub / design note** |
| Full ingest | no `src/data/ingest.py` | **Not shipped** (seed scripts only) |
| Multi-tenant / SSO / Stripe / Postgres ops | — | **Not present** |
| CRM connectors | `src/frontline/connectors.py` | **Generic HTTP + dry-run outbox only** — not Salesforce/ServiceNow/Zendesk OAuth or two-way sync; SSRF URL guard on POST/config |
| Enterprise Ops | `src/enterprise/*` + `/api/frontline/enterprise/*` | **Shipped (deterministic):** timeline, root-cause, copilot intent router, risk scores, graph, entity memory, scenarios, decision flow. **Not** generative LLM copilot, real embeddings, full OTEL, or CRM graph DB |
| v3 Platform OS | `src/v3/*` | **Experiment/governance registry** — stamps + proposals; does **not** change runtime routing or activate live model policies |
| ML severity | triage agent | **Rules path only by default** — do not market as XGBoost |
| Enterprise certs | — | **Not SOC2 / HIPAA / GDPR / ISO ready**; single-tenant DuckDB pilot |

---

## 12. Investigator “ML” claim

| ID | Sev | Finding | Path / behavior |
|----|-----|---------|-----------------|
| **H11** | High (honesty) | **`similar_records` is SQL `ILIKE` + entity filters**, not MiniLM/FAISS. `sentence-transformers` in requirements is unused. Selling “embeddings RCA” would be false. | `investigator.py` `_SIMILAR_SQL` line 35; no import of transformers |

---

## 13. Residual / deferred industrial checklist (nothing silently omitted)

| Prior ID | Topic | Status in this audit |
|----------|--------|----------------------|
| H4 | Simulate blocks event loop | **Closed** (to_thread) |
| H5 | Query-string API keys | **Still open** (WS still uses `?api_key=`; non-goal full redesign) |
| H6 | Console turn/slot/frustration fan-out | **Closed** (reconnect still optional) |
| C-OPEN-1 | Safety path → Low/P3 case | **Closed** (Critical/P1) |
| H7 | Fixture-scale data | **Still open** (non-goal full ingest) |
| H8 | Pack Builder | **Still open** (non-goal) |
| H9 | DuckDB multi-writer / multi-worker | **Still open** (non-goal Postgres) |
| H10 | Real telephony | **Still open** (non-goal) |
| H11 | Embeddings similarity | **Still open** (non-goal) |
| M1 | Max-turns silence | **Closed** |
| M2 | Investigation race | **Closed** |
| M3 | Case+ledger non-atomic | **Closed** |
| M4 | CORS env | **Closed** (TLS compose still non-goal) |
| M5 | Deep health | **Closed** |
| M6 | Redis rate limit | **Still open** (non-goal) |
| M7 | TZ on list API reads | **Closed** (list JSON UTC); full DB migrate N/A |
| M8 | Report rotation | **Closed** |
| M9 | Ask-data not LLM | **Open as product limit** |
| H-NEW-1 | Dashboard API keys | **Closed** |
| M-NEW-1 | Alert dedup before success | **Closed** |
| L3 | Dead-letter HTTP admin | **Closed** |
| L7 | Unused sentence-transformers dep | **Closed** (commented optional) |
| Tier 2–4 | LLM, full ingest, Postgres, SSO, … | **Deferred** |
| Week-one C1–H3 + pilot alerts/CSV/Docker | | **Verified fixed** (§0) |

---

## 14. Net-new observations (not just re-paste of old essays)

1. **H-NEW-1** — Pilot secret breaks half the dashboard: Case Queue, Early Warning, and Audit list never send `X-API-Key` after read routes were locked down.
2. **M-NEW-1** — Alert dedup burns the daily slot even when webhook never succeeds (interacts badly with dead-letter / Slack outage).
3. **L7** — Dependency graph still advertises embeddings while runtime is ILIKE-only.
4. **Sentinel P1 lie is two-sided:** not only Triage skipped — Sentinel documents P1 without mutating context, so CaseAgent cannot “inherit” P1 without new code.
5. **Report directory size (~2.5k files)** measured live on this tree — not theoretical.
6. **Fixture counts re-measured:** 10/10 records per pack, 2 advisories, 3 clusters.

---

## 15. What is safe to demo / sell vs what blocks industrial grade

### Safe now (honest pitch)

- Dual-vertical **offline eval** + unit suite story (genericity).
- **Single-tenant pilot** on customer-supplied small/medium packs (hand-authored), Docker one-box, shared secret auth, JSON/CSV audit export with hash, Slack alerts with retry/dead-letter.
- Live contact loop on fixtures: intake → advisory match → case → audit trail → supervisor takeover (with known H6 limitations).
- **Ledger-first** narrative for the paths that do ledger before emit (escalation script, handoff, goodbye, human_turn).

### Do not claim yet

- “Semantic / embedding RCA,” “production call center telephony,” “multi-tenant SaaS,” “SOC2-ready,” “self-serve Pack Builder,” “NHTSA-scale corpus,” “multi-AZ HA.”
- “Any safety flag → P1 case” until C-OPEN-1 is fixed.
- “Full dashboard works with API key” until H-NEW-1 is fixed.
- Multi-worker or horizontal scale.

### Suggested fix order (for a later implementation pass — not this report)

1. **H-NEW-1** dashboard API headers (hours) — unblocks pilot UI under secret.  
2. **C-OPEN-1** set Critical/P1 on kill-switch path before CaseAgent (hours).  
3. **M-NEW-1** stamp dedup only after success (or re-arm on dead-letter) (hours).  
4. **H4 / H6 / H5** ops quality (days).  
5. Real-scale data + optional embeddings (weeks).  
6. Postgres + multi-worker + observability (enterprise track).

---

## 16. Suite context (analysis only)

As of this audit re-run: `python -m pytest tests/frontline -q --timeout=30` → **209 passed**, exit 0. A green suite supports “no known regression of pilot gates”; it does **not** prove residual items above are fixed.

---

*End of residual audit. Report-only; no product code was changed for findings.*
