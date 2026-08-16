# Pilot playbook — hand-onboard a customer pack (no Pack Builder)

> **Pack Builder is not shipped.** Do not run `make pack-init`. This guide is
> how we onboard pilot #1–#3 customers in ≤3 days using hand-authored YAML + a
> seed script (same pattern as `automotive_nhtsa` and `finance_cfpb`).

## Goal

Turn a customer CSV (historical tickets + optional advisories) into a Domain
Pack the existing agents can run **without Python changes to agent code**.

## Inputs you need from the customer

| Input | Why |
|-------|-----|
| Ticket/complaint CSV | Builds `records` corpus |
| Optional advisory/recall/enforcement CSV | Builds `advisories` |
| Entity fields (3) | Map to `entity_1/2/3` (e.g. year/make/model or product/company) |
| Category field | Maps to `category` slot + taxonomy |
| Free-text narrative column | Maps to `description` / `records.text` |
| Safety keywords | Pack `safety.escalation_lexicon` |
| Greeting language | Pack `greeting` / `goodbye` |

## Day-by-day (3 days)

### Day 1 — Map + scaffold

1. Copy the scaffold:
   ```bash
   cp -R domains/_template domains/<customer_pack_id>
   ```
2. Edit `pack.yaml`:
   - `id` = directory name
   - entity labels, slot prompts, safety lexicon, advisory SQL stubs
3. Fill `taxonomy.yaml` with their categories
4. Write `data/mapping.yaml` documenting CSV column → canonical fields
5. Draft gazetteer CSVs under `gazetteers/` from top-N values in the CSV

### Day 2 — Seed warehouse

1. Copy `scripts/seed_finance_cfpb.py` → `scripts/seed_<customer_pack_id>.py`
2. Load 50–500 rows (pilot sample; not full dump) into:
   - `records`, `advisories`, `clusters`, `cluster_assignments`,
     `weekly_anomalies`, `backtest_results`
3. Register the seeder in the pack-aware seed path used by eval if needed
4. Lint:
   ```bash
   make pack-lint PACK=<customer_pack_id>
   ```

### Day 3 — Smoke + demo script

```bash
DOMAIN_PACK=<customer_pack_id> make contact
DOMAIN_PACK=<customer_pack_id> make simulate N=10
```

Adapt `docs/demo_script.md` beats to their greeting + one known advisory hit.

## Success criteria for pack readiness

- [ ] `make pack-lint PACK=…` clean  
- [ ] Text contact fills required slots  
- [ ] At least one advisory SQL hit on a planted entity  
- [ ] Simulate creates cases  
- [ ] Customer signed off on safety lexicon wording  

## Out of scope for hand onboarding

- Full multi-million-row CFPB/NHTSA ingest  
- Automated Pack Builder (`make pack-init` fails until implemented)  
- Multi-tenant isolation  
