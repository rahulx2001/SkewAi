import { useEffect, useState } from "react";
import { apiHeaders } from "../src/apiAuth.js";
import { formatDetailValue, humanizeKey } from "../src/ui/labels.js";

/**
 * Enterprise ops surface: timeline, root-cause, copilot, risk, graph, memory,
 * scenarios, decision flow. Deterministic warehouse-backed (not generative LLM).
 */
export default function EnterpriseOps() {
  const [tab, setTab] = useState("timeline");
  const [msg, setMsg] = useState(null);
  const [loading, setLoading] = useState(false);

  // Shared interaction id for timeline / decision / root-cause
  const [ixId, setIxId] = useState("");
  const [recentIx, setRecentIx] = useState([]);
  const [timeline, setTimeline] = useState(null);
  const [playStep, setPlayStep] = useState(0);
  const [rootCause, setRootCause] = useState(null);
  const [postmortems, setPostmortems] = useState([]);
  const [decision, setDecision] = useState(null);

  // Copilot
  const [copilotQ, setCopilotQ] = useState("Which customers are most frustrated?");
  const [copilotA, setCopilotA] = useState(null);

  // Risk
  const [risks, setRisks] = useState([]);
  const [riskPersist, setRiskPersist] = useState(false);
  const [riskHistory, setRiskHistory] = useState([]);

  // Graph
  const [graph, setGraph] = useState(null);

  // Memory
  const [memories, setMemories] = useState([]);
  const [memE1, setMemE1] = useState("");
  const [memE2, setMemE2] = useState("");
  const [memE3, setMemE3] = useState("");
  const [memLookup, setMemLookup] = useState(null);

  // Scenarios
  const [scenarios, setScenarios] = useState([]);
  const [scnName, setScnName] = useState("Angry billing path");
  const [scnSteps, setScnSteps] = useState(
    "I have a problem with my account\nThe payment failed twice\nThis is ridiculous I want a human"
  );
  const [scnRun, setScnRun] = useState(null);
  const [scnValid, setScnValid] = useState(null);

  async function loadRecentInteractions() {
    try {
      const r = await fetch(
        "/api/frontline/enterprise/interactions/recent?limit=30",
        { headers: apiHeaders() }
      );
      if (!r.ok) throw new Error(`HTTP ${r.status}`);
      const d = await r.json();
      setRecentIx(d.interactions || []);
    } catch (e) {
      setMsg(String(e));
    }
  }

  async function loadPostmortems() {
    try {
      const r = await fetch("/api/frontline/enterprise/root-cause?limit=20", {
        headers: apiHeaders(),
      });
      if (!r.ok) throw new Error(`HTTP ${r.status}`);
      const d = await r.json();
      setPostmortems(d.postmortems || []);
    } catch (e) {
      setMsg(String(e));
    }
  }

  async function loadRisks() {
    try {
      const q = riskPersist ? "?persist=true" : "";
      const r = await fetch("/api/frontline/enterprise/risk/active" + q, {
        headers: apiHeaders(),
      });
      if (!r.ok) throw new Error(`HTTP ${r.status}`);
      const d = await r.json();
      setRisks(d.risks || []);
    } catch (e) {
      setMsg(String(e));
    }
  }

  async function loadRiskHistory(id) {
    if (!id) return;
    try {
      const r = await fetch(
        `/api/frontline/enterprise/risk/${encodeURIComponent(id)}/history`,
        { headers: apiHeaders() }
      );
      if (!r.ok) throw new Error(`HTTP ${r.status}`);
      const d = await r.json();
      setRiskHistory(d.snapshots || []);
    } catch (e) {
      setMsg(String(e));
      setRiskHistory([]);
    }
  }

  async function loadGraph() {
    try {
      const r = await fetch("/api/frontline/enterprise/graph?limit_cases=30", {
        headers: apiHeaders(),
      });
      if (!r.ok) throw new Error(`HTTP ${r.status}`);
      setGraph(await r.json());
    } catch (e) {
      setMsg(String(e));
    }
  }

  async function loadMemories() {
    try {
      const r = await fetch("/api/frontline/enterprise/memory?limit=40", {
        headers: apiHeaders(),
      });
      if (!r.ok) throw new Error(`HTTP ${r.status}`);
      const d = await r.json();
      setMemories(d.memories || []);
    } catch (e) {
      setMsg(String(e));
    }
  }

  async function loadScenarios() {
    try {
      const r = await fetch("/api/frontline/enterprise/scenarios", {
        headers: apiHeaders(),
      });
      if (!r.ok) throw new Error(`HTTP ${r.status}`);
      const d = await r.json();
      setScenarios(d.scenarios || []);
    } catch (e) {
      setMsg(String(e));
    }
  }

  useEffect(() => {
    if (tab === "timeline" || tab === "root" || tab === "decision") {
      loadRecentInteractions();
    }
    if (tab === "root") loadPostmortems();
    if (tab === "risk") loadRisks();
    if (tab === "graph") loadGraph();
    if (tab === "memory") loadMemories();
    if (tab === "scenarios") loadScenarios();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [tab]);

  async function fetchTimeline() {
    if (!ixId.trim()) return;
    setLoading(true);
    setMsg(null);
    try {
      const r = await fetch(
        `/api/frontline/enterprise/timeline/${encodeURIComponent(ixId.trim())}`,
        { headers: apiHeaders() }
      );
      if (!r.ok) throw new Error(`HTTP ${r.status}: ${await r.text()}`);
      const d = await r.json();
      setTimeline(d);
      setPlayStep(0);
    } catch (e) {
      setMsg(String(e));
      setTimeline(null);
    } finally {
      setLoading(false);
    }
  }

  async function fetchRootOne() {
    if (!ixId.trim()) return;
    setLoading(true);
    try {
      const r = await fetch(
        `/api/frontline/enterprise/root-cause/${encodeURIComponent(ixId.trim())}`,
        { headers: apiHeaders() }
      );
      if (!r.ok) throw new Error(`HTTP ${r.status}`);
      setRootCause(await r.json());
    } catch (e) {
      setMsg(String(e));
    } finally {
      setLoading(false);
    }
  }

  async function fetchDecision() {
    if (!ixId.trim()) return;
    setLoading(true);
    try {
      const r = await fetch(
        `/api/frontline/enterprise/decision-flow/${encodeURIComponent(ixId.trim())}`,
        { headers: apiHeaders() }
      );
      if (!r.ok) throw new Error(`HTTP ${r.status}`);
      setDecision(await r.json());
    } catch (e) {
      setMsg(String(e));
    } finally {
      setLoading(false);
    }
  }

  async function askCopilot() {
    setLoading(true);
    setMsg(null);
    try {
      const r = await fetch("/api/frontline/enterprise/copilot", {
        method: "POST",
        headers: { ...apiHeaders(), "Content-Type": "application/json" },
        body: JSON.stringify({ query: copilotQ }),
      });
      if (!r.ok) throw new Error(`HTTP ${r.status}`);
      setCopilotA(await r.json());
    } catch (e) {
      setMsg(String(e));
    } finally {
      setLoading(false);
    }
  }

  async function lookupMem() {
    setLoading(true);
    try {
      const p = new URLSearchParams({
        pack_id: "automotive_nhtsa",
        entity_1: memE1,
        entity_2: memE2,
        entity_3: memE3,
      });
      const r = await fetch(`/api/frontline/enterprise/memory/lookup?${p}`, {
        headers: apiHeaders(),
      });
      if (!r.ok) throw new Error(`HTTP ${r.status}`);
      setMemLookup(await r.json());
    } catch (e) {
      setMsg(String(e));
    } finally {
      setLoading(false);
    }
  }

  function parseScenarioSteps() {
    return scnSteps
      .split("\n")
      .map((t) => t.trim())
      .filter(Boolean)
      .map((text) => ({ speaker: "customer", text }));
  }

  async function validateScenario() {
    setLoading(true);
    setScnValid(null);
    setMsg(null);
    try {
      const r = await fetch("/api/frontline/enterprise/scenarios/validate", {
        method: "POST",
        headers: { ...apiHeaders(), "Content-Type": "application/json" },
        body: JSON.stringify({
          pack_id: "automotive_nhtsa",
          name: scnName,
          steps: parseScenarioSteps(),
        }),
      });
      if (!r.ok) throw new Error(`HTTP ${r.status}: ${await r.text()}`);
      const d = await r.json();
      setScnValid(d);
      setMsg(d.ok ? "Scenario valid." : "Scenario has errors.");
    } catch (e) {
      setMsg(String(e));
    } finally {
      setLoading(false);
    }
  }

  async function createScenario() {
    setLoading(true);
    setMsg(null);
    try {
      const steps = parseScenarioSteps();
      const r = await fetch("/api/frontline/enterprise/scenarios", {
        method: "POST",
        headers: { ...apiHeaders(), "Content-Type": "application/json" },
        body: JSON.stringify({
          pack_id: "automotive_nhtsa",
          name: scnName,
          steps,
          description: "Built from Enterprise Ops UI",
        }),
      });
      if (!r.ok) throw new Error(`HTTP ${r.status}: ${await r.text()}`);
      await loadScenarios();
      setMsg("Scenario saved.");
      setScnValid(null);
    } catch (e) {
      setMsg(String(e));
    } finally {
      setLoading(false);
    }
  }

  async function runScenario(id) {
    setLoading(true);
    setScnRun(null);
    try {
      const r = await fetch(
        `/api/frontline/enterprise/scenarios/${encodeURIComponent(id)}/run`,
        { method: "POST", headers: apiHeaders() }
      );
      if (!r.ok) throw new Error(`HTTP ${r.status}: ${await r.text()}`);
      setScnRun(await r.json());
    } catch (e) {
      setMsg(String(e));
    } finally {
      setLoading(false);
    }
  }

  const tabs = [
    { id: "timeline", label: "Timeline" },
    { id: "root", label: "Root cause" },
    { id: "copilot", label: "Copilot" },
    { id: "risk", label: "Live risk" },
    { id: "graph", label: "Graph" },
    { id: "memory", label: "Memory" },
    { id: "scenarios", label: "Scenarios" },
    { id: "decision", label: "Decision flow" },
  ];

  const events = timeline?.events || [];
  const current = events[playStep];

  return (
    <div>
      <header className="page-header">
        <div>
          <h1>Enterprise ops</h1>
          <p className="sub">
            Timeline, root cause, risk, memory, and scenarios from the warehouse — not a CRM.
          </p>
        </div>
      </header>

      {msg && (
        <div className="banner banner-ok" role="status">
          {msg}{" "}
          <button type="button" className="ghost" onClick={() => setMsg(null)}>
            Dismiss
          </button>
        </div>
      )}

      <div className="tabs" role="tablist" aria-label="Enterprise ops">
        {tabs.map((t) => (
          <button
            key={t.id}
            type="button"
            role="tab"
            aria-selected={tab === t.id}
            className={"tab" + (tab === t.id ? " active" : "")}
            onClick={() => setTab(t.id)}
          >
            {t.label}
          </button>
        ))}
      </div>

      {(tab === "timeline" || tab === "root" || tab === "decision") && (
        <div className="panel" style={{ marginBottom: 12 }}>
          <div className="row" style={{ gap: 8, flexWrap: "wrap" }}>
            <select
              value={ixId}
              onChange={(e) => setIxId(e.target.value)}
              style={{ flex: 1, minWidth: 220 }}
              title="Recent interactions"
              aria-label="Recent interactions"
            >
              <option value="">— pick recent interaction —</option>
              {recentIx.map((x) => (
                <option key={x.interaction_id} value={x.interaction_id}>
                  {x.interaction_id} · {x.status}
                  {x.peak_frustration != null
                    ? ` · fr=${Number(x.peak_frustration).toFixed(2)}`
                    : ""}
                </option>
              ))}
            </select>
            <input
              value={ixId}
              onChange={(e) => setIxId(e.target.value)}
              placeholder="or paste interaction_id (int_…)"
              aria-label="Interaction id"
              style={{ flex: 1, minWidth: 180 }}
            />
            <button className="ghost" onClick={loadRecentInteractions} disabled={loading}>
              ⟳
            </button>
            {tab === "timeline" && (
              <button className="primary" onClick={fetchTimeline} disabled={loading}>
                Load timeline
              </button>
            )}
            {tab === "root" && (
              <button className="primary" onClick={fetchRootOne} disabled={loading}>
                Analyze
              </button>
            )}
            {tab === "decision" && (
              <button className="primary" onClick={fetchDecision} disabled={loading}>
                Build flow
              </button>
            )}
          </div>
          {recentIx.length === 0 && (
            <p className="muted" style={{ fontSize: 12, marginTop: 8 }}>
              No interactions yet. Pick a recent contact after a voice call, or simulate traffic first.
            </p>
          )}
        </div>
      )}

      {tab === "timeline" && (
        <div className="panel">
          <h2>Incident timeline replay</h2>
          {!timeline && (
            <div className="empty">
              Pick a recent contact or paste an interaction id, then Load timeline.
            </div>
          )}
          {timeline && (
            <>
              <div className="row" style={{ gap: 8, marginBottom: 12, alignItems: "center" }}>
                <button
                  className="ghost"
                  disabled={playStep <= 0}
                  onClick={() => setPlayStep((s) => Math.max(0, s - 1))}
                >
                  ◀ Prev
                </button>
                <span className="mono muted">
                  Step {playStep}/{Math.max(0, events.length - 1)} · {timeline.event_count} events
                </span>
                <button
                  className="ghost"
                  disabled={playStep >= events.length - 1}
                  onClick={() => setPlayStep((s) => Math.min(events.length - 1, s + 1))}
                >
                  Next ▶
                </button>
              </div>
              {current && (
                <div className="panel" style={{ marginBottom: 12 }}>
                  <div className="chip">{current.kind}</div>{" "}
                  <strong>{current.label}</strong>
                  <div className="muted mono" style={{ fontSize: 11, marginTop: 4 }}>
                    {current.ts} · {current.agent}
                  </div>
                  {current.detail && typeof current.detail === "object" ? (
                    <div className="kvs" style={{ marginTop: 8 }}>
                      {Object.entries(current.detail)
                        .slice(0, 12)
                        .map(([k, v]) => (
                          <div key={k} style={{ display: "contents" }}>
                            <span className="k">{humanizeKey(k)}</span>
                            <span className="v mono">{formatDetailValue(v)}</span>
                          </div>
                        ))}
                    </div>
                  ) : current.detail ? (
                    <p className="muted" style={{ marginTop: 8 }}>{String(current.detail)}</p>
                  ) : null}
                </div>
              )}
              <div style={{ maxHeight: 280, overflow: "auto" }}>
                {events.map((e) => (
                  <div
                    key={e.step}
                    onClick={() => setPlayStep(e.step)}
                    style={{
                      padding: "6px 8px",
                      cursor: "pointer",
                      background: e.step === playStep ? "var(--bg-hover)" : "transparent",
                      borderLeft:
                        e.step === playStep
                          ? "3px solid var(--accent)"
                          : "3px solid transparent",
                      fontSize: 12,
                    }}
                  >
                    <span className="mono muted">{e.step}</span> {e.kind}: {e.label}
                  </div>
                ))}
              </div>
            </>
          )}
        </div>
      )}

      {tab === "root" && (
        <>
          {rootCause && (
            <div className="panel" style={{ marginBottom: 12 }}>
              <h2>Post-mortem: {rootCause.interaction_id}</h2>
              <div className="kvs">
                <span className="k">primary</span>
                <span className="v mono">{rootCause.primary_cause}</span>
                <span className="k">blame</span>
                <span className="v">{rootCause.blame_agent}</span>
                <span className="k">confidence</span>
                <span className="v mono">{rootCause.confidence}</span>
                <span className="k">fix</span>
                <span className="v">{rootCause.suggested_fix}</span>
              </div>
            </div>
          )}
          <div className="panel">
            <h2>Recent failure post-mortems</h2>
            {postmortems.length === 0 && <div className="empty">No failure-like contacts yet.</div>}
            {postmortems.length > 0 && (
              <table>
                <thead>
                  <tr>
                    <th>interaction</th>
                    <th>cause</th>
                    <th>agent</th>
                    <th>conf</th>
                    <th>status</th>
                  </tr>
                </thead>
                <tbody>
                  {postmortems.map((p) => (
                    <tr
                      key={p.interaction_id}
                      style={{ cursor: "pointer" }}
                      onClick={() => {
                        setIxId(p.interaction_id);
                        setRootCause(null);
                      }}
                    >
                      <td className="mono" style={{ fontSize: 11 }}>{p.interaction_id}</td>
                      <td>{p.primary_cause}</td>
                      <td>{p.blame_agent}</td>
                      <td className="mono">{p.confidence}</td>
                      <td>{p.status}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            )}
          </div>
        </>
      )}

      {tab === "copilot" && (
        <div className="panel">
          <h2>Supervisor copilot</h2>
          <p className="muted" style={{ fontSize: 12 }}>
            Intent-routed SQL over the ops warehouse. Not a generative model.
          </p>
          <div className="row" style={{ gap: 6, flexWrap: "wrap", marginBottom: 10 }}>
            {(
              copilotA?.suggestions || [
                "Which customers are most frustrated?",
                "Show open critical cases",
                "Show high risk contacts",
                "Show pending connector deliveries",
              ]
            )
              .slice(0, 8)
              .map((s) => (
                <button
                  key={s}
                  className="ghost"
                  style={{ fontSize: 11 }}
                  onClick={() => {
                    setCopilotQ(s);
                  }}
                >
                  {s}
                </button>
              ))}
          </div>
          <div className="row" style={{ gap: 8, marginBottom: 12 }}>
            <input
              value={copilotQ}
              onChange={(e) => setCopilotQ(e.target.value)}
              style={{ flex: 1 }}
              aria-label="Copilot question"
              onKeyDown={(e) => e.key === "Enter" && askCopilot()}
            />
            <button className="primary" onClick={askCopilot} disabled={loading}>
              Ask
            </button>
          </div>
          {copilotA && (
            <>
              <div className="chip teal">{copilotA.intent}</div>
              <p>{copilotA.answer}</p>
              {copilotA.rows?.length > 0 && (
                <table>
                  <thead>
                    <tr>
                      {Object.keys(copilotA.rows[0]).slice(0, 6).map((k) => (
                        <th key={k}>{k}</th>
                      ))}
                    </tr>
                  </thead>
                  <tbody>
                    {copilotA.rows.map((row, i) => (
                      <tr key={row.case_id || row.interaction_id || JSON.stringify(row) + i}>
                        {Object.keys(copilotA.rows[0])
                          .slice(0, 6)
                          .map((k) => (
                            <td key={k} className="mono" style={{ fontSize: 11 }}>
                              {String(row[k] ?? "—")}
                            </td>
                          ))}
                      </tr>
                    ))}
                  </tbody>
                </table>
              )}
            </>
          )}
        </div>
      )}

      {tab === "risk" && (
        <div className="panel">
          <div className="row" style={{ justifyContent: "space-between", marginBottom: 8, flexWrap: "wrap", gap: 8 }}>
            <h2 style={{ margin: 0 }}>Active contact risk scores</h2>
            <div className="row" style={{ gap: 8, alignItems: "center" }}>
              <label className="check-row muted" style={{ fontSize: 12 }}>
                <input
                  type="checkbox"
                  checked={riskPersist}
                  onChange={(e) => setRiskPersist(e.target.checked)}
                />
                persist snapshots
              </label>
              <button className="ghost" onClick={loadRisks}>⟳</button>
            </div>
          </div>
          {risks.length === 0 && (
            <div className="empty">No active contacts (or none scored).</div>
          )}
          {risks.length > 0 && (
            <table>
              <thead>
                <tr>
                  <th>interaction</th>
                  <th>level</th>
                  <th>escalation</th>
                  <th>churn</th>
                  <th>sentiment</th>
                  <th>ETA turns</th>
                  <th></th>
                </tr>
              </thead>
              <tbody>
                {risks.map((r) => (
                  <tr key={r.interaction_id}>
                    <td className="mono" style={{ fontSize: 11 }}>{r.interaction_id}</td>
                    <td>
                      <span
                        className={
                          "chip " +
                          (r.risk_level === "critical"
                            ? "red"
                            : r.risk_level === "high"
                              ? "orange"
                              : "blue")
                        }
                      >
                        {r.risk_level}
                      </span>
                    </td>
                    <td className="mono">{r.escalation_prob}</td>
                    <td className="mono">{r.churn_prob}</td>
                    <td className="mono">{r.sentiment_trend}</td>
                    <td className="mono">{r.est_resolution_turns}</td>
                    <td>
                      <button
                        className="ghost"
                        style={{ fontSize: 11 }}
                        onClick={() => {
                          setIxId(r.interaction_id);
                          loadRiskHistory(r.interaction_id);
                        }}
                      >
                        history
                      </button>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
          {riskHistory.length > 0 && (
            <div style={{ marginTop: 16 }}>
              <h3 style={{ fontSize: 13 }}>Risk history · {ixId || riskHistory[0]?.interaction_id}</h3>
              <table>
                <thead>
                  <tr>
                    <th>ts</th>
                    <th>esc</th>
                    <th>churn</th>
                    <th>sentiment</th>
                    <th>ETA</th>
                  </tr>
                </thead>
                <tbody>
                  {riskHistory.map((s) => (
                    <tr key={s.snapshot_id}>
                      <td className="mono" style={{ fontSize: 11 }}>{s.ts}</td>
                      <td className="mono">{s.escalation_prob}</td>
                      <td className="mono">{s.churn_prob}</td>
                      <td className="mono">{s.sentiment_trend}</td>
                      <td className="mono">{s.est_resolution_turns}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </div>
      )}

      {tab === "graph" && (
        <div className="panel">
          <div className="row" style={{ justifyContent: "space-between", marginBottom: 8 }}>
            <h2 style={{ margin: 0 }}>Ops knowledge graph</h2>
            <button className="ghost" onClick={loadGraph}>⟳</button>
          </div>
          {!graph && <div className="empty">loading…</div>}
          {graph && (
            <>
              <div className="row" style={{ gap: 10, marginBottom: 12 }}>
                <span className="chip">nodes: {graph.node_count}</span>
                <span className="chip">edges: {graph.edge_count}</span>
              </div>
              <h3 style={{ fontSize: 13 }}>Nodes (sample)</h3>
              <div style={{ maxHeight: 200, overflow: "auto", marginBottom: 12 }}>
                {(graph.nodes || []).slice(0, 40).map((n) => (
                  <div key={n.id} style={{ fontSize: 12, padding: "2px 0" }}>
                    <span className="chip" style={{ fontSize: 10 }}>{n.type}</span>{" "}
                    {n.label}
                  </div>
                ))}
              </div>
              <h3 style={{ fontSize: 13 }}>Edges (sample)</h3>
              <div style={{ maxHeight: 200, overflow: "auto" }}>
                {(graph.edges || []).slice(0, 50).map((e, i) => (
                  <div key={`${e.source}-${e.rel}-${e.target}-${i}`} className="mono" style={{ fontSize: 11 }}>
                    {e.source} —{e.rel}→ {e.target}
                  </div>
                ))}
              </div>
            </>
          )}
        </div>
      )}

      {tab === "memory" && (
        <div className="panel">
          <h2>Cross-contact entity memory</h2>
          <div className="row" style={{ gap: 8, marginBottom: 12, flexWrap: "wrap" }}>
            <input placeholder="entity_1" aria-label="entity_1" value={memE1} onChange={(e) => setMemE1(e.target.value)} />
            <input placeholder="entity_2" aria-label="entity_2" value={memE2} onChange={(e) => setMemE2(e.target.value)} />
            <input placeholder="entity_3" aria-label="entity_3" value={memE3} onChange={(e) => setMemE3(e.target.value)} />
            <button className="primary" onClick={lookupMem}>Lookup memory</button>
            <button className="ghost" onClick={loadMemories}>List</button>
          </div>
          {memLookup && (
            <div className="result-card" style={{ marginBottom: 12 }}>
              <div className="result-card-title">Lookup result</div>
              <div className="kvs">
                {Object.entries(memLookup)
                  .filter(([, v]) => v !== null && typeof v !== "object")
                  .map(([k, v]) => (
                    <div key={k} style={{ display: "contents" }}>
                      <span className="k">{k}</span>
                      <span className="v mono">{String(v)}</span>
                    </div>
                  ))}
              </div>
            </div>
          )}
          {memories.length > 0 && (
            <table>
              <thead>
                <tr>
                  <th>entities</th>
                  <th>count</th>
                  <th>last case</th>
                  <th>severity</th>
                  <th>last seen</th>
                </tr>
              </thead>
              <tbody>
                {memories.map((m) => (
                  <tr key={m.memory_id}>
                    <td className="mono" style={{ fontSize: 11 }}>
                      {[m.entity_1, m.entity_2, m.entity_3].filter(Boolean).join(" / ")}
                    </td>
                    <td className="mono">{m.interaction_count}</td>
                    <td className="mono" style={{ fontSize: 11 }}>{m.last_case_id || "—"}</td>
                    <td>{m.last_severity || "—"}</td>
                    <td className="mono" style={{ fontSize: 11 }}>{m.last_seen_at}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
        </div>
      )}

      {tab === "scenarios" && (
        <div className="panel">
          <h2>Scenario playbook builder</h2>
          <div className="field" style={{ marginBottom: 8 }}>
            <label>name</label>
            <input value={scnName} onChange={(e) => setScnName(e.target.value)} style={{ width: "100%" }} />
          </div>
          <div className="field" style={{ marginBottom: 8 }}>
            <label>customer steps (one line each)</label>
            <textarea
              value={scnSteps}
              onChange={(e) => setScnSteps(e.target.value)}
              style={{ width: "100%", minHeight: 100 }}
            />
          </div>
          <div className="row" style={{ gap: 8, marginTop: 8 }}>
            <button className="ghost" onClick={validateScenario} disabled={loading}>
              Validate
            </button>
            <button className="primary" onClick={createScenario} disabled={loading}>
              Save scenario
            </button>
          </div>
          {scnValid && (
            <div className="result-card" style={{ marginTop: 10 }}>
              <div className="result-card-title">
                {scnValid.ok ? <span className="ok-text">Valid</span> : <span className="err-text">Invalid</span>}
              </div>
              <div className="kvs">
                {Object.entries(scnValid)
                  .filter(([, v]) => typeof v !== "object")
                  .map(([k, v]) => (
                    <div key={k} style={{ display: "contents" }}>
                      <span className="k">{k}</span>
                      <span className="v mono">{String(v)}</span>
                    </div>
                  ))}
              </div>
              {Array.isArray(scnValid.errors) && scnValid.errors.length > 0 && (
                <ul className="plain" style={{ marginTop: 8 }}>
                  {scnValid.errors.map((e, i) => (
                    <li key={`${e}-${i}`} className="err-text">{String(e)}</li>
                  ))}
                </ul>
              )}
            </div>
          )}
          <div style={{ marginTop: 16 }}>
            {scenarios.map((s) => (
              <div key={s.scenario_id} className="row" style={{ gap: 8, marginBottom: 8, alignItems: "center" }}>
                <span className="mono" style={{ fontSize: 11, flex: 1 }}>
                  {s.name} · {s.step_count} steps · {s.scenario_id}
                </span>
                <button className="primary" onClick={() => runScenario(s.scenario_id)} disabled={loading}>
                  Run scenario
                </button>
              </div>
            ))}
          </div>
          {scnRun && (
            <div className="result-card" style={{ marginTop: 12 }}>
              <div className="result-card-title">Run result</div>
              <div className="kvs">
                {Object.entries(scnRun)
                  .filter(([, v]) => v !== null && typeof v !== "object")
                  .map(([k, v]) => (
                    <div key={k} style={{ display: "contents" }}>
                      <span className="k">{k}</span>
                      <span className="v mono">{String(v)}</span>
                    </div>
                  ))}
              </div>
            </div>
          )}
        </div>
      )}

      {tab === "decision" && (
        <div className="panel">
          <h2>Decision flow</h2>
          {!decision && <div className="empty">Load an interaction to see agent pipeline graph.</div>}
          {decision && (
            <>
              <div className="row" style={{ gap: 8, marginBottom: 12 }}>
                <span className="chip">actions: {decision.action_count}</span>
                <span className="chip teal">
                  agents: {(decision.agents_in_order || []).join(" → ")}
                </span>
              </div>
              <h3 style={{ fontSize: 13 }}>Agent order</h3>
              <div className="row" style={{ gap: 6, flexWrap: "wrap", marginBottom: 12 }}>
                {(decision.agents_in_order || []).map((a) => (
                  <span className="chip purple" key={a}>{a}</span>
                ))}
              </div>
              <h3 style={{ fontSize: 13 }}>Edges (sample)</h3>
              <div style={{ maxHeight: 280, overflow: "auto" }}>
                {(decision.edges || []).filter((e) => e.rel === "then" || e.rel === "pipeline").slice(0, 40).map((e, i) => (
                  <div key={i} className="mono" style={{ fontSize: 11 }}>
                    {e.source} —{e.rel}→ {e.target}
                  </div>
                ))}
              </div>
            </>
          )}
        </div>
      )}
    </div>
  );
}
