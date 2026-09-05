/** Normalize API weekly_anomaly rows into a left→right week series. */

export function sortOldestFirst(rows) {
  return [...(rows || [])].sort((a, b) =>
    String(a.iso_week || "").localeCompare(String(b.iso_week || "")),
  );
}

export function aggregateByWeek(rows) {
  const by = new Map();
  for (const r of rows || []) {
    const week = String(r.iso_week || "").trim();
    if (!week) continue;
    const n = Number(r.record_count) || 0;
    const prev = by.get(week) || { iso_week: week, record_count: 0, is_anomaly: false, z_score: null };
    prev.record_count += n;
    prev.is_anomaly = Boolean(prev.is_anomaly || r.is_anomaly);
    const z = r.z_score == null ? null : Number(r.z_score);
    if (z != null && Number.isFinite(z)) {
      prev.z_score = prev.z_score == null ? z : Math.max(prev.z_score, z);
    }
    by.set(week, prev);
  }
  return sortOldestFirst([...by.values()]);
}

/**
 * Pad to a fixed number of slots so one week never becomes a lone vertical
 * bar. Empty leading slots hold the shape of a series.
 */
export function normalizeWeekTrend(rows, slots = 6) {
  const n = Math.max(2, Number(slots) || 6);
  const series = aggregateByWeek(rows).slice(-n);
  const pad = Math.max(0, n - series.length);
  const out = [];
  for (let i = 0; i < pad; i += 1) {
    out.push({ iso_week: "", record_count: 0, is_anomaly: false, empty: true });
  }
  for (const r of series) {
    out.push({ ...r, empty: false });
  }
  const values = series.map((r) => r.record_count);
  const max = Math.max(1, ...values);
  const filled = series.length;
  return { slots: out, max, filled };
}
