import { normalizeWeekTrend } from "./weekTrend.js";

/**
 * Fixed-slot week track. One data week sits in a row of reserved columns
 * instead of drawing a stray vertical bar that reads as a scrollbar.
 */
export default function WeekSpark({ trend, slots = 6, compact = false }) {
  const { slots: cols, max, filled } = normalizeWeekTrend(trend, slots);
  if (filled === 0) {
    return (
      <div className={"week-spark" + (compact ? " compact" : "")}>
        <span className="week-spark-empty">No weekly series</span>
      </div>
    );
  }

  const label = cols
    .filter((c) => !c.empty)
    .map((c) => `${c.iso_week}: ${c.record_count}`)
    .join(", ");

  return (
    <div
      className={"week-spark" + (compact ? " compact" : "")}
      role="img"
      aria-label={filled === 1 ? `One week, ${cols[cols.length - 1].record_count} records` : `Weekly volume, ${label}`}
    >
      <div className="week-spark-track">
        {cols.map((c, i) => {
          const h = c.empty ? 0 : Math.max(18, Math.round((c.record_count / max) * 100));
          return (
            <div
              key={`${c.iso_week || "e"}-${i}`}
              className={"week-spark-col" + (c.empty ? " empty" : "") + (c.is_anomaly ? " anomaly" : "")}
              title={c.empty ? undefined : `${c.iso_week} · ${c.record_count}`}
            >
              <div className="week-spark-bar" style={{ height: `${h}%` }} />
            </div>
          );
        })}
      </div>
    </div>
  );
}
