# RBAC Permission Matrix (board: per-dashboard-role authz)

Source of truth: `PERMS` in `src/api/rbac.py`. This document mirrors it for
operators and dashboard builders. `test_rbac_matrix_consistent` fails the
build if a route demands a permission no role grants, or if this doc drifts
from `PERMS`.

Roles: `agent` (default browser caller) · `service` (API-key principal) ·
`supervisor` · `auditor` · `dsr_officer` · `admin`.

| Permission | agent | service | supervisor | auditor | dsr_officer | admin | Used by |
|---|---|---|---|---|---|---|---|
| `contact:write` | ✓ | ✓ | ✓ | – | – | ✓ | start/interact/ingest/handoff accept |
| `case:read` | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | cases, investigations, audits detail, comments |
| `case:write` | – | – | ✓ | – | – | ✓ | notes, investigation patch/comments/feedback |
| `takeover` | – | – | ✓ | – | – | ✓ | takeover/release/override |
| `audit:read` | – | ✓ | – | ✓ | – | ✓ | audit list/rerun |
| `ledger:read` | – | ✓ | – | ✓ | – | ✓ | explain |
| `dsr:export` | – | – | ✓ | ✓ | ✓ | ✓ | DSR export, PII opt-out reads |
| `dsr:delete` | – | – | – | – | – | ✓ | DSR tombstone/erase |
| `approval:decide` | – | – | ✓ | – | – | ✓ | approvals |
| `channel:ingest` | – | ✓ | ✓ | – | – | ✓ | channel ingest |
| `biometrics:match` | – | ✓ | ✓ | – | – | ✓ | biometrics |
| `session:mint` | – | – | – | – | – | ✓ | session mint |
| `admin:keys` | – | – | – | – | – | ✓ | scoped key minting |
| `pack:edit` | – | – | – | – | – | ✓ | OIDC config, pack edit |
| `pack:activate` | – | – | – | – | – | ✓ | pack activation |
| `marketplace:install` | – | – | – | – | – | ✓ | marketplace |
| `ops:drain` | – | – | – | – | – | ✓ | drain control |
| `ops:read` | – | ✓ | ✓ | ✓ | – | ✓ | hardening SLOs, retention, metrics |
| `ops:write` | – | – | – | – | – | ✓ | hardening fairness, cost updates |
| `jobs:run` | – | – | – | – | – | ✓ | job run-next |
| `routing:control` | – | – | ✓ | – | – | ✓ | traffic gate & circuit breaker control |

Notes:
- Bare `X-Frontline-Role` never elevates above `agent`; elevated roles need
  a signed session, and the shared API key resolves to `service` (not admin).
- Open (dev) mode: `open_mode_ok=True` routes skip checks; everything else
  still requires the key when configured.
- Multi-tenancy: single-tenant pilot — packs share one DB, separated by
  `pack_id` scoping, not by tenant isolation. True multi-tenancy is out of
  scope (see report).
- LLM backpressure: `FRONTLINE_LLM_TURN_CAP` (default 6/contact) + daily
  cost cap in `src/ai/provider.py`; narration degrades to templates on miss.
