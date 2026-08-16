# Information Security Policy

**Organization:** [LEGAL NAME]  
**Product:** Skew AI  
**Effective date:** [YYYY-MM-DD]  
**Owner:** [Name / title]  
**Review cadence:** Annual or after material change  

## 1. Purpose
Protect confidentiality, integrity, and availability of customer and company data processed by Skew AI and supporting systems.

## 2. Scope
All employees, contractors, systems, and third parties handling Skew AI data (ops warehouses, transcripts, cases, connectors, cloud accounts).

## 3. Roles
| Role | Responsibility |
|------|----------------|
| Executive sponsor | Budget, risk acceptance |
| Security lead | Policy, access, incidents |
| Engineering lead | Secure SDLC, production config |
| All staff | Acceptable use, reporting incidents |

## 4. Principles
- Least privilege and need-to-know  
- Defense in depth  
- Fail closed for production (`PILOT_HARDENED` / `ENV=production`)  
- Log security-relevant actions  

## 5. Acceptable use
No sharing of production API keys or customer data outside approved tools. Personal devices require disk encryption and screen lock.

## 6. Data classification
| Class | Examples | Handling |
|-------|----------|----------|
| Public | Marketing site | No special controls |
| Internal | Architecture docs | SSO required |
| Confidential | Customer cases, transcripts | Encryption in transit; access logged |
| Restricted | API keys, SESSION_SECRET | Secrets manager / env only; never commit |

## 7. Exceptions
Documented risk acceptance by executive sponsor, time-bounded.

## 8. Enforcement
Violations may result in access removal and employment consequences per local law.

## Approval
| Name | Role | Date | Signature |
|------|------|------|-----------|
| | | | |
