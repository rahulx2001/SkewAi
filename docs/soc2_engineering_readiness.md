# SOC 2 readiness — engineering baseline vs Type II attestation

**Product:** Skew AI (`v2_ai_rca_tool`)  
**Updated:** 2026-07-31  

## Important distinction

| Term | Meaning |
|------|---------|
| **SOC 2 Type I** | CPA report: controls *designed* and implemented at a point in time |
| **SOC 2 Type II** | CPA report: controls *operated effectively* for 3–12 months |
| **This repo** | Engineering + **policy templates** that *support* Security criteria |

**Code + templates alone cannot produce a SOC 2 Type II report.** You still need
approved policies, vendor reviews, access reviews, training evidence, backup
drills, an observation period, and an independent auditor.

---

## 1. Engineering baseline (implemented in product)

| Control | Implementation |
|---------|----------------|
| Fail-closed production | `src/security/harden.py` + Docker entrypoint |
| Auth on ops APIs | `require_api_key` on frontline, enterprise, platform, **packs** |
| Always-auth DSR | `require_api_key_strict` |
| Session hardening | No free admin; no `dev-only` when auth required |
| Path jail | Marketplace `source_path` under allow-root |
| Security audit log | `src/security/audit_log.py` → JSONL |
| Security headers | CSP, frame deny, nosniff; **HSTS only when production-like** |
| Rate limits | Default + sensitive routes |
| SSRF guard | Webhooks |
| Constant-time key compare | `secrets.compare_digest` |
| Hardened Compose profile | `docker compose --profile hardened up` |
| `make run-hardened` | Local fail-closed bind to 127.0.0.1 |
| Compliance templates | `docs/compliance/*` (CC1–CC9 process starters) |

### Hardened env

```bash
export ENV=production   # or PILOT_HARDENED=1 or SOC2_MODE=1
export FRONTLINE_AUTH_REQUIRED=1
export FRONTLINE_API_KEY="$(openssl rand -hex 32)"
export SESSION_SECRET="$(openssl rand -hex 32)"
export FRONTLINE_OPEN_MODE=0
make run-hardened
# or: docker compose --profile hardened up --build
```

---

## 2. Trust Services Criteria — status

### Security (required)

| Criterion | Engineering | Process templates | Still for auditor Type II |
|-----------|-------------|-------------------|---------------------------|
| CC1 Control environment | Docs | `information_security_policy.md` | Board approval, training records |
| CC2 Communication | Partial | same + IR plan | Customer security page live |
| CC3 Risk assessment | Template | `risk_assessment.md` | Annual workshop evidence |
| CC4 Monitoring | Audit JSONL | IR + SIEM ship | Alerts + management review |
| CC5 Control activities | CI/tests | `change_management.md` | Ticket evidence trail |
| CC6 Logical access | API key + RBAC clamps | `access_control_policy.md` | **SSO+MFA**, quarterly reviews filled |
| CC7 Operations | Drain, logs | `incident_response_plan.md` | Tabletop evidence |
| CC8 Change | Git/CI | `change_management.md` | Required approvals history |
| CC9 Risk mitigation | SSRF, harden | `vendor_management.md` | Vendor SOC reports collected |

### Availability

| Engineering | Still needed |
|-------------|--------------|
| Single worker, DuckDB, prune | HA Postgres, multi-AZ, tested backups (template in `backup_and_dr.md`) |

### Confidentiality / Privacy

| Engineering | Still needed |
|-------------|--------------|
| DSR API, PII helpers, audit log | Signed DPAs, subprocessor list filled (`subprocessors.md`), encryption at rest (managed DB) |

---

## 3. Organizational checklist (you must operate this)

- [ ] Approve policies under `docs/compliance/` (replace `[BRACKETS]`)  
- [ ] Enroll GRC tool (Vanta/Drata/Secureframe) **or** manual evidence folder  
- [ ] IdP SSO + MFA for humans  
- [ ] Ship `security_audit.jsonl` to SIEM  
- [ ] Quarterly access reviews (log file)  
- [ ] Annual pen test  
- [ ] Vendor SOC reports on file  
- [ ] CPA engagement → Type I → Type II window (3–12 months)  

---

## 4. Honesty statement

> Skew AI ships a **single-tenant hardened security baseline** and **SOC 2 process templates**.  
> **SOC 2 Type II certified** only after an independent CPA report covering an observation period.  
> Engineering readiness ≠ certified attestation.

---

## 5. Related paths

| Path | Role |
|------|------|
| `docs/compliance/` | Policy / IR / vendor / backup templates |
| `docs/security_review_2026-07-31.md` | Vuln findings |
| `tests/frontline/test_soc2_baseline.py` | Automated engineering gates |
| `make security-test` / `make run-hardened` | Local verification |
