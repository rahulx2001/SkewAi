#!/usr/bin/env node
/**
 * assert-auth-centralization: dashboard credential-hygiene gate (items 20/46).
 *
 * Fails when any route/component outside src/apiAuth.js:
 *  - reads "frontline_api_key" from storage directly, or
 *  - builds an api_key query string, or
 *  - defines a local apiHeaders() instead of importing the shared one.
 *
 * Run: node scripts/assert-auth-centralization.mjs
 */
import { readFileSync, readdirSync } from "node:fs";
import { join } from "node:path";

const ROOT = new URL("..", import.meta.url).pathname;
const DIRS = [join(ROOT, "routes"), join(ROOT, "src")];
const failures = [];

for (const dir of DIRS) {
  let files = [];
  try {
    files = readdirSync(dir).filter((f) => f.endsWith(".jsx") || f.endsWith(".js"));
  } catch {
    continue;
  }
  for (const f of files) {
    const p = join(dir, f);
    const src = readFileSync(p, "utf8");
    const rel = p.replace(ROOT, "");
    if (!p.endsWith("src/apiAuth.js")) {
      if (/frontline_api_key/.test(src)) {
        failures.push(`${rel}: direct frontline_api_key access (use apiAuth helpers)`);
      }
      if (/api_key=/.test(src) && !/withApiKeyQuery/.test(src)) {
        failures.push(`${rel}: raw api_key query construction`);
      }
      if (/function apiHeaders\(\)/.test(src)) {
        failures.push(`${rel}: local apiHeaders() (import from src/apiAuth.js)`);
      }
    }
  }
}

if (failures.length) {
  console.error("assert-auth-centralization: FAILED");
  for (const f of failures) console.error("  - " + f);
  process.exit(1);
}
console.log("assert-auth-centralization: PASSED");
