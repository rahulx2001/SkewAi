# Frontline v3 — Enterprise AI OS foundation

Date: 2026-07-22

This release adds a **finishable OS foundation** on top of the deterministic
pilot core: continuous learning, experiments, and governance. It does **not**
claim multi-provider LLM routing, multi-tenant SaaS, OTEL mesh, or drag-drop
workflow studios (those remain roadmap).

## Architecture (what landed)

```
Contact finalize
    → version stamp (pack + active deployment + model_policy=deterministic)
    → optional learning proposal (if failure-like via root-cause)

Operators
    → scan failures → proposals → approve/reject/deploy
    → register artifacts → A/B experiment → trial metrics → compare report
    → create deployment → activate / rollback (soft history)
```

Reuses (does not rewrite): `enterprise.root_cause`, ledger, pack_version,
Enterprise Ops explorers, Qubot auditor, dual-pack eval.

## Schema (ops DuckDB)

| Table | Role |
|-------|------|
| `learning_proposals` | Improvement proposals + review lifecycle |
| `ai_artifacts` | Versioned prompt/workflow/routing/safety/retrieval configs |
| `experiments` | Control vs candidate experiment headers |
| `experiment_trials` | Per-arm outcome metrics |
| `config_deployments` | Soft-activate deployment history |
| `interaction_version_stamps` | Per-contact version trail |

## APIs (`/api/v3/*`, auth when key set)

| Path | Purpose |
|------|---------|
| `POST /learning/run` | Batch-generate proposals from failures |
| `GET /learning/proposals` | List proposals |
| `POST /learning/proposals/{id}/review` | approve \| reject \| deployed |
| `GET /learning/trends` | Status / weakness aggregates |
| `POST /artifacts` | Register versioned artifact |
| `POST /experiments` | Create experiment |
| `POST /experiments/{id}/trials` | Record trial metrics |
| `POST /experiments/{id}/complete` | Comparison report |
| `POST /governance/deployments` | Create deployment |
| `POST /governance/deployments/{id}/activate` | Soft-activate |
| `POST /governance/rollback` | Rollback to prior |
| `GET/POST /governance/stamps/{interaction_id}` | Version stamp |

## UI

Dashboard **Platform OS** (`#/platform`): Learning · Experiments · Governance.

## Honesty / non-goals

| Claimed elsewhere | Reality here |
|-------------------|--------------|
| Multi-model GPT/Claude/Gemini router | **Not shipped** — `model_policy=deterministic` |
| Drag-drop workflow studio | **Not shipped** |
| Multi-tenant orgs/RBAC | **Not shipped** |
| OpenTelemetry production mesh | **Not shipped** |
| Postgres/Kafka HA | **Not shipped** |
| Pack Builder / embeddings | Pack Builder ships as CLI MVP; embeddings are bag-of-hash + ILIKE fallback (no MiniLM) |
| Generative executive copilot | Use supervisor copilot (SQL intents) + learning trends |

## Future roadmap (phases 4–17 sketch)

1. Real model router + cost telemetry  
2. Visual workflow studio  
3. Multi-tenant tenancy  
4. OTEL + horizontal workers  
5. Marketplace for packs/prompts  

## Migration

No breaking changes to existing `/api/frontline/*` or Enterprise Ops.
New tables appear on next ops DB schema apply (`init_ops_db` / first write).
