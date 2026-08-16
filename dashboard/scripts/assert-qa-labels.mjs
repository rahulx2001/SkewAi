#!/usr/bin/env node
/**
 * Drive shipped labels.js + grep defect strings (QA audit fix gate).
 */
import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";
import {
  statusLabel,
  weaknessLabel,
  capabilityLabel,
  proposalTitle,
  proposalDetailParts,
  formatDetailValue,
} from "../src/ui/labels.js";

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const root = path.resolve(__dirname, "..");

function fail(msg) {
  console.error("FAIL:", msg);
  process.exitCode = 1;
}
function ok(msg) {
  console.log("OK:", msg);
}

// Label map behavior
const cases = [
  [statusLabel("open"), "Open"],
  [statusLabel("pending_followup"), "Pending follow-up"],
  [statusLabel("closed"), "Closed"],
  [weaknessLabel("abandoned_or_incomplete"), "Abandoned or incomplete"],
  [capabilityLabel("stt"), "Speech to text"],
  [capabilityLabel("barge_in"), "Barge-in"],
];
for (const [got, want] of cases) {
  if (got !== want) fail(`expected ${want}, got ${got}`);
  else ok(`${want}`);
}

const title = proposalTitle({
  title: "abandoned_or_incomplete on int_01kymx0w1qe4ece829jvyzh6tk",
  weakness_class: "abandoned_or_incomplete",
  interaction_id: "int_01kymx0w1qe4ece829jvyzh6tk",
});
if (!/Abandoned/i.test(title)) fail(`proposalTitle not humanized: ${title}`);
if (/abandoned_or_incomplete on int_/i.test(title)) fail(`raw title still shown: ${title}`);
ok(`proposalTitle: ${title}`);

const parts = proposalDetailParts({
  detail: "blame=intake; confidence=0.54; why=status=abandoned outcome=incomplete",
});
if (parts.blame !== "Intake") fail(`blame: ${parts.blame}`);
if (parts.confidence !== "0.54") fail(`confidence: ${parts.confidence}`);
ok("proposalDetailParts parsed");

if (formatDetailValue({ summary: "hello" }) !== "hello") fail("formatDetailValue summary");
ok("formatDetailValue");

// Retired defect strings in source
const checks = [
  ["routes/CaseQueue.jsx", (s) => s.includes("statusLabel") && s.includes("statusLabel(s)"), "CaseQueue uses statusLabel"],
  ["routes/EnterpriseOps.jsx", (s) => !s.includes("#1a1f2e") && !s.includes("panel-2") && s.includes("Load timeline"), "Enterprise no dark fallback"],
  ["routes/Settings.jsx", (s) => !s.includes('placeholder="FRONTLINE_API_KEY"') && s.includes("Paste pilot API key") && !s.includes("hooks.example.com/frontline"), "Settings brand"],
  ["src/App.jsx", (s) => !s.includes("fill wallboard") && !s.includes("Health re-checked"), "App shell strings"],
  ["routes/CommandCenter.jsx", (s) => !s.includes("Could not load wallboard") && s.includes("command center"), "Command center error"],
  ["routes/CallWidget.jsx", (s) => s.includes("voice-cta") && s.includes("capabilityLabel"), "Voice CTA + caps"],
  ["routes/PlatformOS.jsx", (s) => s.includes("proposalTitle") && s.includes("Scan failures") && s.includes("Approve"), "Platform OS"],
];

for (const [rel, pred, name] of checks) {
  const s = fs.readFileSync(path.join(root, rel), "utf8");
  if (!pred(s)) fail(name);
  else ok(name);
}

if (process.exitCode) {
  console.error("\nassert-qa-labels: FAILED");
  process.exit(1);
}
console.log("\nassert-qa-labels: PASSED");
