import { useCallback, useEffect, useState } from "react";
import { apiHeaders } from "../src/apiAuth.js";
import {
  fetchCriticalCases,
  goHash,
  includeSimQuery,
  openCases,
  openConsole,
  openWarning,
  readIncludeSimulated,
  simulateTraffic,
} from "../src/ui/opsActions.js";
import { dayGreeting } from "../src/ui/greeting.js";
import { formatSnapshotTs } from "../src/ui/formatTime.js";
import { packLabel } from "../src/ui/labels.js";

/**
 * Command Center — flagship wallboard.
 * One glance at live ops before diving into voice / cases.
 */
export default function CommandCenter({ refreshKey }) {
  const [health, setHealth] = useState(null);
  const [wall, setWall] = useState(null);
  const [metrics, setMetrics] = useState(null);
  const [usage, setUsage] = useState(null);
  const [drain, setDrain] = useState(null);
  const [p1Cases, setP1Cases] = useState([]);
  const [err, setErr] = useState("");
  const [msg, setMsg] = useState("");
  const [loading, setLoading] = useState(true);
  const [simBusy, setSimBusy] = useState(false);
  const [tick, setTick] = useState(() => new Date());

  const load = useCallback(async () => {
    setErr("");
    setLoading(true);
    try {
      const h = apiHeaders();
      const [a, b, c, d, e, p1] = await Promise.all([
        fetch("/health"),
        fetch(`/api/frontline/wallboard?include_simulated=${includeSimQuery()}`, { headers: h }),
        fetch(`/api/frontline/metrics?include_simulated=${includeSimQuery()}`, { headers: h }),
        fetch("/api/frontline/usage", { headers: h }),
        fetch("/api/frontline/ops/drain", { headers: h }),
        fetchCriticalCases(8),
      ]);
      if (!a.ok) throw new Error(`health ${a.status}`);
      setHealth(await a.json());
      setWall(b.ok ? await b.json() : null);
      setMetrics(c.ok ? await c.json() : null);
      setUsage(d.ok ? await d.json() : null);
      setDrain(e.ok ? await e.json() : null);
      setP1Cases(p1);
      setTick(new Date());
    } catch (ex) {
      setErr(String(ex.message || ex));
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    load();
    const t = setInterval(load, 12000);
    return () => clearInterval(t);
  }, [load, refreshKey]);

  async function runSimulate() {
    setSimBusy(true);
    setMsg("");
    setErr("");
    try {
      const d = await simulateTraffic({ count: 15 });
      setMsg(
        `Simulated traffic loaded · completed ${d.completed ?? d.count ?? "?"} · cases created ${d.cases_created ?? "—"}`,
      );
      await load();
    } catch (e) {
      setErr(String(e.message || e));
    } finally {
      setSimBusy(false);
    }
  }

  const live = Array.isArray(wall?.live_contacts) ? wall.live_contacts : [];
  const clusters = wall?.top_risk_clusters || wall?.top_clusters || [];
  const liveCount =
    wall?.active_contacts ?? wall?.active_count ?? wall?.live_count ?? live.length ?? 0;
  const p1 = wall?.critical_open ?? wall?.p1_open ?? 0;
  const openCaseCount = wall?.open_cases ?? 0;
  const draining = Boolean(drain?.draining);

  return (
    <div className="page-enter">
      <section className="cc-hero" aria-label="Command center overview">
        <div className="cc-hero-copy">
          <h1 className="cc-greeting">{dayGreeting(tick)}</h1>
        </div>
        <div className="cc-hero-meta">
          <button type="button" className="ghost" onClick={load} disabled={loading}>
            {loading ? "Refreshing…" : "Refresh"}
          </button>
        </div>
      </section>

      {msg && (
        <div className="banner banner-ok" role="status">
          {msg}
        </div>
      )}

      {err && (
        <div className="banner banner-error" role="alert">
          Could not load command center: <span className="mono">{err}</span>
        </div>
      )}

      {loading && !wall && (
        <div className="cc-skel" aria-hidden="true">
          <div className="skeleton block" />
          <div className="skeleton block" />
          <div className="skeleton block" />
          <div className="skeleton block" />
        </div>
      )}

      {readIncludeSimulated() && (
        <p className="faint" style={{ margin: "0 0 10px" }}>
          Including simulated contacts (toggle on Early warning).
        </p>
      )}

      <div className="stat-grid" style={{ marginBottom: 16 }}>
        <button
          type="button"
          className="stat-card stat-card-btn"
          onClick={() => openConsole()}
          title="Open live console"
        >
          <div className="label">Live contacts</div>
          <div className="value">{liveCount}</div>
          <div className="hint">Active now</div>
        </button>
        <button
          type="button"
          className={`stat-card ${Number(p1) > 0 ? "danger" : ""} stat-card-btn`}
          onClick={() => openCases({ severity: "Critical", status: "open" })}
          title="Open Critical case queue"
        >
          <div className="label">Critical open</div>
          <div className="value">{p1}</div>
          <div className="hint">Needs a look</div>
        </button>
        <button
          type="button"
          className="stat-card stat-card-btn"
          onClick={() => openCases({ status: "open" })}
          title="Open case queue"
        >
          <div className="label">Open cases</div>
          <div className="value">{openCaseCount}</div>
          <div className="hint">Open and follow-up</div>
        </button>
        <button
          type="button"
          className={`stat-card ${draining ? "danger" : "ok"} stat-card-btn`}
          onClick={() => goHash("settings?tab=lab&view=ops")}
          title="Open drain controls in Feature lab"
        >
          <div className="label">Deploy drain</div>
          <div className="value" style={{ fontSize: 24, letterSpacing: "-0.04em" }}>
            {draining ? "Draining" : "Ready"}
          </div>
          <div className="hint">
            {draining
              ? `${drain?.active_count ?? 0} still active`
              : "New contacts accepted"}
          </div>
        </button>
      </div>

      <div className="cc-section-label">
        <h2>Floor view</h2>
        <span>Live contacts · top risk clusters</span>
      </div>

      <div className="grid-2">
        <section className="panel">
          <h2>
            Live contacts
            <span className="faint" style={{ fontWeight: 500, letterSpacing: 0 }}>
              {live.length} active
            </span>
          </h2>
          {live.length === 0 ? (
            <div className="empty-state">
              <p className="empty-state-text">
                No active contacts. Start one from Voice agent.
              </p>
              <div className="row" style={{ marginTop: 12 }}>
                <button type="button" className="primary" onClick={() => (window.location.hash = "call")}>
                  Start a contact
                </button>
              </div>
            </div>
          ) : (
            <div className="live-feed">
              {live.map((row) => (
                <button
                  type="button"
                  className="live-row live-row-btn"
                  key={row.interaction_id}
                  onClick={() => openConsole(row.interaction_id)}
                  title="Open in live console"
                >
                  <span className="dot" aria-hidden="true" />
                  <div className="id" title={row.interaction_id}>
                    {row.interaction_id}
                  </div>
                  <div className="meta">
                    {[row.pack_id, row.category].filter(Boolean).join(" · ") || "intake in progress"}
                  </div>
                  <div className="chan">
                    {row.channel === "simulated" ? (
                      <span className="chip purple" style={{ fontSize: 10, padding: "2px 6px" }}>simulated</span>
                    ) : (
                      row.channel || "open →"
                    )}
                  </div>
                </button>
              ))}
            </div>
          )}
        </section>

        <section className="panel">
          <h2>
            Top risk clusters
            <span className="faint" style={{ fontWeight: 500, letterSpacing: 0 }}>
              by open cases
            </span>
          </h2>
          {clusters.length === 0 ? (
            <div className="empty-state">
              <p className="empty-state-text">
                No open clustered cases yet. Early warning lights up here when similar contacts
                share a cluster.
              </p>
              <button
                type="button"
                className="ghost"
                style={{ marginTop: 12 }}
                onClick={() => (window.location.hash = "warning")}
              >
                Open early warning
              </button>
            </div>
          ) : (
            <div className="risk-list">
              {clusters.map((c, i) => (
                <button
                  type="button"
                  className="risk-row"
                  key={`${c.pack_id}-${c.cluster_id}`}
                  onClick={() => openWarning({ clusterId: c.cluster_id, packId: c.pack_id })}
                >
                  <div className="risk-rank">#{String(i + 1).padStart(2, "0")}</div>
                  <div className="risk-main">
                    <div className="title">
                      Cluster {c.cluster_id}{" "}
                      <span className={`sev ${(c.max_severity || "").toLowerCase()}`}>
                        {c.max_severity || "—"}
                      </span>
                    </div>
                    <div className="hint">{packLabel(c.pack_id)}</div>
                  </div>
                  <div className="risk-count" title="Open cases">
                    {c.open_cases}
                  </div>
                </button>
              ))}
            </div>
          )}
        </section>
      </div>

      <div className="cc-section-label">
        <h2>Critical queue</h2>
        <span>Open Critical cases — click a row to open the case queue</span>
      </div>
      <section className="panel" style={{ marginBottom: 16 }}>
        {p1Cases.length === 0 ? (
          <div className="empty-state">
            <p className="empty-state-text">
              No open Critical cases. Simulate traffic or take live contacts to light this up.
            </p>
            <div className="row" style={{ marginTop: 10 }}>
              <button type="button" className="ghost" onClick={runSimulate} disabled={simBusy}>
                {simBusy ? "Seeding…" : "Seed demo traffic"}
              </button>
              <button type="button" className="ghost" onClick={() => openCases({ status: "open" })}>
                All open cases
              </button>
            </div>
          </div>
        ) : (
          <div className="table-wrap">
            <table>
              <thead>
                <tr>
                  <th>Case</th>
                  <th>Category</th>
                  <th>Severity</th>
                  <th>Status</th>
                  <th />
                </tr>
              </thead>
              <tbody>
                {p1Cases.map((c) => (
                  <tr
                    key={c.case_id}
                    style={{ cursor: "pointer" }}
                    tabIndex={0}
                    onClick={() =>
                      openCases({
                        severity: "Critical",
                        status: "open",
                        caseId: c.case_id,
                      })
                    }
                    onKeyDown={(e) => {
                      if (e.key === "Enter" || e.key === " ") {
                        e.preventDefault();
                        openCases({
                          severity: "Critical",
                          status: "open",
                          caseId: c.case_id,
                        });
                      }
                    }}
                  >
                    <td className="mono">{c.case_id}</td>
                    <td>{c.category || "—"}</td>
                    <td>{c.severity || "Critical"}</td>
                    <td>{c.status}</td>
                    <td>
                      <button
                        type="button"
                        className="ghost"
                        onClick={(e) => {
                          e.stopPropagation();
                          openCases({
                            severity: "Critical",
                            status: "open",
                            caseId: c.case_id,
                          });
                        }}
                      >
                        Open
                      </button>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </section>

      <div className="cc-section-label">
        <h2>System readiness</h2>
        <span>Health · metering · pilot metrics</span>
      </div>

      <div className="readiness-strip">
        <div className="readiness-item">
          <div className="k">API status</div>
          <div className={`v ${health?.status === "ok" ? "ok-text" : "warn-text"}`}>
            {health?.status || "connecting"}
          </div>
        </div>
        <div className="readiness-item">
          <div className="k">Auth</div>
          <div className="v">{health?.auth_required ? "API key required" : "open local"}</div>
        </div>
        <div className="readiness-item">
          <div className="k">Database</div>
          <div className="v">{health?.db_ok ? "reachable" : "check connection"}</div>
        </div>
        <div className="readiness-item">
          <div className="k">Pack load</div>
          <div className="v">{health?.pack_ok ? "ok" : "failed"}</div>
        </div>
        <div className="readiness-item">
          <div className="k">LLM</div>
          <div className={`v ${health?.llm_available ? "ok-text" : "warn-text"}`}>
            {health?.llm_available ? "available" : "off"}
          </div>
        </div>
        <div className="readiness-item">
          <div className="k">Embedding</div>
          <div className="v">{health?.embedding?.mode || "—"}</div>
        </div>
      </div>

      <div className="grid-2" style={{ marginTop: 16 }}>
        <section className="panel">
          <h2>Usage metering</h2>
          {usage ? (
            <div className="kvs">
              <span className="k">tenant</span>
              <span className="v mono">{usage.tenant_id}</span>
              <span className="k">month</span>
              <span className="v mono">{usage.month}</span>
              {Object.entries(usage.metrics || {}).map(([k, v]) => (
                <div key={k} style={{ display: "contents" }}>
                  <span className="k">{k}</span>
                  <span className="v mono">{v}</span>
                </div>
              ))}
            </div>
          ) : (
            <div className="empty">No usage rows yet — contacts still count from interactions.</div>
          )}
        </section>

        <section className="panel">
          <div className="pilot-head">
            <h2>Pilot metrics</h2>
            {metrics?.ts ? (
              <span className="pilot-asof">{formatSnapshotTs(metrics.ts)}</span>
            ) : null}
          </div>
          {metrics ? (
            <div className="kv-grid">
              {[
                ["Open cases", metrics.cases?.open],
                ["Critical open", metrics.cases?.critical_open],
                ["Pending follow-up", metrics.cases?.pending_followup],
                ["Investigations", metrics.investigations?.open],
                ["Active calls", metrics.interactions_active],
                ["Dead-letters", metrics.alert_dead_letters_pending],
                ["Connector pending", metrics.connector_deliveries_pending],
                ["Case notes", metrics.case_notes_in_window],
                ["Fixes recorded", metrics.fix_loop?.fixes_recorded],
              ]
                .filter(([, v]) => v != null)
                .map(([k, v]) => (
                  <div className="kv-tile" key={k}>
                    <div className="k">{k}</div>
                    <div className="v mono">{String(v)}</div>
                  </div>
                ))}
            </div>
          ) : (
            <div className="empty">No scalar metrics in snapshot.</div>
          )}
        </section>
      </div>
    </div>
  );
}
