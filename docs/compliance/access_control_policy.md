# Access Control Policy

**Effective:** [YYYY-MM-DD] · **Owner:** [Security lead]

## 1. Identity
- Production access: unique user identity via **OIDC SSO** ([IdP]) preferred.  
- Pilot single-tenant: `FRONTLINE_API_KEY` is a **service credential** — treat as admin secret; do not share in chat/email.  
- MFA required for cloud consoles and IdP admin.

## 2. Provisioning
| Event | Action |
|-------|--------|
| Hire | Ticket → least-privilege role → document in access_review_log |
| Role change | Remove old groups before add |
| Termination | Same day: revoke IdP, cloud, API keys, GitHub |

## 3. Application roles (Skew AI)
| Role | Intended use |
|------|----------------|
| agent | Contact write, case read |
| supervisor | + case write, takeover |
| auditor | Read + DSR export |
| admin | Full (service key maps to admin in pilot) |

Bare `X-Frontline-Role` headers cannot elevate (enforced in code).

## 4. Reviews
Quarterly access review (see `access_review_log.md`). Evidence retained 1 year minimum.

## 5. Secrets
- Rotate `FRONTLINE_API_KEY` / `SESSION_SECRET` on compromise or staff exit.  
- Never store production keys in browser localStorage for multi-user production (pilot-only exception documented).
