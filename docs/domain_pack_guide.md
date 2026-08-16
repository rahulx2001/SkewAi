# Domain Pack Guide — how to add a vertical

> A pack is **domain-as-data, not domain-as-code**. The agents are generic
> engines; everything domain-specific lives in declarative YAML + CSVs.

This guide walks through creating a new Domain Pack for any industry. For the
architecture overview see [Frontline Architecture](frontline_architecture.md).

## 1. What a pack is

A pack is a directory `domains/<pack_id>/` that tells the generic agents:

- **What to ask** (slot frame + prompts)
- **What's an entity** (gazetteers + validation)
- **What's safety-critical** (escalation lexicon + script)
- **What's a known issue** (advisory SQL)
- **How to triage** (severity rules OR ML artifact + priority matrix)
- **What categories exist** (taxonomy)

Adding a vertical means writing YAML + CSVs, not Python (plus a small
fixture/seed script if you need domain warehouse data). A Pack Builder
(`make pack-init`) is **planned but not shipped** — `src/domains/builder/`
is empty today; do not run `make pack-init` expecting a working pipeline.

## 2. Directory layout

```
domains/<pack_id>/
├── pack.yaml              # the manifest (schema-validated) — REQUIRED
├── taxonomy.yaml          # category tree — REQUIRED (referenced from pack.yaml)
├── gazetteers/            # frequency-ranked entity value lists
│   ├── <name>.csv         # one value per row, most-frequent first
│   └── ...
├── context/               # Qubot context pack additions (optional)
├── playbooks/             # domain-specific Qubot playbooks (optional)
├── data/                  # mapping.yaml + cached source files (optional)
├── demo/                  # demo script + eval personas (optional)
└── models/                # trained artifacts (optional)
```

## 3. The `pack.yaml` schema

### 3.1 Top-level fields

```yaml
id: automotive_nhtsa                  # must match directory name; no path separators
display_name: Automotive (NHTSA)
greeting: "Thanks for calling support. What's going on with your vehicle?"
goodbye: "Thanks for reaching out. Your case number is {case_id}. ..."
refusal_topics:                        # agent politely refuses these
  - legal advice
  - dealer pricing
```

### 3.2 Entities

Labels for the three canonical entity slots. The slot keys (`entity_1/2/3`) are
fixed; the labels are pack-defined.

```yaml
entities:
  entity_1: "Year"           # automotive
  entity_2: "Make"
  entity_3: "Model"
```

```yaml
entities:                     # finance_cfpb
  entity_1: "Product"
  entity_2: "Sub-product"
  entity_3: "Company"
```

### 3.3 Slot frame

Ordered list of slots the Intake Agent fills. One question per turn for the
highest-priority missing required slot.

```yaml
slot_frame:
  - name: entity_1
    label: "Vehicle year"
    prompt: "What's the model year of your vehicle?"
    required: true
    max_re_asks: 2
    validation: year-range
    year_range: [1990, 2026]
  - name: entity_2
    label: "Make"
    prompt: "What's the make? For example, Honda, Ford, Toyota."
    required: true
    max_re_asks: 2
    validation: gazetteer
    gazetteer: makes                    # → gazetteers/makes.csv
  - name: entity_3
    label: "Model"
    prompt: "And the model? For example, CR-V, F-150, Corolla."
    required: true
    max_re_asks: 2
    validation: gazetteer
    gazetteer: models
  - name: category
    label: "System"
    prompt: "Which system is affected? For example, brakes, engine, ..."
    required: true
    max_re_asks: 2
    validation: gazetteer
    gazetteer: categories
  - name: description
    label: "Symptom description"
    prompt: "In your own words, what's happening with the vehicle?"
    required: true
    max_re_asks: 1
    validation: free-text
```

Validation strategies:
- `gazetteer` — value must appear in `gazetteers/<name>.csv`. The Intake Agent
  does whole-word substring matching so "I have a Honda" matches "HONDA".
- `regex` — value must match a Python regex.
- `year-range` — value must be a 4-digit year in `[min, max]`.
- `free-text` — any non-empty text is accepted (used for the description slot).

### 3.4 Safety

```yaml
safety:
  escalation_lexicon:                  # whole-word match; triggers immediate escalation
    - fire
    - smoke
    - crash
    - injury
    - airbag deployed
    - loss of control
    - vehicle stopped in traffic
    - unable to brake
    - seatbelt failed
  safety_questions:                   # asked once each, before regular slots
    - "Is anyone hurt?"
    - "Are you in a safe location right now?"
  escalation_script: |                  # read verbatim on escalation (no LLM)
    I want to flag this immediately for a safety specialist. Please do not
    drive the vehicle until a specialist has reviewed your case. They will
    reach out within the hour. If at any point you feel unsafe, please call
    emergency services.
```

When a customer utterance matches any lexicon term (word-boundary match), the
Intake Agent:
1. Sets `safety_flags[<term>] = True` + `safety_flags['escalation'] = True`
2. Skips remaining slots
3. Reads the static escalation script
4. The Sentinel Agent fires its escalation trigger
5. The orchestrator fires a `safety_escalation` ops alert (P1)

### 3.5 Advisory match

Parameterized SQL over the `advisories` table. Read-only. Returns matching
recalls / TSBs / enforcement actions.

```yaml
advisory_match:
  sql_template: |
    SELECT advisory_id, issued_at,
           scope_entity_2 || ' ' || scope_entity_3 || ' ' || scope_category AS scope_summary,
           summary, remedy, url, source
    FROM advisories
    WHERE (scope_entity_1 = $entity_1 OR scope_entity_1 IS NULL)
      AND (scope_entity_2 = $entity_2 OR scope_entity_2 IS NULL)
      AND (scope_entity_3 = $entity_3 OR scope_entity_3 IS NULL)
      AND (scope_category = $category OR scope_category IS NULL)
    ORDER BY issued_at DESC
    LIMIT 5
  readback_fields: [advisory_id, scope_summary, remedy, url]
```

The SQL uses **named parameters** (`$entity_1`, `$entity_2`, `$entity_3`,
`$category`) bound by DuckDB. The loader lints it to reject write statements
(INSERT/UPDATE/DELETE/DROP/ALTER/CREATE/TRUNCATE/MERGE).

`readback_fields` are the columns read back to the customer verbatim — no LLM.
The Sentinel Agent takes the top match and builds a notice:
"There's a matching known issue. Advisory Id: 19V-12345 | Scope Summary: ... |
Remedy: ... | Url: ...".

### 3.6 Severity

Two paths: ML artifact OR ordered rule list. The pack chooses which.

```yaml
severity:
  # Option A: ML runtime artifact (the automotive pack uses v1's XGBoost model)
  model_artifact: automotive_nhtsa/severity_xgb
  # Option B: ordered rules (evaluated top-down; first match wins)
  rules:
    - when: safety.any                  # any safety flag set
      severity: Critical
      reason: "Safety flag present — escalated to Critical"
    - when: description_matches_fire|smoke|crash|injury
      severity: Critical
      reason: "Severity-critical language in description"
    - when: category in [SERVICE BRAKES, AIR BAGS, FUEL SYSTEM, STEERING]
      severity: Medium
      reason: "Safety-critical system"
    - when: default
      severity: Low
      reason: "Default severity"
  priority_matrix:
    safety: 1
    Critical: 1
    Medium: 2
    Low: 3
```

Condition syntax (in `when`):
- `default` / `always` / `true` / `else` — always true (catch-all)
- `safety.any` — any safety flag set
- `safety.<key>` — specific safety flag (e.g. `safety.fire`)
- `category in [A, B, C]` — category match
- `description_matches_fire|smoke|crash` — word-boundary match on description

**Hardcoded invariant:** any safety flag → P1 always (the matrix value for
`safety` is 1 by default, but `_priority_from_matrix` enforces the floor too).

### 3.7 Taxonomy

The `taxonomy.yaml` is a category tree used by the `category` slot and the
Investigator. Simple structure:

```yaml
groups:
  - name: Brakes & Steering
    categories: [SERVICE BRAKES, STEERING, SUSPENSION, PARKING BRAKE]
  - name: Powertrain
    categories: [ENGINE, POWER TRAIN, FUEL SYSTEM, HYBRID PROPULSION SYSTEM]
  # ...
```

## 4. The gazetteers CSV format

Each gazetteer is a plain CSV with a header row, then one value per row
(most-frequent first):

```csv
value
HONDA
TOYOTA
FORD
CHEVROLET
NISSAN
```

The loader lowercases for lookup but preserves the canonical form for display
(so "honda" / "HONDA" / "Honda" all resolve to "HONDA").

## 5. Step-by-step: add a new vertical

1. **Copy the template**:
   ```bash
   cp -r domains/_template domains/<your_pack_id>
   ```

2. **Edit `pack.yaml`** — fill in id, display_name, greeting, entities,
   slot_frame, safety, advisory_match, severity.

3. **Add gazetteers** — create `gazetteers/<name>.csv` for each entity slot
   that uses `validation: gazetteer`. Frequency-ranked.

4. **Edit `taxonomy.yaml`** — define your category tree.

5. **Lint the pack**:
   ```bash
   make pack-lint PACK=<your_pack_id>
   ```
   This validates the manifest schema, resolves gazetteers, and checks
   referential integrity. Fix any errors.

6. **Build the domain warehouse** — write a small seed script under `scripts/`
   (see `scripts/seed_domains.py` and `scripts/seed_finance_cfpb.py` as
   templates). Both shipped packs use this pattern today.

7. **Test in text mode**:
   ```bash
   DOMAIN_PACK=<your_pack_id> make contact
   ```

8. **Run the eval harness** (if you added personas):
   ```bash
   # Offline CI gates only the real verticals (automotive_nhtsa, finance_cfpb).
   make eval-frontline
   ```

## 6. The Pack Builder — **not shipped**

> **Status:** `src/domains/builder/` is empty. `make pack-init` **fails**
> (no `src.domains.builder` module). Do not treat this section as runnable.

A future Pack Builder is intended to turn a historical complaints CSV into a
draft pack (profile → human-confirmed `mapping.yaml` → gazetteers → domain
DuckDB → stub `pack.yaml`). Until that code exists:

- Create packs **by hand** (YAML + CSVs) as in sections 3–5.
- Seed fixtures with a Python script under `scripts/`.
- The shipped **`finance_cfpb` pack was hand-authored**, not produced by a
  builder pipeline.

When the builder lands, this section will document the real CLI and the
dogfood path. Until then, ignore any older references to
`make pack-init SRC=history.csv` as a working command.

## 7. What's optional vs required

| Field | Required? | Notes |
|---|---|---|
| `id`, `display_name`, `greeting`, `goodbye` | Required | |
| `entities` (entity_1/2/3 labels) | Required | |
| `slot_frame` (with a `description` slot) | Required | Must include `description` (free-text). |
| `safety.escalation_lexicon` | Required | Can be empty list, but the field must exist. |
| `safety.escalation_script` | Required | Read verbatim on safety escalation. |
| `advisory_match.sql_template` | Required | Parameterized + read-only (linted). |
| `severity.model_artifact` OR `severity.rules` | One required | At least one severity path must be configured. |
| `taxonomy_ref` | Optional (defaults to `taxonomy.yaml`) | |
| `domain_db` | Optional (defaults to `data/domains/<pack_id>.duckdb`) | |
| `context/`, `playbooks/`, `data/`, `demo/`, `models/` | Optional | |

## 8. See also

- [Frontline Architecture](frontline_architecture.md) — full architecture reference
- [Demo Script](demo_script.md) — the 12-beat demo, both verticals
