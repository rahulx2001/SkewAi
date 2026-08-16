# Vendor Management

**Effective:** [YYYY-MM-DD] · **Owner:** [Ops]

## 1. Inventory (update quarterly)

| Vendor | Purpose | Data shared | SOC 2 / ISO | Review date |
|--------|---------|-------------|-------------|-------------|
| [Cloud host] | Compute / storage | Ops DB, logs | [Y/N + report] | |
| [LLM provider] | Optional narration | Prompt snippets | | |
| Twilio (if used) | Telephony | Call metadata/audio | | |
| GitHub | Source | Code | | |
| [Email/Slack] | Alerts | Event summaries | | |

## 2. Onboarding
- Business justification  
- Data flow diagram note  
- Security review (SOC report or questionnaire)  
- DPA if personal data  

## 3. Offboarding
- Revoke keys, remove integrations, confirm data deletion if contract requires  

## 4. Skew AI product note
Outbound webhooks use SSRF guards (`src/security/url_guard.py`). Customer-configured webhook URLs are treated as trusted by that customer only.
