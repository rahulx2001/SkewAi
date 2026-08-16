# Backup and Disaster Recovery

**Effective:** [YYYY-MM-DD] · **Owner:** [Eng lead]  
**RTO target:** [e.g. 24h] · **RPO target:** [e.g. 24h]

## 1. Data stores (current architecture)
| Store | Path / system | Backup method |
|-------|---------------|---------------|
| Ops warehouse | DuckDB under `data/` | Volume snapshot / copy |
| Domain warehouses | `data/domains/*.duckdb` | Volume snapshot / copy |
| Security audit log | `SECURITY_AUDIT_LOG_PATH` | Ship to remote log + retain |
| Reports | `reports/` | Volume / object storage |

## 2. Backup schedule
- [ ] Daily automated snapshot of data volumes (production)  
- [ ] Weekly restore test to staging (document result)  

## 3. Restore procedure (pilot)
These steps are the restore path. Run them in order on the replacement host.

1. Stop the API process (`kill $(cat data/uvicorn-local.pid)` or stop the compose service).
2. Copy the snapshot back over `data/` (ops + domain DuckDB files) and `reports/`.
3. Restore `data/locker_keys/` if the Evidence Locker must verify historical bundles.
4. Start with the same hardened env (`FRONTLINE_AUTH_REQUIRED=1`, real `FRONTLINE_API_KEY`).
5. Prove the restore: `GET /health` returns ok; `GET /api/frontline/cases` lists prior cases; `python -m src.ledger` / locker verify on a saved bundle succeeds; `GET /api/frontline/provenance/kpis` returns figures.
6. Record the restore clock (RTO) and the newest recovered `agent_actions.ts` (RPO).

## 4. DR notes for SOC 2 Availability
Single-process DuckDB is **not multi-AZ HA**. For enterprise Availability criteria, plan Postgres + managed backups. Document current single-tenant RTO honestly with customers.
