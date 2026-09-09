import { useEffect, useState } from "react";
import { apiHeaders } from "../src/apiAuth.js";
import { hashQueryObject, patchHashQuery } from "../src/ui/opsActions.js";
import { bannerTone } from "../src/ui/Feedback.jsx";
import {
  displayCopy,
  proposalDetailParts,
  proposalTitle,
  statusLabel,
  weaknessLabel,
} from "../src/ui/labels.js";

/**
 * Skew AI v3 OS foundation UI:
 * continuous learning, experiments, governance.
 * Deterministic / offline-honest — not multi-provider LLM SaaS.
 */
export default function PlatformOS({ embedded }) {
  const tabFromHash = hashQueryObject().view;
  const tab = ["learning", "experiments", "governance"].includes(tabFromHash) ? tabFromHash : "learning";
  const [msg, setMsg] = useState(null);
  const [loading, setLoading] = useState(false);

  const [proposals, setProposals] = useState([]);
  const [trends, setTrends] = useState(null);

  const [artifacts, setArtifacts] = useState([]);
  const [experiments, setExperiments] = useState([]);
  const [expReport, setExpReport] = useState(null);

  const [deployments, setDeployments] = useState([]);
  const [activeDep, setActiveDep] = useState(null);
  const [stampId, setStampId] = useState("");
  const [stamp, setStamp] = useState(null);

  async function loadLearning() {
    try {
      const [p, t] = await Promise.all([
        fetch("/api/v3/learning/proposals?limit=50", { headers: apiHeaders() }),
        fetch("/api/v3/learning/trends?window_days=30", { headers: apiHeaders() }),
      ]);
      if (!p.ok) throw new Error(`proposals HTTP ${p.status}`);
      if (!t.ok) throw new Error(`trends HTTP ${t.status}`);
      setProposals((await p.json()).proposals || []);
      setTrends(await t.json());
    } catch (e) {
      setMsg(String(e));
    }
  }

  async function runLearning() {
    setLoading(true);
    setMsg(null);
    try {
      const r = await fetch("/api/v3/learning/run?limit=25", {
        method: "POST",
        headers: apiHeaders(),
      });
      if (!r.ok) throw new Error(`HTTP ${r.status}: ${await r.text()}`);
      const d = await r.json();
      setMsg(`Learning scan: created ${d.created}, skipped ${d.skipped}`);
      await loadLearning();
    } catch (e) {
      setMsg(String(e));
    } finally {
      setLoading(false);
    }
  }

  async function reviewProposal(id, status) {
    setLoading(true);
    try {
      const r = await fetch(`/api/v3/learning/proposals/${encodeURIComponent(id)}/review`, {
        method: "POST",
        headers: { ...apiHeaders(), "Content-Type": "application/json" },
        body: JSON.stringify({ status, reviewed_by: "operator" }),
      });
      if (!r.ok) throw new Error(`HTTP ${r.status}: ${await r.text()}`);
      await loadLearning();
    } catch (e) {
      setMsg(String(e));
    } finally {
      setLoading(false);
    }
  }

  async function loadExperiments() {
    try {
      const [a, e] = await Promise.all([
        fetch("/api/v3/artifacts?limit=50", { headers: apiHeaders() }),
        fetch("/api/v3/experiments?limit=50", { headers: apiHeaders() }),
      ]);
      if (!a.ok || !e.ok) throw new Error("failed to load experiments");
      setArtifacts((await a.json()).artifacts || []);
      setExperiments((await e.json()).experiments || []);
    } catch (err) {
      setMsg(String(err));
    }
  }

  async function loadGovernance() {
    try {
      const r = await fetch("/api/v3/governance/deployments", { headers: apiHeaders() });
      if (!r.ok) throw new Error(`HTTP ${r.status}`);
      const d = await r.json();
      setDeployments(d.deployments || []);
      setActiveDep(d.active || null);
    } catch (e) {
      setMsg(String(e));
    }
  }

  async function createAndActivate() {
    setLoading(true);
    try {
      const r = await fetch("/api/v3/governance/deployments", {
        method: "POST",
        headers: { ...apiHeaders(), "Content-Type": "application/json" },
        body: JSON.stringify({
          label: `deploy-${new Date().toISOString().slice(0, 16)}`,
          artifact_versions: { "prompt/intake_greeting": "1.0.0" },
          note: "Pilot OS UI",
        }),
      });
      if (!r.ok) throw new Error(await r.text());
      const dep = await r.json();
      const a = await fetch(
        `/api/v3/governance/deployments/${encodeURIComponent(dep.deployment_id)}/activate`,
        { method: "POST", headers: { ...apiHeaders(), "Content-Type": "application/json" }, body: "{}" }
      );
      if (!a.ok) throw new Error(await a.text());
      setMsg(`Activated ${dep.deployment_id}`);
      await loadGovernance();
    } catch (e) {
      setMsg(String(e));
    } finally {
      setLoading(false);
    }
  }

  async function doRollback() {
    setLoading(true);
    try {
      const r = await fetch("/api/v3/governance/rollback", {
        method: "POST",
        headers: { ...apiHeaders(), "Content-Type": "application/json" },
        body: "{}",
      });
      if (!r.ok) throw new Error(await r.text());
      setMsg("Rollback complete.");
      await loadGovernance();
    } catch (e) {
      setMsg(String(e));
    } finally {
      setLoading(false);
    }
  }

  async function completeExperiment(id) {
    setLoading(true);
    setMsg(null);
    try {
      const r = await fetch(`/api/v3/experiments/${encodeURIComponent(id)}/complete`, {
        method: "POST",
        headers: apiHeaders(),
      });
      if (!r.ok) throw new Error(`HTTP ${r.status}: ${await r.text()}`);
      setExpReport(await r.json());
      await loadExperiments();
      setMsg("Experiment completed.");
    } catch (e) {
      setMsg(String(e));
    } finally {
      setLoading(false);
    }
  }

  async function loadStamp() {
    if (!stampId.trim()) {
      setMsg("Paste an interaction id");
      return;
    }
    setLoading(true);
    try {
      const r = await fetch(
        `/api/v3/governance/stamps/${encodeURIComponent(stampId.trim())}`,
        { headers: apiHeaders() }
      );
      if (!r.ok) throw new Error(`HTTP ${r.status}`);
      setStamp(await r.json());
    } catch (e) {
      setMsg(String(e));
      setStamp(null);
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => {
    if (tab === "learning") loadLearning();
    if (tab === "experiments") loadExperiments();
    if (tab === "governance") loadGovernance();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [tab]);

  const tabs = [
    { id: "learning", label: "Learning" },
    { id: "experiments", label: "Experiments" },
    { id: "governance", label: "Governance" },
  ];

  return (
    <div>
      {!embedded && (
        <header className="page-header">
          <div>
            <h1>Platform OS</h1>
            <p className="sub">
              Learning proposals, experiments, and deployment governance — deterministic, offline-honest.
            </p>
          </div>
        </header>
      )}

      {msg && (
        <div
          className={"banner " + (bannerTone(msg) === "error" ? "banner-error" : "banner-ok")}
          role={bannerTone(msg) === "error" ? "alert" : "status"}
        >
          {msg}{" "}
          <button type="button" className="ghost" onClick={() => setMsg(null)}>
            Dismiss
          </button>
        </div>
      )}

      <div className="tabs" role="tablist" aria-label="Platform OS">
        {tabs.map((t) => (
          <button
            key={t.id}
            type="button"
            role="tab"
            aria-selected={tab === t.id}
            className={"tab" + (tab === t.id ? " active" : "")}
            onClick={() => patchHashQuery({ view: t.id })}
          >
            {t.label}
          </button>
        ))}
      </div>

      {tab === "learning" && (
        <div className="panel">
          <div className="row" style={{ justifyContent: "space-between", marginBottom: 12 }}>
            <h2 style={{ margin: 0 }}>Improvement proposals</h2>
            <button className="primary" onClick={runLearning} disabled={loading}>
              Scan failures
            </button>
          </div>
          {trends && (
            <div className="row" style={{ gap: 10, marginBottom: 14, flexWrap: "wrap" }}>
              <span className="chip">Total: {trends.total}</span>
              {Object.entries(trends.by_status || {}).map(([k, v]) => (
                <span className="chip teal" key={k}>
                  {statusLabel(k)}: {v}
                </span>
              ))}
              {Object.entries(trends.by_weakness_class || {}).slice(0, 6).map(([k, v]) => (
                <span className="chip purple" key={k}>
                  {weaknessLabel(k)}: {v}
                </span>
              ))}
            </div>
          )}
          {proposals.length === 0 && (
            <div className="empty">No proposals yet. Run scan after failed contacts exist.</div>
          )}
          {proposals.map((p) => {
            const detailParts = proposalDetailParts(p);
            return (
            <div key={p.proposal_id} className="panel" style={{ marginBottom: 10 }}>
              <div className="row" style={{ justifyContent: "space-between", gap: 8, alignItems: "flex-start" }}>
                <div>
                  <strong>{proposalTitle(p)}</strong>
                  {p.interaction_id && (
                    <div className="mono muted" style={{ fontSize: 11, marginTop: 2 }}>
                      {p.interaction_id}
                    </div>
                  )}
                </div>
                <span className="chip">{statusLabel(p.status)}</span>
              </div>
              {(detailParts.blame || detailParts.confidence || detailParts.why) ? (
                <div className="row" style={{ gap: 8, flexWrap: "wrap", margin: "8px 0" }}>
                  {detailParts.blame && (
                    <span className="chip">Blame: {detailParts.blame}</span>
                  )}
                  {detailParts.confidence != null && (
                    <span className="chip teal">Confidence: {detailParts.confidence}</span>
                  )}
                  {detailParts.why && (
                    <span className="chip">Why: {detailParts.why}</span>
                  )}
                </div>
              ) : detailParts.raw ? (
                <p className="muted" style={{ fontSize: 12 }}>{detailParts.raw}</p>
              ) : null}
              <p style={{ fontSize: 13 }}><strong>Suggested:</strong> {displayCopy(p.suggested_change)}</p>
              <div className="row" style={{ gap: 8, flexWrap: "wrap", alignItems: "center" }}>
                <span className="muted" style={{ fontSize: 12 }}>
                  Impact {p.impact_score ?? "—"} · {weaknessLabel(p.weakness_class)}
                </span>
                {p.status === "proposed" && (
                  <>
                    <button className="primary" disabled={loading} onClick={() => reviewProposal(p.proposal_id, "approved")}>
                      Approve
                    </button>
                    <button className="danger" disabled={loading} onClick={() => reviewProposal(p.proposal_id, "rejected")}>
                      Reject
                    </button>
                  </>
                )}
                {p.status === "approved" && (
                  <button className="primary" disabled={loading} onClick={() => reviewProposal(p.proposal_id, "deployed")}>
                    Mark deployed
                  </button>
                )}
              </div>
            </div>
            );
          })}
        </div>
      )}

      {tab === "experiments" && (
        <div className="panel">
          <div className="row" style={{ justifyContent: "space-between", marginBottom: 12 }}>
            <h2 style={{ margin: 0 }}>Experiments</h2>
          </div>
          <p className="muted" style={{ fontSize: 12 }}>
            Versioned artifacts (prompt/workflow/routing/safety/retrieval) with offline trial metrics.
            Modes: ab · shadow · canary (labels — no multi-cluster infra).
          </p>
          <h3 style={{ fontSize: 13 }}>Artifacts ({artifacts.length})</h3>
          {artifacts.length === 0 ? (
            <div className="empty" style={{ marginBottom: 12 }}>No artifacts yet.</div>
          ) : (
            <div className="table-wrap" style={{ marginBottom: 12, maxHeight: 160, overflow: "auto" }}>
              <table>
                <thead>
                  <tr>
                    <th>Kind</th>
                    <th>Name</th>
                    <th>Version</th>
                    <th>Id</th>
                  </tr>
                </thead>
                <tbody>
                  {artifacts.map((a) => (
                    <tr key={a.artifact_id}>
                      <td>{a.kind}</td>
                      <td>{a.name}</td>
                      <td className="mono">{a.version}</td>
                      <td className="mono" style={{ fontSize: 11 }}>{a.artifact_id}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
          <h3 style={{ fontSize: 13 }}>Experiments</h3>
          {experiments.length === 0 && (
            <div className="empty" style={{ marginBottom: 12 }}>No experiments yet.</div>
          )}
          {experiments.map((e) => (
            <div key={e.experiment_id} className="panel" style={{ marginBottom: 8 }}>
              <strong>{e.name}</strong>{" "}
              <span className="chip">{e.status}</span>{" "}
              <span className="chip teal">{e.mode}</span>
              <div className="mono muted" style={{ fontSize: 11 }}>{e.experiment_id}</div>
              {e.status !== "completed" && (
                <button
                  type="button"
                  className="primary"
                  style={{ marginTop: 8 }}
                  disabled={loading}
                  onClick={() => completeExperiment(e.experiment_id)}
                >
                  Complete
                </button>
              )}
            </div>
          ))}
          {expReport && (
            <div className="result-card" style={{ marginTop: 12 }}>
              <div className="result-card-title">Experiment report</div>
              <div className="kv-grid">
                {Object.entries(expReport.metrics || expReport)
                  .filter(([, v]) => v !== null && typeof v !== "object")
                  .map(([k, v]) => (
                    <div className="kv-tile" key={k}>
                      <div className="k">{k.replace(/_/g, " ")}</div>
                      <div className="v mono">{String(v)}</div>
                    </div>
                  ))}
              </div>
            </div>
          )}
        </div>
      )}

      {tab === "governance" && (
        <div className="panel">
          <div className="row" style={{ gap: 8, marginBottom: 12, flexWrap: "wrap" }}>
            <h2 style={{ margin: 0, flex: 1 }}>Deployments</h2>
            <button className="primary" onClick={createAndActivate} disabled={loading}>
              Create + activate
            </button>
            <button className="ghost" onClick={doRollback} disabled={loading}>
              Rollback
            </button>
          </div>
          {activeDep && (
            <div className="chip green" style={{ marginBottom: 10 }}>
              Active: {activeDep.label} ({activeDep.deployment_id})
            </div>
          )}
          {deployments.length === 0 ? (
            <div className="empty">No deployments yet.</div>
          ) : (
            <div className="table-wrap" style={{ marginBottom: 12 }}>
              <table>
                <thead>
                  <tr>
                    <th>Status</th>
                    <th>Label</th>
                    <th>Id</th>
                  </tr>
                </thead>
                <tbody>
                  {deployments.map((d) => (
                    <tr key={d.deployment_id}>
                      <td>{statusLabel(d.status)}</td>
                      <td>{d.label}</td>
                      <td className="mono" style={{ fontSize: 11 }}>{d.deployment_id}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
          <div className="h-divider" style={{ margin: "16px 0" }} />
          <h3 style={{ fontSize: 13 }}>Interaction version stamp</h3>
          <div className="row" style={{ gap: 8 }}>
            <input
              value={stampId}
              onChange={(e) => setStampId(e.target.value)}
              placeholder="interaction_id"
              aria-label="Interaction id for version stamp"
              style={{ flex: 1 }}
            />
            <button className="primary" onClick={loadStamp} disabled={loading}>
              Load stamp
            </button>
          </div>
          {stamp && (
            <div className="result-card" style={{ marginTop: 10 }}>
              <div className="result-card-title">Version stamp</div>
              <div className="kvs">
                {Object.entries(stamp)
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
    </div>
  );
}
