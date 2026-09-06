import { useEffect, useState } from "react";
import { apiHeaders } from "../src/apiAuth.js";
import WeekSpark from "../src/ui/WeekSpark.jsx";



export default function EarlyWarningBoard() {
  const [tab, setTab] = useState("clusters");
  const [clusters, setClusters] = useState([]);
  const [funnel, setFunnel] = useState(null);
  const [investigations, setInvestigations] = useState([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState(null);
  const [simModal, setSimModal] = useState(false);
  const [simCount, setSimCount] = useState(25);
  const [simSpeed, setSimSpeed] = useState("instant");
  const [simResult, setSimResult] = useState(null);
  const [simRunning, setSimRunning] = useState(false);
  const [metrics, setMetrics] = useState(null);
  const [includeSimulated, setIncludeSimulated] = useState(false);

  async function loadMetrics() {
    try {
      const r = await fetch("/api/frontline/metrics?window_days=7", {
        headers: apiHeaders(),
      });
      if (!r.ok) return;
      setMetrics(await r.json());
    } catch {
      /* optional strip */
    }
  }

  async function loadClusters() {
    setLoading(true);
    setError(null);
    try {
      const r = await fetch(
        `/api/frontline/early-warning?window_days=7&include_simulated=${includeSimulated ? "true" : "false"}`,
        {
          headers: apiHeaders(),
        }
      );
      if (!r.ok) throw new Error(`HTTP ${r.status}`);
      const d = await r.json();
      setClusters(d.live_risk || []);
      setFunnel(d.funnel || null);
      loadMetrics();
    } catch (e) {
      setError(String(e));
    } finally {
      setLoading(false);
    }
  }

  async function loadInvestigations() {
    setLoading(true);
    setError(null);
    try {
      // Load all statuses so closed/monitoring remain visible after PATCH.
      const r = await fetch(
        "/api/frontline/investigations?window_days=30",
        { headers: apiHeaders() }
      );
      if (!r.ok) throw new Error(`HTTP ${r.status}`);
      const d = await r.json();
      setInvestigations(d.investigations || []);
      loadMetrics();
    } catch (e) {
      setError(String(e));
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => {
    if (tab === "clusters") loadClusters();
    else if (tab === "investigations") loadInvestigations();
    else loadMetrics();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [tab, includeSimulated]);

  // Composite risk: live_count × critical_count
  const sortedClusters = [...clusters].sort((a, b) => {
    const ra = (a.live_case_count || 0) * (a.critical_count || 0);
    const rb = (b.live_case_count || 0) * (b.critical_count || 0);
    return rb - ra;
  });

  async function runSimulate() {
    setSimRunning(true);
    setSimResult(null);
    setError(null);
    try {
      const params = new URLSearchParams({
        count: String(simCount),
        speed: simSpeed,
      });
      const r = await fetch(
        `/api/frontline/simulate?${params.toString()}`,
        { method: "POST", headers: apiHeaders() }
      );
      if (!r.ok) throw new Error(`HTTP ${r.status}`);
      const d = await r.json();
      setSimResult(d);
      setIncludeSimulated(true);
      if (tab === "clusters") loadClusters();
      else loadInvestigations();
    } catch (e) {
      setError(String(e));
    } finally {
      setSimRunning(false);
    }
  }

  async function setInvStatus(inv, status) {
    setError(null);
    try {
      const r = await fetch(
        `/api/frontline/investigations/${encodeURIComponent(inv.investigation_id)}`,
        {
          method: "PATCH",
          headers: { ...apiHeaders(), "Content-Type": "application/json" },
          body: JSON.stringify({ status }),
        }
      );
      if (!r.ok) throw new Error(`HTTP ${r.status}: ${await r.text()}`);
      await loadInvestigations();
      loadMetrics();
    } catch (e) {
      setError(String(e));
    }
  }

  return (
    <div className="page-enter">
      <header className="page-header">
        <div>
          <h1>Early warning</h1>
          <p className="sub">
            Snapshot tiles, weekly funnel, and risk cards — simulate traffic to light the board.
          </p>
        </div>
        <div className="page-actions">
          <span className="build-stamp">Risk board</span>
          <label className="check-row" style={{ fontSize: 12, margin: 0 }}>
            <input
              type="checkbox"
              checked={includeSimulated}
              onChange={(e) => setIncludeSimulated(e.target.checked)}
            />
            Include simulated
          </label>
          <button type="button" className="primary" onClick={() => setSimModal(true)}>
            Simulate traffic
          </button>
          <button
            type="button"
            onClick={tab === "clusters" ? loadClusters : loadInvestigations}
            disabled={loading}
          >
            {loading ? "Loading…" : "Refresh"}
          </button>
        </div>
      </header>

      {error && (
        <div className="banner banner-error" role="alert">
          {error}{" "}
          <button type="button" className="ghost" onClick={() => setError(null)}>
            Dismiss
          </button>
        </div>
      )}

      <div className="tabs" role="tablist" aria-label="Early warning views">
        <button
          type="button"
          role="tab"
          aria-selected={tab === "clusters"}
          className={"tab" + (tab === "clusters" ? " active" : "")}
          onClick={() => setTab("clusters")}
        >
          Clusters
        </button>
        <button
          type="button"
          role="tab"
          aria-selected={tab === "investigations"}
          className={"tab" + (tab === "investigations" ? " active" : "")}
          onClick={() => setTab("investigations")}
        >
          Investigations
        </button>
        <button
          type="button"
          role="tab"
          aria-selected={tab === "fixes"}
          className={"tab" + (tab === "fixes" ? " active" : "")}
          onClick={() => setTab("fixes")}
        >
          Fix loop
        </button>
      </div>

      {loading && (
        <div className="empty-state">
          <p className="empty-state-text">Loading early-warning data…</p>
          <div className="skeleton" style={{ width: "60%", height: 12, marginTop: 10 }} />
          <div className="skeleton" style={{ width: "40%", height: 12, marginTop: 8 }} />
        </div>
      )}

      {tab === "clusters" && !loading && (
        <>
          {metrics && (
            <div className="snapshot-grid">
              <div className="snapshot-tile">
                <div className="k">Open cases</div>
                <div className="v">{metrics.cases?.open ?? 0}</div>
                <div className="h">7-day snapshot</div>
              </div>
              <div className="snapshot-tile danger">
                <div className="k">Critical open</div>
                <div className="v">{metrics.cases?.critical_open ?? 0}</div>
                <div className="h">needs eyes</div>
              </div>
              <div className="snapshot-tile warn">
                <div className="k">Investigations</div>
                <div className="v">{metrics.investigations?.open ?? 0}</div>
                <div className="h">open</div>
              </div>
              <div className="snapshot-tile accent">
                <div className="k">Active calls</div>
                <div className="v">{metrics.interactions_active ?? 0}</div>
                <div className="h">live right now</div>
              </div>
            </div>
          )}
          {funnel && funnel.include_simulated === false && funnel.simulated_count != null && (
            <p className="faint" style={{ margin: "0 0 10px" }}>
              {funnel.simulated_count} simulated contacts excluded from this board
            </p>
          )}
          {funnel && (
            <div className="funnel" aria-label="Weekly funnel">
              <div className="funnel-step"><div className="n">{funnel.started ?? 0}</div><div className="l">started</div></div>
              <div className="funnel-step"><div className="n">{funnel.completed ?? 0}</div><div className="l">completed</div></div>
              <div className="funnel-step"><div className="n">{funnel.cases_created ?? 0}</div><div className="l">cases</div></div>
              <div className="funnel-step"><div className="n">{funnel.advisories_notified ?? 0}</div><div className="l">advisories</div></div>
              <div className="funnel-step"><div className="n">{funnel.escalated ?? 0}</div><div className="l">escalated</div></div>
              <div className="funnel-step"><div className="n">{funnel.takeovers ?? 0}</div><div className="l">takeovers</div></div>
            </div>
          )}

          {sortedClusters.length > 0 && (
            <div className="risk-card-grid">
              {sortedClusters.slice(0, 4).map((c) => {
                const composite = (c.live_case_count || 0) * (c.critical_count || 0);
                return (
                  <div className="risk-card" key={`card-${c.pack_id}:${c.cluster_id}`}>
                    <div className="top">
                      <div>
                        <div className="mono faint" style={{ fontSize: 11 }}>{c.pack_id}</div>
                        <div style={{ fontWeight: 650, letterSpacing: "-0.02em", marginTop: 2 }}>
                          Cluster {c.cluster_id}
                        </div>
                      </div>
                      <div className={"score" + (composite > 0 ? " hot" : "")}>{composite}</div>
                    </div>
                    <WeekSpark trend={c.weekly_trend} />
                    <div className="meta-line">
                      <span>{c.live_case_count ?? 0} live</span>
                      <span>{c.critical_count ?? 0} critical</span>
                      <span>{c.lead_time_weeks != null ? `${c.lead_time_weeks}w lead` : "no lead time"}</span>
                      <span>{c.trend_scope || "no trend scope"}</span>
                    </div>
                  </div>
                );
              })}
            </div>
          )}

          <div className="panel" style={{ padding: 0, overflow: "hidden" }}>
            <table>
              <thead>
                <tr>
                  <th>cluster</th>
                  <th>pack</th>
                  <th>live cases</th>
                  <th>critical</th>
                  <th>composite risk</th>
                  <th>weekly trend</th>
                  <th>trend scope</th>
                  <th>backtest lead-time</th>
                  <th>matched advisory</th>
                  <th>last case</th>
                </tr>
              </thead>
              <tbody>
                {sortedClusters.length === 0 && (
                  <tr>
                    <td colSpan={10}>
                      <div className="hero-empty" style={{ margin: 16, border: "none" }}>
                        <h3>No live-risk clusters</h3>
                        <p>Simulate traffic to light up this board, or wait for real contacts to cluster.</p>
                        <button type="button" className="primary" onClick={() => setSimModal(true)}>
                          Simulate traffic
                        </button>
                      </div>
                    </td>
                  </tr>
                )}
                {sortedClusters.map((c) => {
                  const composite = (c.live_case_count || 0) * (c.critical_count || 0);
                  return (
                    <tr key={`${c.pack_id}:${c.cluster_id}`}>
                      <td><span className="chip teal">cluster {c.cluster_id}</span></td>
                      <td className="mono">{c.pack_id}</td>
                      <td className="mono">{c.live_case_count ?? 0}</td>
                      <td>
                        {c.critical_count > 0 ? (
                          <span className="chip red">{c.critical_count}</span>
                        ) : (
                          <span className="faint">0</span>
                        )}
                      </td>
                      <td className="mono"><strong>{composite}</strong></td>
                      <td><WeekSpark trend={c.weekly_trend} compact /></td>
                      <td className="mono faint">{c.trend_scope || "—"}</td>
                      <td className="mono">{c.lead_time_weeks != null ? `${c.lead_time_weeks}w` : "—"}</td>
                      <td className="mono">
                        {c.matched_advisory ? (
                          <span className="chip green">{c.matched_advisory}</span>
                        ) : (
                          <span className="faint">—</span>
                        )}
                      </td>
                      <td className="mono faint">
                        {c.last_case_at ? String(c.last_case_at).slice(0, 19) : "—"}
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        </>
      )}

      {/* ── Investigations tab ──────────────────────────────────────── */}
      {tab === "investigations" && !loading && (
        <div className="panel" style={{ padding: 0, overflow: "hidden" }}>
          <table>
            <thead>
              <tr>
                <th>investigation</th>
                <th>pack</th>
                <th>cluster</th>
                <th>title</th>
                <th>case count</th>
                <th>trend</th>
                <th>days open</th>
                <th>opened</th>
                <th>status</th>
              </tr>
            </thead>
            <tbody>
              {investigations.length === 0 && (
                <tr>
                  <td colSpan={9}>
                    <div className="empty">No open investigations.</div>
                  </td>
                </tr>
              )}
              {investigations.map((inv) => {
                const trend =
                  inv.cases && inv.cases.length
                    ? inv.cases
                        .map((c, i) => ({
                            iso_week: `c${i + 1}`,
                            record_count: 1,
                            is_anomaly: c.severity === "Critical",
                            z_score: c.severity === "Critical" ? 2 : 0,
                          }))
                        .slice(-6)
                    : [];
                return (
                  <tr key={inv.investigation_id}>
                    <td className="mono">{inv.investigation_id}</td>
                    <td className="mono">{inv.pack_id}</td>
                    <td>
                      <span className="chip purple">cluster {inv.cluster_id}</span>
                    </td>
                    <td>{inv.title}</td>
                    <td className="mono">{inv.case_count ?? (inv.cases?.length || 0)}</td>
                    <td>
                      <WeekSpark trend={trend} compact />
                    </td>
                    <td className="mono">
                      {inv.days_open != null ? `${inv.days_open}d` : "—"}
                    </td>
                    <td className="mono faint">
                      {inv.opened_at ? String(inv.opened_at).slice(0, 10) : "—"}
                    </td>
                    <td>
                      <span
                        className={
                          "chip " +
                          (inv.status === "open"
                            ? "red"
                            : inv.status === "monitoring"
                            ? "orange"
                            : "green")
                        }
                      >
                        {inv.status}
                      </span>
                      <div className="row" style={{ marginTop: 4, gap: 4 }}>
                        {inv.status !== "monitoring" && (
                          <button
                            className="ghost"
                            style={{ fontSize: 10, padding: "2px 6px" }}
                            onClick={() => setInvStatus(inv, "monitoring")}
                          >
                            → monitoring
                          </button>
                        )}
                        {inv.status !== "closed" && (
                          <button
                            className="ghost"
                            style={{ fontSize: 10, padding: "2px 6px" }}
                            onClick={() => setInvStatus(inv, "closed")}
                          >
                            → closed
                          </button>
                        )}
                      </div>
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      )}

      {/* ── Fix loop tab (item 37): before/after + reopen rate ───────── */}
      {tab === "fixes" && !loading && (
        <>
          {metrics?.fix_loop ? (
            <>
              <div className="snapshot-grid">
                <div className="snapshot-tile">
                  <div className="k">Fixes recorded</div>
                  <div className="v">{metrics.fix_loop.fixes_recorded ?? 0}</div>
                  <div className="h">auto-recorded on close</div>
                </div>
                <div className="snapshot-tile accent">
                  <div className="k">Resolved</div>
                  <div className="v">{metrics.fix_loop.resolved ?? 0}</div>
                  <div className="h">after-rate below before-rate</div>
                </div>
                <div className="snapshot-tile danger">
                  <div className="k">Reopened</div>
                  <div className="v">{metrics.fix_loop.reopened ?? 0}</div>
                  <div className="h">
                    reopen rate{" "}
                    {metrics.fix_loop.reopen_rate != null
                      ? `${Math.round(metrics.fix_loop.reopen_rate * 100)}%`
                      : "—"}
                  </div>
                </div>
              </div>
              <div className="panel" style={{ padding: 0, overflow: "hidden" }}>
                <table>
                  <thead>
                    <tr>
                      <th>fix</th>
                      <th>category</th>
                      <th>before</th>
                      <th>after</th>
                      <th>before → after</th>
                      <th>verdict</th>
                    </tr>
                  </thead>
                  <tbody>
                    {(metrics.fix_loop.series || []).length === 0 && (
                      <tr>
                        <td colSpan={6}>
                          <div className="empty">
                            No fixes measured yet — close an investigation to record one.
                          </div>
                        </td>
                      </tr>
                    )}
                    {(metrics.fix_loop.series || []).map((s) => {
                      const before = Number(s.before_count ?? 0);
                      const after = Number(s.after_count ?? 0);
                      const max = Math.max(before, after, 1);
                      return (
                        <tr key={s.fix_id}>
                          <td className="mono">{String(s.fix_id).slice(0, 12)}…</td>
                          <td>{s.category || "—"}</td>
                          <td className="mono">{before}</td>
                          <td className="mono">{after}</td>
                          <td>
                            <div
                              className="before-after"
                              role="img"
                              aria-label={`before ${before}, after ${after}`}
                            >
                              <div
                                className="ba-bar ba-before"
                                style={{ width: `${Math.round((before / max) * 100)}%` }}
                              />
                              <div
                                className="ba-bar ba-after"
                                style={{ width: `${Math.round((after / max) * 100)}%` }}
                              />
                            </div>
                          </td>
                          <td>
                            {s.improved ? (
                              <span className="chip green">resolved</span>
                            ) : (
                              <span className="chip orange">watch</span>
                            )}
                          </td>
                        </tr>
                      );
                    })}
                  </tbody>
                </table>
              </div>
            </>
          ) : (
            <div className="empty">Fix-loop metrics unavailable.</div>
          )}
        </>
      )}

      {/* ── Simulate modal ──────────────────────────────────────────── */}      {simModal && (
        <div
          className="modal-backdrop"
          onClick={(e) => e.target.className === "modal-backdrop" && setSimModal(false)}
        >
          <div className="modal">
            <h3>Simulate traffic</h3>
            <p className="muted" style={{ marginTop: -8, fontSize: 12 }}>
              Replay corpus records as simulated interactions.
            </p>
            <div className="row" style={{ gap: 16, marginTop: 12 }}>
              <div className="field" style={{ flex: 1 }}>
                <label>count</label>
                <input
                  type="number"
                  min={1}
                  max={100}
                  value={simCount}
                  onChange={(e) => setSimCount(Math.max(1, Math.min(100, Number(e.target.value) || 1)))}
                />
              </div>
              <div className="field" style={{ flex: 1 }}>
                <label>speed</label>
                <select value={simSpeed} onChange={(e) => setSimSpeed(e.target.value)}>
                  <option value="instant">instant</option>
                  <option value="fast">fast</option>
                  <option value="realtime">realtime</option>
                </select>
              </div>
            </div>
            {simResult && (
              <div className="panel" style={{ marginTop: 14, padding: 12 }}>
                <div className="kvs">
                  <span className="k">completed</span>
                  <span className="v ok-text">{simResult.completed}</span>
                  <span className="k">abandoned</span>
                  <span className="v warn-text">{simResult.abandoned}</span>
                  <span className="k">escalated</span>
                  <span className="v err-text">{simResult.escalated}</span>
                  <span className="k">cases_created</span>
                  <span className="v">{simResult.cases_created}</span>
                  <span className="k">investigations_opened</span>
                  <span className="v">{simResult.investigations_opened}</span>
                  {simResult.errors?.length > 0 && (
                    <>
                      <span className="k">errors</span>
                      <span className="v err-text">{simResult.errors.length}</span>
                    </>
                  )}
                </div>
              </div>
            )}
            <div className="row" style={{ justifyContent: "flex-end", marginTop: 18, gap: 8 }}>
              <button className="ghost" onClick={() => setSimModal(false)}>
                Close
              </button>
              <button className="primary" onClick={runSimulate} disabled={simRunning}>
                {simRunning ? "running…" : "Run"}
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
