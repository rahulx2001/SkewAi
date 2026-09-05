#!/usr/bin/env node
/**
 * Drive the shipped week-trend helper. A single week must occupy one of
 * several reserved slots — never become a lone vertical bar.
 */
import { aggregateByWeek, normalizeWeekTrend } from "../src/ui/weekTrend.js";

function fail(msg) {
  console.error("FAIL:", msg);
  process.exitCode = 1;
}
function ok(msg) {
  console.log("OK:", msg);
}

const empty = normalizeWeekTrend([], 6);
if (empty.filled !== 0 || empty.slots.length !== 6) {
  fail(`empty series should pad 6 empty slots, got filled=${empty.filled} n=${empty.slots.length}`);
} else {
  ok("empty series pads 6 empty slots");
}

const one = normalizeWeekTrend([{ iso_week: "2026-W32", record_count: 10, is_anomaly: false }], 6);
if (one.filled !== 1 || one.slots.length !== 6) {
  fail(`one week must stay 6 slots, got filled=${one.filled} n=${one.slots.length}`);
} else if (!one.slots.slice(0, 5).every((s) => s.empty) || one.slots[5].record_count !== 10) {
  fail("one week must sit in the last reserved slot, not as a lone bar");
} else {
  ok("one week sits in a 6-slot track");
}

const mixed = aggregateByWeek([
  { iso_week: "2026-W31", record_count: 4, is_anomaly: false },
  { iso_week: "2026-W31", record_count: 6, is_anomaly: true },
  { iso_week: "2026-W32", record_count: 3, is_anomaly: false },
]);
if (mixed.length !== 2 || mixed[0].record_count !== 10 || mixed[0].is_anomaly !== true) {
  fail(`aggregateByWeek failed: ${JSON.stringify(mixed)}`);
} else {
  ok("same-week slices collapse to one column");
}

const long = normalizeWeekTrend(
  [1, 2, 3, 4, 5, 6, 7, 8].map((w) => ({ iso_week: `2026-W${String(w).padStart(2, "0")}`, record_count: w })),
  6,
);
if (long.filled !== 6 || long.slots[0].iso_week !== "2026-W03") {
  fail(`should keep last 6 weeks, got ${JSON.stringify(long.slots.map((s) => s.iso_week))}`);
} else {
  ok("keeps the most recent 6 weeks");
}

if (process.exitCode) {
  console.error("\nassert-week-spark: FAILED");
  process.exit(1);
}
console.log("\nassert-week-spark: PASSED");
