# Compliance pack (SOC 2 Type I / II readiness)

This folder holds **policy and process templates** required for SOC 2 that
cannot be enforced by application code alone. Fill in `[BRACKETS]`, approve
with leadership, and store signed copies in your GRC tool (Vanta/Drata/etc.).

| Document | TSC theme | Owner |
|----------|-----------|--------|
| [information_security_policy.md](information_security_policy.md) | CC1–CC2 | Security lead |
| [access_control_policy.md](access_control_policy.md) | CC6 | Security lead |
| [incident_response_plan.md](incident_response_plan.md) | CC7 | On-call lead |
| [change_management.md](change_management.md) | CC8 | Eng lead |
| [vendor_management.md](vendor_management.md) | CC9 | Ops |
| [backup_and_dr.md](backup_and_dr.md) | A1 | Eng lead |
| [access_review_log.md](access_review_log.md) | CC6 | Security lead |
| [risk_assessment.md](risk_assessment.md) | CC3 | Founder / security |
| [subprocessors.md](subprocessors.md) | Privacy / C | Legal |

**Engineering baseline (code):** see `docs/soc2_engineering_readiness.md`.

**Truthful customer language:** “We maintain a hardened single-tenant security
baseline and are preparing for SOC 2 Type I/II with [auditor/GRC].” Do **not**
claim “SOC 2 Type II certified” until a CPA report is issued.
