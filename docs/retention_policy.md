# Retention & Residency (10/10 compliance §7)

Per data class (env-overridable, pack-overridable):

| class | default | override env |
|---|---|---|
| turns | 90d | RETENTION_TURNS_DAYS / RETENTION_<PACK>_TURNS_DAYS |
| cases | 2555d (7y) | RETENTION_CASES_DAYS |
| audit (ledger) | 2555d, tombstone-only | never early-delete |
| voice_audio | 30d (biometric-shortest) | RETENTION_VOICE_AUDIO_DAYS |
| metrics/alerts | 400d / 180d | RETENTION_METRICS_DAYS |

- Residency: `MERKLE_ANCHOR_RESIDENCY` (default `us-tenant-local`).
- Sub-processors: LLM vendor (optional narration, de-identified text only); carrier/Twilio (when configured, audio+metadata).
- DSR: hash-keyed erasure plan in `src/compliance/retention.py:erase_customer` + `src/frontline/dsr.py`; ledger rows tombstoned, chain intact.
- See `GET /api/frontline/hardening/retention`.
