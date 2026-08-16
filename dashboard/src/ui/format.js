/**
 * Display formatters.
 *
 * Server timestamps are naive strings without an offset. Rendering them through
 * `new Date()` would silently reinterpret them in the browser's zone, so the
 * helpers here keep the raw wall-clock reading and label it explicitly rather
 * than guessing a zone.
 */

const MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];

function parseParts(value) {
  if (!value) return null;
  const m = String(value).match(
    /^(\d{4})-(\d{2})-(\d{2})[T ](\d{2}):(\d{2})(?::(\d{2}))?(?:\.\d+)?(Z|[+-]\d{2}:?\d{2})?$/,
  );
  if (!m) return null;
  return {
    year: +m[1],
    month: +m[2],
    day: +m[3],
    hour: +m[4],
    minute: +m[5],
    second: m[6] ? +m[6] : 0,
    offset: m[7] || null,
  };
}

/** Absolute timestamp, e.g. "28 Jul 01:24" — never shifted between zones. */
export function fmtTime(value, { withDate = true, withSeconds = false } = {}) {
  const p = parseParts(value);
  if (!p) return value ? String(value) : "—";
  const hh = String(p.hour).padStart(2, "0");
  const mm = String(p.minute).padStart(2, "0");
  const clock = withSeconds ? `${hh}:${mm}:${String(p.second).padStart(2, "0")}` : `${hh}:${mm}`;
  if (!withDate) return clock;
  return `${p.day} ${MONTHS[p.month - 1]} ${clock}`;
}

/** Zone label for a raw server value, so two readers never disagree silently. */
export function zoneLabel(value) {
  const p = parseParts(value);
  if (!p) return "";
  if (p.offset === "Z") return "UTC";
  if (p.offset) return `UTC${p.offset}`;
  return "server time";
}

/** Milliseconds between a server timestamp and now, treating both as wall clock. */
function elapsedMs(value) {
  const p = parseParts(value);
  if (!p) return null;
  const then = Date.UTC(p.year, p.month - 1, p.day, p.hour, p.minute, p.second);
  const n = new Date();
  const now = Date.UTC(
    n.getFullYear(),
    n.getMonth(),
    n.getDate(),
    n.getHours(),
    n.getMinutes(),
    n.getSeconds(),
  );
  return now - then;
}

/** "just now" / "4m ago" / "2h ago" / falls back to the absolute stamp. */
export function fmtRelative(value) {
  const ms = elapsedMs(value);
  if (ms === null) return value ? String(value) : "—";
  const s = Math.round(ms / 1000);
  if (s < 0) return "just now";
  if (s < 10) return "just now";
  if (s < 60) return `${s}s ago`;
  const m = Math.round(s / 60);
  if (m < 60) return `${m}m ago`;
  const h = Math.round(m / 60);
  if (h < 24) return `${h}h ago`;
  return fmtTime(value);
}

/** Compact counts: 1200 -> "1.2k". Keeps small numbers exact for ops accuracy. */
export function fmtCount(value) {
  if (value === null || value === undefined || value === "") return "—";
  const n = Number(value);
  if (!Number.isFinite(n)) return String(value);
  if (Math.abs(n) < 1000) return String(n);
  if (Math.abs(n) < 1_000_000) return `${(n / 1000).toFixed(n % 1000 === 0 ? 0 : 1)}k`;
  return `${(n / 1_000_000).toFixed(1)}M`;
}

export function fmtDuration(ms) {
  if (ms === null || ms === undefined) return "—";
  const n = Number(ms);
  if (!Number.isFinite(n)) return "—";
  if (n < 1000) return `${Math.round(n)}ms`;
  if (n < 60_000) return `${(n / 1000).toFixed(1)}s`;
  const mins = Math.floor(n / 60_000);
  const secs = Math.round((n % 60_000) / 1000);
  return `${mins}m ${secs}s`;
}

export function fmtPercent(value, digits = 0) {
  if (value === null || value === undefined) return "—";
  const n = Number(value);
  if (!Number.isFinite(n)) return "—";
  const pct = n <= 1 && n >= -1 ? n * 100 : n;
  return `${pct.toFixed(digits)}%`;
}

/** Humanise snake_case keys for label display. */
export function fmtLabel(key) {
  return String(key || "")
    .replace(/_/g, " ")
    .replace(/^\w/, (c) => c.toUpperCase());
}

export function severityClass(severity) {
  return String(severity || "").toLowerCase();
}
