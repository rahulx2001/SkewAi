# Pilot statement of work template — Skew AI (skewai)

> **Not legal advice.** Replace bracketed fields. Single-tenant pilot only —
> not multi-tenant SaaS, not real PSTN telephony, not SOC2 certification.

## Parties

- **Provider:** [Your entity]  
- **Customer:** [Company name]  
- **Sponsor (budget owner):** [Name, title]  
- **Technical contact:** [Name, email]

## Offer

**Name:** Skew AI Pilot — First Deploy  
**Duration:** [4] weeks from kickoff  
**Environment:** Single-tenant deploy (Docker Compose or Customer VPC)  
**Scope:** One Domain Pack for [auto / finance / other], fixture-or-sample data
scale agreed below.

## Promise

Within the pilot window, Provider will deploy Skew AI so that support contacts
are structured into the Customer’s historical schema, matched against known
advisories when SQL rules hit, clustered for early warning, ledgered for audit,
and exportable for compliance review — without rewriting agent code for the
industry.

## Deliverables

| Week | Deliverable |
|------|-------------|
| 1 | Deploy + ingest **sample** tickets/advisories into a hand-authored pack |
| 2 | Text + browser-voice demo on Customer entities/slots/safety lexicon |
| 3 | Live console + supervisor takeover + Slack (or webhook) alerts wired |
| 4 | Audit JSON export of N pilot contacts + written pilot report |

## Success metrics (examples — pick 3–5)

- [ ] ≥ [90]% of pilot contacts produce a case row with filled entity slots  
- [ ] ≥ [1] planted advisory match demonstrated live  
- [ ] Investigation auto-open demonstrated on repeated cluster cases  
- [ ] 100% of completed contacts have ledger rows before agent outputs  
- [ ] Audit export contains interaction ids + action summaries + groundedness verdicts  
- [ ] Supervisor takeover completed once without API errors  

## Data handling

- Customer provides a **sample** CSV (PII minimized). Provider does not sell data.  
- Data resides in Customer-controlled volume or VPC unless otherwise agreed.  
- Retention: pilot data deleted or returned within [30] days of pilot end unless
  converted to a paid subscription.  
- No multi-tenant mixing of Customer data with other parties.

## Non-goals (explicit)

- Multi-tenant SaaS / SSO  
- Real carrier telephony (browser STT/TTS or text only)  
- Full historical multi-million-row ingest (sample scale only unless scoped)  
- Pack Builder automation (hand pack for this pilot)  
- Production 24/7 SLA (best-effort uptime during pilot business hours)

## Security baseline

- Optional shared secret: `FRONTLINE_API_KEY` on write/console routes  
- Input validation on customer/supervisor turns  
- Rate limits on start/simulate  
- No LLM keys in logs  

## Fees (indicative placeholders)

| Item | Amount |
|------|--------|
| Pilot fee | $[25,000–75,000] |
| Payment schedule | [50% kickoff / 50% week 4] |
| Optional workshop | $[3,000–8,000] |

## Sign-off

| Role | Name | Signature | Date |
|------|------|-----------|------|
| Customer sponsor | | | |
| Provider | | | |
