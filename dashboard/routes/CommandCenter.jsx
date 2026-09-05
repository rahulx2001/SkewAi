import { useCallback, useEffect, useState } from "react";
import { apiHeaders } from "../src/apiAuth.js";
import {
  fetchOpenP1Cases,
  openCases,
  openConsole,
  simulateTraffic,
} from "../src/ui/opsActions.js";
import { dayGreeting } from "../src/ui/greeting.js";
import { formatSnapshotTs } from "../src/ui/formatTime.js";

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
        fetch("/api/frontline/wallboard", { headers: h }),
        fetch("/api/frontline/metrics", { headers: h }),
        fetch("/api/frontline/usage", { headers: h }),
        fetch("/api/frontline/ops/drain", { headers: h }),
        fetchOpenP1Cases(8),
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

  const live = wall?.live_contacts || wall?.active_contacts || [];
  const clusters = wall?.top_clusters || [];
  const liveCount = wall?.active_count ?? wall?.live_count ?? live.length ?? 0;
  const p1 = wall?.p1_count ?? wall?.p1 ?? 0;
  const openCases = wall?.open_cases ?? 0;
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
          <button type="button" onClick={runSimulate} disabled={simBusy}>
            {simBusy ? "Simulating…" : "Simulate 15"}
          </button>
          <button
            type="button"
            className="primary"
            onClick={() => {
              window.location.hash = "call";
            }}
          >
            Open voice agent
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

      <div className="stat-grid" style={{ marginBottom: 16 }}>
        <div className="stat-card">
          <div className="label">Live contacts</div>
          <div className="value">{liveCount}</div>
          <div className="hint">status = active right now</div>
        </div>
        <button
          type="button"
          className={`stat-card ${Number(p1) > 0 ? "danger" : ""} stat-card-btn`}
          onClick={() => openCases({ severity: "Critical", status: "open" })}
          title="Open Critical case queue"
        >
          <div className="label">P1 / Critical open</div>
          <div className="value">{p1}</div>
          <div className="hint">click → case queue filtered</div>
        </button>
        <div className="stat-card">
          <div className="label">Open cases</div>
          <div className="value">{openCases}</div>
          <div className="hint">open + pending follow-up</div>
        </div>
        <div className={`stat-card ${draining ? "danger" : "ok"}`}>
          <div className="label">Deploy drain</div>
          <div className="value" style={{ fontSize: 24, letterSpacing: "-0.04em" }}>
            {draining ? "Draining" : "Ready"}
          </div>
          <div className="hint">
            active slots: {drain?.active_count ?? 0}
            {drain?.ready_to_exit ? " · ready to exit" : ""}
          </div>
        </div>
      </div>

      <div className="jump-grid" aria-label="Quick jumps">
        <button type="button" className="jump-tile" onClick={() => (window.location.hash = "call")}>
          <span className="jt-kicker">Operate</span>
          <span className="jt-title">Voice agent</span>
          <span className="jt-hint">Start a browser contact with STT / TTS</span>
        </button>
        <button type="button" className="jump-tile" onClick={() => (window.location.hash = "console")}>
          <span className="jt-kicker">Operate</span>
          <span className="jt-title">Live console</span>
          <span className="jt-hint">Watch frustration · take over mid-call</span>
        </button>
        <button type="button" className="jump-tile" onClick={() => (window.location.hash = "cases")}>
          <span className="jt-kicker">Queue</span>
          <span className="jt-title">Case queue</span>
          <span className="jt-hint">Filter by severity · export CSV</span>
        </button>
        <button type="button" className="jump-tile" onClick={() => (window.location.hash = "warning")}>
          <span className="jt-kicker">Risk</span>
          <span className="jt-title">Early warning</span>
          <span className="jt-hint">Clusters, funnel, simulate traffic</span>
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
                No active contacts. Start one from Voice agent — or open Live console when a
                supervisor needs to take over.
              </p>
              <div className="row" style={{ marginTop: 12 }}>
                <button type="button" className="primary" onClick={() => (window.location.hash = "call")}>
                  Start a contact
                </button>
                <button type="button" className="ghost" onClick={() => (window.location.hash = "console")}>
                  Open live console
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
                  <div className="chan">{row.channel || "open →"}</div>
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
                <div className="risk-row" key={`${c.pack_id}-${c.cluster_id}`}>
                  <div className="risk-rank">#{String(i + 1).padStart(2, "0")}</div>
                  <div className="risk-main">
                    <div className="title">
                      Cluster {c.cluster_id}{" "}
                      <span className={`sev ${(c.max_severity || "").toLowerCase()}`}>
                        {c.max_severity || "—"}
                      </span>
                    </div>
                    <div className="hint mono">{c.pack_id}</div>
                  </div>
                  <div className="risk-count" title="Open cases">
                    {c.open_cases}
                  </div>
                </div>
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
              <button type="button" className="primary" onClick={runSimulate} disabled={simBusy}>
                {simBusy ? "Simulating…" : "Simulate 15 contacts"}
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
                  <th>Priority</th>
                  <th>Status</th>
                  <th />
                </tr>
              </thead>
              <tbody>
                {p1Cases.map((c) => (
                  <tr key={c.case_id}>
                    <td className="mono">{c.case_id}</td>
                    <td>{c.category || "—"}</td>
                    <td className="mono">P{c.priority ?? "—"}</td>
                    <td>{c.status}</td>
                    <td>
                      <button
                        type="button"
                        className="ghost"
                        onClick={() =>
                          openCases({
                            severity: "Critical",
                            status: "open",
                            caseId: c.case_id,
                          })
                        }
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
              {Object.entries(metrics)
                .filter(([k, v]) => k !== "ts" && v !== null && typeof v !== "object")
                .slice(0, 12)
                .map(([k, v]) => (
                  <div className="kv-tile" key={k}>
                    <div className="k">{k.replace(/_/g, " ")}</div>
                    <div className="v mono">{String(v)}</div>
                  </div>
                ))}
            </div>
          ) : (
            <div className="empty">No scalar metrics in snapshot.</div>
          )}
          {metrics && Object.keys(metrics).length === 0 && (
            <div className="empty">No scalar metrics in snapshot.</div>
          )}
        </section>
      </div>
    </div>
  );
}
