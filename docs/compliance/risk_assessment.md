# Risk Assessment (template)

**Date:** [YYYY-MM-DD] · **Facilitator:** [Name]

## Top risks (example — replace with workshop output)

| Risk | Likelihood | Impact | Mitigation | Residual |
|------|------------|--------|------------|----------|
| Unauthenticated API if open mode exposed | M | H | Hardened env, entrypoint fail-closed | L |
| Shared API key compromise | M | H | Key rotation, SSO roadmap, audit log | M |
| XSS steals browser key | L | H | CSP, no localStorage long-term, OIDC | M |
| Vendor LLM data leak | M | M | Disable LLM or DPA + no PII in prompts | M |
| Single-node data loss | M | H | Backups + restore tests | M |
| Supply-chain pack install | L | H | Path jail, disable source_path in prod | L |

## Next review
[YYYY-MM-DD]
