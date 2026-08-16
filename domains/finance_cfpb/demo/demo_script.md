# Finance pack demo script

A 3-turn scripted contact that exercises the full flow on the finance_cfpb pack.

## Setup
```bash
make frontline-db
```

## Run
```bash
DOMAIN_PACK=finance_cfpb python -m src.frontline.cli contact --script "My checking account at Chase was charged twice for a transfer.|No money was taken without permission.|Yes I contacted their fraud department."
```

## Expected turns
1. **Agent (greeting):** "Thanks for calling. What issue are you having with your account?"
2. **Customer:** "My checking account at Chase was charged twice for a transfer."
3. **Agent (safety q):** "Has money been taken from your account without your permission?"
4. **Customer:** "No money was taken without permission."
5. **Agent (safety q):** "Have you contacted your bank's fraud department?"
6. **Customer:** "Yes I contacted their fraud department."
7. **Agent (advisory notice):** "There's a matching known issue. Advisory Id: CFPB-2023-01 | ..."
8. **Agent (goodbye):** "Thanks for reaching out. Your case number is case_XXX..."

## Expected outcomes
- state: DONE
- case_id: case_XXX
- severity: Medium (P2)
- advisory_match: True (CFPB-2023-01)
- investigation: opened (if 3+ cases on cluster #41)
