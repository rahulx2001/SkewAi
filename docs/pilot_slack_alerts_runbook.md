# Pilot runbook — Slack (or any webhook) ops alerts

## Config

Set on the API process (`.env` or Compose):

```bash
ALERT_WEBHOOK_URL=https://hooks.slack.com/services/XXX/YYY/ZZZ
```

Any endpoint that accepts JSON `{"text": "..."}` works (Slack incoming webhooks,
webhook.site for dry runs, Discord-compatible proxies with adapters).

Leave empty to disable outbound HTTP (events are still ledgered).

## Event types (shipped)

Implemented in `src/frontline/alerts.py`:

| Event | When it fires |
|-------|----------------|
| `safety_escalation` | Safety lexicon / P1 path |
| `investigation_opened` | Nth case on a cluster opens an investigation |
| `early_warning_threshold` | Live-risk score crosses `EARLY_WARNING_ALERT_THRESHOLD` |
| `groundedness_mismatch` | Qubot auditor finds a bad citation |
| `takeover_started` | Supervisor takes over a live contact |

Dedup: at most one alert per `(event, cluster/interaction)` per window
(see `alert_dedup` table).

## Dry-run checklist (30 minutes)

1. Start API with a test webhook:
   ```bash
   # terminal A: capture requests
   # use https://webhook.site or `nc -l 9999` behind a tunnel
   export ALERT_WEBHOOK_URL=https://webhook.site/<your-uuid>
   uvicorn src.api.main:app --port 8000
   ```
2. Force a safety path with the Call Widget or text contact:
   - Auto pack: utterance with **fire** / **injury**
   - Finance pack: **identity theft** / **fraud**
3. Confirm webhook received a `{"text": ...}` body with the event summary.
4. Run multiple similar cases until `FRONTLINE_INVESTIGATION_MIN_CASES` (default 3)
   opens an investigation; confirm `investigation_opened` alert.
5. Optional: plant a bad evidence id in a ledger row and re-run
   `make audit ID=int_…` to see `groundedness_mismatch`.

## Ops notes

- Alert failures are logged and **must never** break the contact path.
- Retries: current implementation is fire-and-forget; for pilot, use a
  reliable webhook receiver (Slack) rather than a fragile laptop listener.
- Rate: safety + investigation alerts are the only ones that must be
  on-call for a pilot; early-warning can be daytime-only.

## Customer handoff

Give them:

1. The webhook URL they own  
2. This event table  
3. Escalation path (who gets paged on `safety_escalation`)  
