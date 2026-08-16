# Change Management

**Effective:** [YYYY-MM-DD] · **Owner:** [Eng lead]

## 1. Scope
Code, infrastructure, production config, domain packs that affect production pilots.

## 2. Standard change path
1. Branch + PR with description and risk notes  
2. CI green (`make ci` / GitHub Actions)  
3. At least one reviewer approval for production paths  
4. Deploy via [pipeline / documented steps]  
5. Post-deploy smoke: `/health`, auth 401 without key, UI load  

## 3. Emergency change
- Document after-the-fact within 24h  
- Same security tests required before close  

## 4. Prohibited
- Force-push to main without policy exception  
- Production secrets in git  
- Disabling auth in production (`FRONTLINE_OPEN_MODE=1` with `ENV=production`)  

## 5. Evidence for SOC 2
PR links, CI runs, deploy tickets retained per retention schedule.
