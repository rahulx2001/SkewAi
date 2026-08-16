# Incident Response Plan

**Effective:** [YYYY-MM-DD] · **On-call:** [contact] · **Escalation:** [exec]

## 1. Severity
| Sev | Definition | Response target |
|-----|------------|-----------------|
| SEV1 | Confirmed breach / data loss / total outage | 15 min ack |
| SEV2 | Auth bypass, partial outage | 1 hour |
| SEV3 | Degraded, no data risk | Next business day |

## 2. Detection sources
- `data/security_audit.jsonl` / `SECURITY_AUDIT_LOG_PATH`  
- Host/cloud alerts, customer reports, anomaly in connector deliveries  

## 3. Response steps
1. **Detect & triage** — severity, systems, data classes  
2. **Contain** — revoke keys, disable `FRONTLINE_ENABLED=0` if needed, block IPs  
3. **Eradicate** — patch, rotate secrets, redeploy  
4. **Recover** — restore from backup if needed  
5. **Lessons learned** — within 5 business days; track actions  

## 4. Communications
- Internal: [#security-incidents]  
- Customers: only if personal/customer data affected or SLA impact; legal review  

## 5. Evidence
Preserve audit logs, access logs, and timeline in [ticket system]. Do not delete security_audit.jsonl during investigation.

## 6. Tabletop
Run at least **annual** tabletop; record date in GRC tool.
