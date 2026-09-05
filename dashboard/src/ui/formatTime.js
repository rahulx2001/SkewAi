/** Compact UTC clock for dashboard tiles. Never dump a raw ISO stamp. */

const MONTHS = [
  "Jan",
  "Feb",
  "Mar",
  "Apr",
  "May",
  "Jun",
  "Jul",
  "Aug",
  "Sep",
  "Oct",
  "Nov",
  "Dec",
];

export function formatSnapshotTs(raw) {
  const s = String(raw ?? "").trim();
  if (!s) return "";
  const stamped = /[zZ]|[+-]\d{2}:\d{2}$/.test(s) ? s : `${s}Z`;
  const d = new Date(stamped);
  if (Number.isNaN(d.getTime())) return s;
  const hh = String(d.getUTCHours()).padStart(2, "0");
  const mm = String(d.getUTCMinutes()).padStart(2, "0");
  return `${d.getUTCDate()} ${MONTHS[d.getUTCMonth()]} ${hh}:${mm} UTC`;
}
