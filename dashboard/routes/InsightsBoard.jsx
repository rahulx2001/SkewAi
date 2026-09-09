import { useCallback, useEffect, useState } from "react";
import { apiHeaders } from "../src/apiAuth.js";
import { includeSimQuery, openWarning } from "../src/ui/opsActions.js";
import { outcomeLabel } from "../src/ui/labels.js";

/**
 * CSAT proxy + product-gap board — industry ops layout (stats + tables).
 * Honest: satisfaction_proxy is friction-based, not survey NPS.
 */
export default function InsightsBoard({ embedded }) {
  const [csat, setCsat] = useState(null);
  const [gap, setGap] = useState(null);
  const [err, setErr] = useState("");
  const [loading, setLoading] = useState(true);
  const [windowDays, setWindowDays] = useState(14);

  const load = useCallback(async () => {
    setErr("");
    setLoading(true);
    try {
      const h = apiHeaders();
      const [a, b] = await Promise.all([
        fetch(`/api/frontline/insights/csat?window_days=${windowDays}&include_simulated=${includeSimQuery()}`, { headers: h }),
        fetch(`/api/frontline/insights/product-gap?window_days=${windowDays}&include_simulated=${includeSimQuery()}`, { headers: h }),
      ]);
      if (!a.ok) throw new Error(`csat ${a.status}`);
      if (!b.ok) throw new Error(`gap ${b.status}`);
      setCsat(await a.json());
      setGap(await b.json());
    } catch (e) {
      setErr(String(e.message || e));
    } finally {
      setLoading(false);
    }
  }, [windowDays]);

  useEffect(() => {
    load();
  }, [load]);

  const satPct =
    csat && csat.contact_count > 0 && typeof csat.satisfaction_proxy === "number"
      ? Math.round(csat.satisfaction_proxy * 100)
      : null;

  return (
    <div>
      {!embedded && (
        <header className="page-header">
          <div>
            <h1>Insights</h1>
            <p className="sub">
              Friction proxy, not survey NPS. Percentage is hidden until the window has contacts.
            </p>
          </div>
          <div className="page-actions">
            <label style={{ minWidth: 120 }}>
              Window (days)
              <input
                type="number"
                min={1}
                max={90}
                value={windowDays}
                onChange={(e) => {
                  const n = Number(e.target.value);
                  if (Number.isFinite(n) && n >= 1) setWindowDays(Math.min(90, n));
                }}
                aria-label="Window in days"
              />
            </label>
            <button type="button" onClick={load} disabled={loading}>
              {loading ? "Loading…" : "Refresh"}
            </button>
          </div>
        </header>
      )}
      {embedded && (
        <div className="row" style={{ gap: 8, marginBottom: 12 }}>
          <label style={{ minWidth: 120 }}>
            Window (days)
            <input
              type="number"
              min={1}
              max={90}
              value={windowDays}
              onChange={(e) => {
                const n = Number(e.target.value);
                if (Number.isFinite(n) && n >= 1) setWindowDays(Math.min(90, n));
              }}
              aria-label="Window in days"
            />
          </label>
          <button type="button" onClick={load} disabled={loading}>
            {loading ? "Loading…" : "Refresh"}
          </button>
        </div>
      )}

      {err && (
        <div className="banner banner-error" role="alert">
          {err}
        </div>
      )}

      <div className="stat-grid" style={{ marginBottom: 16 }}>
        <div className="stat-card accent">
          <div className="label">Friction</div>
          <div className="value">
            {satPct == null ? "—" : satPct >= 99 ? "Low" : `${100 - satPct}%`}
          </div>
          <div className="hint">
            Peak-frustration proxy · {csat?.contact_count ?? 0} contacts · {windowDays}d
          </div>
        </div>
        <div className="stat-card">
          <div className="label">Contacts</div>
          <div className="value">{csat?.contact_count ?? "—"}</div>
          <div className="hint">{windowDays}d window</div>
        </div>
        <div className="stat-card danger">
          <div className="label">Angry contacts</div>
          <div className="value">{csat?.angry_contacts ?? "—"}</div>
          <div className="hint">peak frustration ≥ 0.65</div>
        </div>
        <div className="stat-card">
          <div className="label">Safety-flagged</div>
          <div className="value">{csat?.safety_flagged_cases ?? "—"}</div>
          <div className="hint">cases in window</div>
        </div>
      </div>

      <div className="grid-2">
        <section className="panel">
          <h2>Outcome mix</h2>
          {!csat ? (
            <div className="empty-state">
              <p className="empty-state-text">{loading ? "Loading…" : "No CSAT data yet."}</p>
            </div>
          ) : Object.keys(csat.outcome_mix || {}).length === 0 ? (
            <div className="empty-state">
              <p className="empty-state-text">No outcomes recorded in this window.</p>
            </div>
          ) : (
            <div className="table-wrap">
              <table>
                <thead>
                  <tr>
                    <th>Outcome</th>
                    <th>Count</th>
                  </tr>
                </thead>
                <tbody>
                  {Object.entries(csat.outcome_mix || {}).map(([k, v]) => (
                    <tr key={k}>
                      <td>{outcomeLabel(k)}</td>
                      <td className="mono">{v}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
          <div className="h-divider" />
          <h3>Top themes</h3>
          {(csat?.top_themes || []).length === 0 ? (
            <div className="empty-state">
              <p className="empty-state-text">No themes yet — complete more contacts.</p>
            </div>
          ) : (
            <ul className="bar-list">
              {(csat.top_themes || []).map((t) => {
                const max = Math.max(...(csat.top_themes || []).map((x) => x.volume || 0), 1);
                const pct = Math.round(((t.volume || 0) / max) * 100);
                return (
                  <li key={t.theme}>
                    <div className="bar-list-head">
                      <span>{t.theme}</span>
                      <span className="mono">{t.volume}</span>
                    </div>
                    <div className="bar-track" aria-hidden="true">
                      <div className="bar-fill" style={{ width: `${pct}%` }} />
                    </div>
                  </li>
                );
              })}
            </ul>
          )}
          {csat && (
            <p className="muted small" style={{ marginTop: 12 }}>
              Avg peak frustration:{" "}
              <span className="mono">{csat.avg_peak_frustration ?? "—"}</span>
            </p>
          )}
        </section>

        <section className="panel">
          <h2>Product gap board</h2>
          {!gap ? (
            <div className="empty-state">
              <p className="empty-state-text">{loading ? "Loading…" : "No gap data yet."}</p>
            </div>
          ) : (gap.top_issues || []).length === 0 ? (
            <div className="empty-state">
              <p className="empty-state-text">No clustered issues in this window.</p>
            </div>
          ) : (
            <div className="table-wrap">
              <table>
                <thead>
                  <tr>
                    <th>Issue</th>
                    <th>Vol</th>
                    <th>Crit</th>
                    <th>Drift</th>
                    <th>Worse</th>
                  </tr>
                </thead>
                <tbody>
                  {(gap.top_issues || []).map((i) => (
                    <tr
                      key={i.issue_key}
                      style={{ cursor: i.cluster_id != null ? "pointer" : undefined }}
                      tabIndex={i.cluster_id != null ? 0 : undefined}
                      onClick={() => {
                        if (i.cluster_id != null) openWarning({ clusterId: i.cluster_id, tab: "risk" });
                      }}
                      onKeyDown={(e) => {
                        if (i.cluster_id == null) return;
                        if (e.key === "Enter" || e.key === " ") {
                          e.preventDefault();
                          openWarning({ clusterId: i.cluster_id, tab: "risk" });
                        }
                      }}
                    >
                      <td>
                        {i.category || i.issue_key}
                        {i.cluster_id != null ? (
                          <span className="mono faint"> #{i.cluster_id}</span>
                        ) : null}
                      </td>
                      <td className="mono">{i.volume}</td>
                      <td className="mono">{i.severity_mix?.Critical ?? 0}</td>
                      <td className="mono">{i.severity_drift}</td>
                      <td>
                        <span className={i.getting_worse ? "err-text" : "ok-text"}>
                          {i.getting_worse ? "yes" : "no"}
                        </span>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
          <div className="h-divider" />
          <h3>Rising severity</h3>
          {(gap?.rising_issues || []).length === 0 ? (
            <div className="empty-state">
              <p className="empty-state-text">No rising severity signals in window.</p>
            </div>
          ) : (
            <ul className="plain">
              {(gap.rising_issues || []).map((i) => (
                <li key={"r" + i.issue_key}>
                  {i.category || i.issue_key}{" "}
                  <span className="mono muted">(drift {i.severity_drift})</span>
                </li>
              ))}
            </ul>
          )}
        </section>
      </div>
    </div>
  );
}
