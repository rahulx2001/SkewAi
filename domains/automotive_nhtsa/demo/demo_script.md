# Automotive pack demo script

A 3-turn scripted contact that exercises the full flow on the automotive pack.

## Setup
```bash
make frontline-db
```

## Run
```bash
make contact
```

## Expected turns
1. **Agent (greeting):** "Thanks for calling support. What's going on with your vehicle?"
2. **Customer:** "My 2019 Honda CR-V grinds when I brake."
3. **Agent (safety q):** "Is anyone hurt?"
4. **Customer:** "It started about a week ago."
5. **Agent (safety q):** "Are you in a safe location right now?"
6. **Customer:** "Yes it happens at low speeds too."
7. **Agent (advisory notice):** "There's a matching known issue. Advisory Id: 19V-12345 | ..."
8. **Agent (goodbye):** "Thanks for reaching out. Your case number is case_XXX..."

## Expected outcomes
- state: DONE
- case_id: case_XXX
- severity: Medium (P2)
- advisory_match: True
- investigation: opened (if 3+ cases on cluster #14)
