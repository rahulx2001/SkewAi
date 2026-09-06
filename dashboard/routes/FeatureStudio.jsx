import { useCallback, useEffect, useState } from "react";
import { apiHeaders } from "../src/apiAuth.js";

const TABS = [
  { id: "analytics", label: "Analytics" },
  { id: "booking", label: "Booking" },
  { id: "callbacks", label: "Callbacks" },
  { id: "approvals", label: "Approvals" },
  { id: "jobs", label: "Jobs" },
  { id: "coach", label: "Coach" },
  { id: "channels", label: "Channels" },
  { id: "marketplace", label: "Packs" },
  { id: "ops", label: "Ops" },
];

async function jget(path) {
  const r = await fetch(path, { headers: apiHeaders() });
  if (!r.ok) throw new Error(`${path} → ${r.status}`);
  return r.json();
}

async function jpost(path, body) {
  const r = await fetch(path, {
    method: "POST",
    headers: { ...apiHeaders(), "Content-Type": "application/json" },
    body: JSON.stringify(body || {}),
  });
  const data = await r.json().catch(() => ({}));
  if (!r.ok) throw new Error(data.detail || `${path} → ${r.status}`);
  return data;
}

function Empty({ children, action }) {
  return (
    <div className="empty-state">
      <p className="empty-state-text">{children}</p>
      {action}
    </div>
  );
}

function MetricRow({ label, value, hint }) {
  return (
    <div className="metric-row">
      <div>
        <div className="metric-row-label">{label}</div>
        {hint ? <div className="metric-row-hint">{hint}</div> : null}
      </div>
      <div className="metric-row-value mono">{value}</div>
    </div>
  );
}

function StatusTag({ ok, children }) {
  return <span className={"tag " + (ok ? "ok" : "med")}>{children}</span>;
}

/**
 * Feature Studio — product UI for platform surfaces (no raw JSON dumps).
 */
export default function FeatureStudio() {
  const [tab, setTab] = useState("analytics");
  const [err, setErr] = useState("");
  const [okMsg, setOkMsg] = useState("");
  const [busy, setBusy] = useState(false);
  const [data, setData] = useState({});

  const [phone, setPhone] = useState("+15550001111");
  const [slotStart, setSlotStart] = useState("");
  const [actionType, setActionType] = useState("open_investigation");
  const [resourceId, setResourceId] = useState("inv_demo");
  const [reviewer, setReviewer] = useState("bob");
  const [approvalId, setApprovalId] = useState("");
  const [jobType, setJobType] = useState("audit_contact");
  const [coachText, setCoachText] = useState("Ask for the VIN before closing.");
  const [coachIid, setCoachIid] = useState("int_demo");
  const [emailSubject, setEmailSubject] = useState("Brake grind 2019 Camry");
  const [emailBody, setEmailBody] = useState("My Toyota Camry 2019 brakes grind and spark.");
  const [i18nText, setI18nText] = useState("problema con frenos y peligro");
  const [subTarget, setSubTarget] = useState("ops@example.com");

  const flash = (msg) => {
    setOkMsg(msg);
    setTimeout(() => setOkMsg(""), 4000);
  };

  const loadAnalytics = useCallback(async () => {
    setBusy(true);
    setErr("");
    try {
      const [forecast, cross, hotspots, drift, cohort, fin, fair, reg] = await Promise.all([
        jget("/api/frontline/analytics/forecast"),
        jget("/api/frontline/analytics/cross-pack"),
        jget("/api/frontline/analytics/hotspots"),
        jget("/api/frontline/analytics/severity-drift"),
        jget("/api/frontline/analytics/cohorts"),
        jget("/api/frontline/analytics/financial-impact"),
        jget("/api/frontline/analytics/fairness"),
        jget("/api/frontline/analytics/regulator-watch"),
      ]);
      setData((d) => ({
        ...d,
        forecast,
        cross,
        hotspots,
        drift,
        cohort,
        fin,
        fair,
        reg,
      }));
    } catch (e) {
      setErr(String(e.message || e));
    } finally {
      setBusy(false);
    }
  }, []);

  const loadTab = useCallback(async () => {
    setErr("");
    setBusy(true);
    try {
      if (tab === "analytics") {
        await loadAnalytics();
        return;
      }
      if (tab === "callbacks") {
        const callbacks = await jget("/api/frontline/callbacks");
        setData((d) => ({ ...d, callbacks }));
      } else if (tab === "jobs") {
        const jobs = await jget("/api/frontline/jobs");
        setData((d) => ({ ...d, jobs }));
      } else if (tab === "marketplace") {
        const market = await jget("/api/frontline/marketplace/packs");
        setData((d) => ({ ...d, market }));
      } else if (tab === "ops") {
        const [backend, drain, usage, subs, oidc] = await Promise.all([
          jget("/api/frontline/ops/backend"),
          jget("/api/frontline/ops/drain"),
          jget("/api/frontline/usage"),
          jget("/api/frontline/subscriptions"),
          jget("/api/frontline/auth/oidc"),
        ]);
        setData((d) => ({ ...d, backend, drain, usage, subs, oidc }));
      }
    } catch (e) {
      setErr(String(e.message || e));
    } finally {
      setBusy(false);
    }
  }, [tab, loadAnalytics]);

  useEffect(() => {
    loadTab();
  }, [loadTab]);

  const forecasts = data.forecast?.forecasts || [];
  const finEstimates = data.fin?.estimates || [];
  const patterns = data.cross?.patterns || [];
  const hotspots = data.hotspots?.hotspots || [];
  const driftClusters = data.drift?.clusters || [];
  const fairGroups = data.fair?.groups || [];
  const regMatches = data.reg?.matches || [];
  const callbacks = data.callbacks?.callbacks || data.callbacks || [];
  const jobs = data.jobs?.jobs || data.jobs || [];
  const packs = data.market?.packs || [];
  const subs = data.subs?.subscriptions || data.subs || [];

  return (
    <div>
      <header className="page-header">
        <div>
          <h1>Feature studio</h1>
          <p className="sub">
            Analytics, booking, callbacks, approvals, jobs, coach, and ops — readable boards, not
            raw payloads.
          </p>
        </div>
        <div className="page-actions">
          <button type="button" onClick={loadTab} disabled={busy}>
            {busy ? "Refreshing…" : "Refresh"}
          </button>
        </div>
      </header>

      <div className="tabs" role="tablist" aria-label="Feature areas">
        {TABS.map((t) => (
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

      {err && (
        <div className="banner banner-error" role="alert">
          {err}
        </div>
      )}
      {okMsg && (
        <div className="banner banner-ok" role="status">
          {okMsg}
        </div>
      )}

      {/* ── Analytics ───────────────────────────────────────────────────── */}
      {tab === "analytics" && (
        <div className="stack">
          <div className="stat-grid" style={{ marginBottom: 4 }}>
            <div className="stat-card accent">
              <div className="label">Portfolio risk</div>
              <div className="value">
                ${Number(data.fin?.portfolio_risk_usd || 0).toLocaleString()}
              </div>
              <div className="hint">Pilot cost model</div>
            </div>
            <div className="stat-card">
              <div className="label">Forecast clusters</div>
              <div className="value">{forecasts.length}</div>
              <div className="hint">{data.forecast?.window_days || 28}d window</div>
            </div>
            <div className="stat-card">
              <div className="label">Cross-pack signals</div>
              <div className="value">{patterns.length}</div>
              <div className="hint">shared categories</div>
            </div>
            <div className={`stat-card ${data.fair?.flag ? "danger" : "ok"}`}>
              <div className="label">Fairness flag</div>
              <div className="value" style={{ fontSize: 22 }}>
                {data.fair?.flag ? "REVIEW" : "OK"}
              </div>
              <div className="hint">disparity {data.fair?.handoff_rate_disparity ?? "—"}</div>
            </div>
          </div>

          <div className="grid-2">
            <section className="panel">
              <h2>Cluster forecast</h2>
              {forecasts.length === 0 ? (
                <Empty>
                  No cluster volume series yet. Run voice contacts or simulate cases so weekly
                  counts appear.
                </Empty>
              ) : (
                <div className="table-wrap">
                  <table>
                    <thead>
                      <tr>
                        <th>Cluster</th>
                        <th>Last week</th>
                        <th>Slope</th>
                        <th>Weeks to threshold</th>
                        <th>Status</th>
                      </tr>
                    </thead>
                    <tbody>
                      {forecasts.map((f) => (
                        <tr key={String(f.cluster_id)}>
                          <td className="mono">{f.cluster_id}</td>
                          <td className="mono">{f.last_week_volume}</td>
                          <td className="mono">{f.slope_per_week}</td>
                          <td className="mono">
                            {f.projected_weeks_to_threshold ?? "—"}
                          </td>
                          <td>
                            <StatusTag ok={f.status === "ok"}>
                              {f.status || "—"}
                            </StatusTag>
                          </td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              )}
            </section>

            <section className="panel">
              <h2>Financial impact by cluster</h2>
              {finEstimates.length === 0 ? (
                <Empty>No case cost estimates yet. Open cases to populate risk dollars.</Empty>
              ) : (
                <div className="table-wrap">
                  <table>
                    <thead>
                      <tr>
                        <th>Cluster</th>
                        <th>Cases</th>
                        <th>Critical</th>
                        <th>Warranty</th>
                        <th>Recall risk</th>
                        <th>Total</th>
                      </tr>
                    </thead>
                    <tbody>
                      {finEstimates.slice(0, 12).map((e) => (
                        <tr key={String(e.cluster_id)}>
                          <td className="mono">{e.cluster_id}</td>
                          <td className="mono">{e.case_count}</td>
                          <td className="mono">{e.critical_count}</td>
                          <td className="mono">${Number(e.warranty_cost_usd || 0).toLocaleString()}</td>
                          <td className="mono">${Number(e.recall_risk_usd || 0).toLocaleString()}</td>
                          <td className="mono">${Number(e.total_risk_usd || 0).toLocaleString()}</td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              )}
            </section>
          </div>

          <div className="grid-3">
            <section className="panel">
              <h2>Cross-pack patterns</h2>
              {patterns.length === 0 ? (
                <Empty>No categories spanning multiple packs yet.</Empty>
              ) : (
                <div className="table-wrap">
                  <table>
                    <thead>
                      <tr>
                        <th>Category</th>
                        <th>Packs</th>
                        <th>Total</th>
                      </tr>
                    </thead>
                    <tbody>
                      {patterns.slice(0, 10).map((p) => (
                        <tr key={p.category}>
                          <td>{p.category}</td>
                          <td className="mono">{p.pack_count}</td>
                          <td className="mono">{p.total}</td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              )}
            </section>

            <section className="panel">
              <h2>Geographic hotspots</h2>
              {hotspots.length === 0 ? (
                <Empty>No region column data in the current window.</Empty>
              ) : (
                <ul className="bar-list">
                  {hotspots.slice(0, 8).map((h) => {
                    const max = Math.max(...hotspots.map((x) => x.volume || 0), 1);
                    const pct = Math.round(((h.volume || 0) / max) * 100);
                    return (
                      <li key={h.region}>
                        <div className="bar-list-head">
                          <span>{h.region}</span>
                          <span className="mono">{h.volume}</span>
                        </div>
                        <div className="bar-track" aria-hidden="true">
                          <div className="bar-fill" style={{ width: `${pct}%` }} />
                        </div>
                      </li>
                    );
                  })}
                </ul>
              )}
            </section>

            <section className="panel">
              <h2>Severity drift</h2>
              {driftClusters.length === 0 ? (
                <Empty>Need cases across early/late halves of the window.</Empty>
              ) : (
                <div className="table-wrap">
                  <table>
                    <thead>
                      <tr>
                        <th>Cluster</th>
                        <th>Early</th>
                        <th>Late</th>
                        <th>Drift</th>
                      </tr>
                    </thead>
                    <tbody>
                      {driftClusters.slice(0, 10).map((c) => (
                        <tr key={String(c.cluster_id)}>
                          <td className="mono">{c.cluster_id}</td>
                          <td className="mono">{c.early_avg_severity}</td>
                          <td className="mono">{c.late_avg_severity}</td>
                          <td>
                            <span className={c.worsening ? "err-text mono" : "ok-text mono"}>
                              {c.severity_drift}
                              {c.worsening ? " ↑" : ""}
                            </span>
                          </td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              )}
            </section>
          </div>

          <div className="grid-2">
            <section className="panel">
              <h2>Fairness by group</h2>
              {fairGroups.length === 0 ? (
                <Empty>No interaction groups in the fairness window.</Empty>
              ) : (
                <>
                  <div className="table-wrap">
                    <table>
                      <thead>
                        <tr>
                          <th>Group</th>
                          <th>Volume</th>
                          <th>Handoff proxy</th>
                          <th>Escalation</th>
                        </tr>
                      </thead>
                      <tbody>
                        {fairGroups.map((g) => (
                          <tr key={g.group}>
                            <td>{g.group}</td>
                            <td className="mono">{g.volume}</td>
                            <td className="mono">
                              {((g.handoff_proxy_rate || 0) * 100).toFixed(0)}%
                            </td>
                            <td className="mono">
                              {((g.escalation_rate || 0) * 100).toFixed(0)}%
                            </td>
                          </tr>
                        ))}
                      </tbody>
                    </table>
                  </div>
                  <p className="muted small" style={{ marginTop: 10 }}>
                    {data.fair?.note || "Pilot fairness monitor on category proxy."}
                  </p>
                </>
              )}
            </section>

            <section className="panel">
              <h2>Regulator filing watch</h2>
              <p className="muted small" style={{ marginTop: 0 }}>
                Pack <span className="mono">{data.reg?.pack_id || "—"}</span>
              </p>
              {regMatches.length === 0 ? (
                <Empty>
                  No advisory ↔ investigation matches yet. Open investigations and seed advisories.
                </Empty>
              ) : (
                <div className="table-wrap">
                  <table>
                    <thead>
                      <tr>
                        <th>Advisory</th>
                        <th>Investigation</th>
                        <th>Lead weeks</th>
                        <th>Before filing</th>
                      </tr>
                    </thead>
                    <tbody>
                      {regMatches.map((m, i) => (
                        <tr key={`${m.advisory_id}-${m.investigation_id}-${i}`}>
                          <td className="mono">{m.advisory_id}</td>
                          <td className="mono">{m.investigation_id}</td>
                          <td className="mono">{m.lead_time_weeks ?? "—"}</td>
                          <td>
                            <StatusTag ok={!!m.flagged_before_filing}>
                              {m.flagged_before_filing ? "yes" : "no"}
                            </StatusTag>
                          </td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              )}
            </section>
          </div>
        </div>
      )}

      {/* ── Booking ─────────────────────────────────────────────────────── */}
      {tab === "booking" && (
        <div className="grid-2">
          <section className="panel">
            <h2>Book free remedy appointment</h2>
            <div className="stack" style={{ maxWidth: 440 }}>
              <label>
                Slot start
                <input
                  value={slotStart}
                  onChange={(e) => setSlotStart(e.target.value)}
                  placeholder="Pick from offer or paste ISO time"
                />
              </label>
              <div className="row">
                <button
                  type="button"
                  className="primary"
                  onClick={async () => {
                    try {
                      setErr("");
                      const offer = await jpost("/api/frontline/booking/offer", {
                        advisory_id: "demo-adv",
                        pack_id: "automotive_nhtsa",
                        case_id: "case_demo",
                      });
                      setData((d) => ({ ...d, offer }));
                      if (!slotStart && offer.open_slots?.[0]?.slot_start) {
                        setSlotStart(offer.open_slots[0].slot_start);
                      }
                      flash("Open slots loaded");
                    } catch (e) {
                      setErr(String(e.message || e));
                    }
                  }}
                >
                  Load open slots
                </button>
                <button
                  type="button"
                  onClick={async () => {
                    try {
                      setErr("");
                      const booked = await jpost("/api/frontline/booking/book", {
                        pack_id: "automotive_nhtsa",
                        case_id: "case_demo",
                        slot_start: slotStart,
                      });
                      setData((d) => ({ ...d, booked }));
                      flash(`Booked ${booked.appointment_id}`);
                    } catch (e) {
                      setErr(String(e.message || e));
                    }
                  }}
                >
                  Confirm booking
                </button>
              </div>
            </div>
          </section>
          <section className="panel">
            <h2>Offer & confirmation</h2>
            {!data.offer && !data.booked ? (
              <Empty>Load open slots to see available times and customer message.</Empty>
            ) : (
              <div className="stack">
                {data.offer?.prompt && <p className="muted">{data.offer.prompt}</p>}
                {(data.offer?.open_slots || []).length > 0 && (
                  <div className="table-wrap">
                    <table>
                      <thead>
                        <tr>
                          <th>Label</th>
                          <th>Start</th>
                          <th />
                        </tr>
                      </thead>
                      <tbody>
                        {data.offer.open_slots.map((s) => (
                          <tr key={s.slot_start}>
                            <td>{s.label}</td>
                            <td className="mono">{s.slot_start}</td>
                            <td>
                              <button
                                type="button"
                                className="ghost"
                                onClick={() => setSlotStart(s.slot_start)}
                              >
                                Use
                              </button>
                            </td>
                          </tr>
                        ))}
                      </tbody>
                    </table>
                  </div>
                )}
                {data.booked && (
                  <div className="result-card">
                    <div className="result-card-title ok-text">Booked</div>
                    <div className="kvs">
                      <span className="k">id</span>
                      <span className="v mono">{data.booked.appointment_id}</span>
                      <span className="k">when</span>
                      <span className="v mono">{data.booked.slot_start}</span>
                      <span className="k">where</span>
                      <span className="v">{data.booked.location}</span>
                      <span className="k">message</span>
                      <span className="v">{data.booked.customer_message}</span>
                    </div>
                  </div>
                )}
              </div>
            )}
          </section>
        </div>
      )}

      {/* ── Callbacks ───────────────────────────────────────────────────── */}
      {tab === "callbacks" && (
        <section className="panel">
          <h2>Callback queue</h2>
          <div className="row" style={{ marginBottom: 14 }}>
            <label style={{ minWidth: 220 }}>
              Phone or channel
              <input value={phone} onChange={(e) => setPhone(e.target.value)} />
            </label>
            <button
              type="button"
              className="primary"
              onClick={async () => {
                try {
                  setErr("");
                  await jpost("/api/frontline/callbacks", {
                    pack_id: "automotive_nhtsa",
                    phone_or_channel: phone,
                  });
                  await loadTab();
                  flash("Callback scheduled");
                } catch (e) {
                  setErr(String(e.message || e));
                }
              }}
            >
              Schedule callback
            </button>
          </div>
          {!Array.isArray(callbacks) || callbacks.length === 0 ? (
            <Empty>No scheduled callbacks. Schedule one to populate the queue.</Empty>
          ) : (
            <div className="table-wrap">
              <table>
                <thead>
                  <tr>
                    <th>ID</th>
                    <th>Channel</th>
                    <th>Window</th>
                    <th>Status</th>
                    <th>Reason</th>
                  </tr>
                </thead>
                <tbody>
                  {(Array.isArray(callbacks) ? callbacks : []).map((c) => (
                    <tr key={c.callback_id}>
                      <td className="mono">{c.callback_id}</td>
                      <td>{c.phone_or_channel}</td>
                      <td>{c.preferred_window}</td>
                      <td>
                        <StatusTag ok={c.status === "scheduled"}>{c.status}</StatusTag>
                      </td>
                      <td className="muted">{c.reason}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </section>
      )}

      {/* ── Approvals ───────────────────────────────────────────────────── */}
      {tab === "approvals" && (
        <div className="grid-2">
          <section className="panel">
            <h2>Request four-eyes approval</h2>
            <div className="stack">
              <label>
                Action
                <select value={actionType} onChange={(e) => setActionType(e.target.value)}>
                  <option value="open_investigation">Open investigation</option>
                  <option value="close_p1_case">Close P1 case</option>
                  <option value="send_customer_followup">Send customer follow-up</option>
                </select>
              </label>
              <label>
                Resource id
                <input value={resourceId} onChange={(e) => setResourceId(e.target.value)} />
              </label>
              <button
                type="button"
                className="primary"
                onClick={async () => {
                  try {
                    setErr("");
                    const req = await jpost("/api/frontline/approvals", {
                      action_type: actionType,
                      resource_id: resourceId,
                      requested_by: "alice",
                    });
                    setApprovalId(req.approval_id || "");
                    setData((d) => ({ ...d, approvalReq: req }));
                    flash(req.required ? "Approval pending" : "Auto-allowed");
                  } catch (e) {
                    setErr(String(e.message || e));
                  }
                }}
              >
                Request
              </button>
              {data.approvalReq && (
                <div className="result-card">
                  <div className="kvs">
                    <span className="k">status</span>
                    <span className="v">{data.approvalReq.status}</span>
                    <span className="k">approval</span>
                    <span className="v mono">{data.approvalReq.approval_id || "—"}</span>
                    <span className="k">action</span>
                    <span className="v mono">{data.approvalReq.action_type}</span>
                  </div>
                </div>
              )}
            </div>
          </section>
          <section className="panel">
            <h2>Decide (second reviewer)</h2>
            <div className="stack">
              <label>
                Approval id
                <input value={approvalId} onChange={(e) => setApprovalId(e.target.value)} />
              </label>
              <label>
                Reviewer (must differ from requester)
                <input value={reviewer} onChange={(e) => setReviewer(e.target.value)} />
              </label>
              <div className="row">
                <button
                  type="button"
                  className="primary"
                  onClick={async () => {
                    try {
                      setErr("");
                      const dec = await jpost(`/api/frontline/approvals/${approvalId}/decide`, {
                        reviewer,
                        approve: true,
                      });
                      setData((d) => ({ ...d, approvalDec: dec }));
                      flash("Approved");
                    } catch (e) {
                      setErr(String(e.message || e));
                    }
                  }}
                >
                  Approve
                </button>
                <button
                  type="button"
                  className="danger"
                  onClick={async () => {
                    try {
                      setErr("");
                      const dec = await jpost(`/api/frontline/approvals/${approvalId}/decide`, {
                        reviewer,
                        approve: false,
                      });
                      setData((d) => ({ ...d, approvalDec: dec }));
                      flash("Rejected");
                    } catch (e) {
                      setErr(String(e.message || e));
                    }
                  }}
                >
                  Reject
                </button>
              </div>
              {data.approvalDec && (
                <div className="result-card">
                  <div className="kvs">
                    <span className="k">status</span>
                    <span className="v">{data.approvalDec.status}</span>
                    <span className="k">reviewer</span>
                    <span className="v">{data.approvalDec.reviewer}</span>
                    <span className="k">resource</span>
                    <span className="v mono">{data.approvalDec.resource_id}</span>
                  </div>
                </div>
              )}
            </div>
          </section>
        </div>
      )}

      {/* ── Jobs ────────────────────────────────────────────────────────── */}
      {tab === "jobs" && (
        <section className="panel">
          <h2>Background jobs</h2>
          <div className="row" style={{ marginBottom: 14 }}>
            <label style={{ minWidth: 200 }}>
              Job type
              <input value={jobType} onChange={(e) => setJobType(e.target.value)} />
            </label>
            <button
              type="button"
              className="primary"
              onClick={async () => {
                try {
                  setErr("");
                  await jpost("/api/frontline/jobs", {
                    job_type: jobType,
                    payload: { interaction_id: "int_demo" },
                  });
                  await loadTab();
                  flash("Job enqueued");
                } catch (e) {
                  setErr(String(e.message || e));
                }
              }}
            >
              Enqueue
            </button>
            <button
              type="button"
              onClick={async () => {
                try {
                  setErr("");
                  const r = await jpost("/api/frontline/jobs/run-next", {});
                  setData((d) => ({ ...d, jobRun: r }));
                  await loadTab();
                  flash(r.status === "empty" ? "Queue empty" : `Job ${r.status}`);
                } catch (e) {
                  setErr(String(e.message || e));
                }
              }}
            >
              Run next
            </button>
          </div>
          {data.jobRun && data.jobRun.status !== "empty" && (
            <div className="result-card" style={{ marginBottom: 12 }}>
              <div className="result-card-title">Last run</div>
              <div className="kvs">
                <span className="k">job</span>
                <span className="v mono">{data.jobRun.job_id}</span>
                <span className="k">status</span>
                <span className="v">{data.jobRun.status}</span>
              </div>
            </div>
          )}
          {!Array.isArray(jobs) || jobs.length === 0 ? (
            <Empty>No jobs in the queue. Enqueue a type such as audit_contact.</Empty>
          ) : (
            <div className="table-wrap">
              <table>
                <thead>
                  <tr>
                    <th>ID</th>
                    <th>Type</th>
                    <th>Status</th>
                    <th>Attempts</th>
                  </tr>
                </thead>
                <tbody>
                  {(Array.isArray(jobs) ? jobs : []).map((j) => (
                    <tr key={j.job_id}>
                      <td className="mono">{j.job_id}</td>
                      <td>{j.job_type}</td>
                      <td>
                        <StatusTag ok={j.status === "done"}>{j.status}</StatusTag>
                      </td>
                      <td className="mono">{j.attempts}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </section>
      )}

      {/* ── Coach ───────────────────────────────────────────────────────── */}
      {tab === "coach" && (
        <div className="grid-2">
          <section className="panel">
            <h2>Suggested supervisor replies</h2>
            <button
              type="button"
              className="primary"
              style={{ marginBottom: 12 }}
              onClick={async () => {
                try {
                  setErr("");
                  const s = await jpost("/api/frontline/coach/suggest", {
                    last_customer_text: "brakes grind",
                    slots: { entity_1: "Toyota" },
                    severity: "Critical",
                  });
                  setData((d) => ({ ...d, coachSuggest: s }));
                } catch (e) {
                  setErr(String(e.message || e));
                }
              }}
            >
              Generate suggestions
            </button>
            {(data.coachSuggest?.suggestions || []).length === 0 ? (
              <Empty>Generate suggestions for takeover coaching lines.</Empty>
            ) : (
              <ul className="suggest-list">
                {data.coachSuggest.suggestions.map((s) => (
                  <li key={s.id}>
                    <div className="suggest-id mono">{s.id}</div>
                    <div>{s.text}</div>
                  </li>
                ))}
              </ul>
            )}
          </section>
          <section className="panel">
            <h2>Private whisper</h2>
            <div className="stack">
              <label>
                Interaction id
                <input value={coachIid} onChange={(e) => setCoachIid(e.target.value)} />
              </label>
              <label>
                Message to agent
                <textarea value={coachText} onChange={(e) => setCoachText(e.target.value)} />
              </label>
              <button
                type="button"
                className="primary"
                onClick={async () => {
                  try {
                    setErr("");
                    const w = await jpost("/api/frontline/coach/whisper", {
                      interaction_id: coachIid,
                      text: coachText,
                    });
                    setData((d) => ({ ...d, whisper: w }));
                    flash("Whisper sent (private)");
                  } catch (e) {
                    setErr(String(e.message || e));
                  }
                }}
              >
                Send whisper
              </button>
              {data.whisper && (
                <div className="result-card">
                  <div className="kvs">
                    <span className="k">id</span>
                    <span className="v mono">{data.whisper.message_id}</span>
                    <span className="k">to</span>
                    <span className="v">{data.whisper.to_role}</span>
                    <span className="k">text</span>
                    <span className="v">{data.whisper.text}</span>
                  </div>
                </div>
              )}
            </div>
          </section>
        </div>
      )}

      {/* ── Channels ────────────────────────────────────────────────────── */}
      {tab === "channels" && (
        <div className="grid-2">
          <section className="panel">
            <h2>Email intake</h2>
            <div className="stack">
              <label>
                Subject
                <input value={emailSubject} onChange={(e) => setEmailSubject(e.target.value)} />
              </label>
              <label>
                Body
                <textarea value={emailBody} onChange={(e) => setEmailBody(e.target.value)} />
              </label>
              <button
                type="button"
                className="primary"
                onClick={async () => {
                  try {
                    setErr("");
                    const r = await jpost("/api/frontline/channels/email/ingest", {
                      subject: emailSubject,
                      body: emailBody,
                      from: "driver@example.com",
                    });
                    setData((d) => ({ ...d, email: r }));
                    flash(r.complete ? "Intake complete" : "Needs clarifying reply");
                  } catch (e) {
                    setErr(String(e.message || e));
                  }
                }}
              >
                Ingest email
              </button>
              {data.email ? (
                <div className="result-card">
                  <div className="result-card-title">
                    {data.email.complete ? (
                      <span className="ok-text">Slots complete</span>
                    ) : (
                      <span className="warn-text">Missing: {(data.email.missing || []).join(", ")}</span>
                    )}
                  </div>
                  <p className="muted">{data.email.reply}</p>
                  <div className="h-divider" />
                  <h3>Extracted slots</h3>
                  {Object.entries(data.email.slots || {})
                    .filter(([k]) => !k.startsWith("__"))
                    .map(([k, v]) => (
                      <div className="slot-row" key={k}>
                        <span className="k">{k}</span>
                        <span className="v">{String(v)}</span>
                      </div>
                    ))}
                </div>
              ) : (
                <Empty>Ingest a sample complaint email to extract slots.</Empty>
              )}
            </div>
          </section>
          <section className="panel">
            <h2>Language & returning caller</h2>
            <div className="stack">
              <label>
                Customer text
                <textarea value={i18nText} onChange={(e) => setI18nText(e.target.value)} />
              </label>
              <div className="row">
                <button
                  type="button"
                  className="primary"
                  onClick={async () => {
                    try {
                      setErr("");
                      const r = await jpost("/api/frontline/i18n/normalize", { text: i18nText });
                      setData((d) => ({ ...d, i18n: r }));
                    } catch (e) {
                      setErr(String(e.message || e));
                    }
                  }}
                >
                  Normalize language
                </button>
                <button
                  type="button"
                  onClick={async () => {
                    try {
                      setErr("");
                      const r = await jpost("/api/frontline/biometrics/match", {
                        pack_id: "automotive_nhtsa",
                        ani: "+15551212",
                      });
                      setData((d) => ({ ...d, bio: r }));
                    } catch (e) {
                      setErr(String(e.message || e));
                    }
                  }}
                >
                  Match caller (ANI)
                </button>
              </div>
              {data.i18n && (
                <div className="result-card">
                  <div className="kvs">
                    <span className="k">lang</span>
                    <span className="v mono">{data.i18n.lang}</span>
                    <span className="k">method</span>
                    <span className="v">{data.i18n.method}</span>
                    <span className="k">original</span>
                    <span className="v">{data.i18n.original}</span>
                    <span className="k">english</span>
                    <span className="v">{data.i18n.normalized_en}</span>
                  </div>
                </div>
              )}
              {data.bio && (
                <div className="result-card">
                  <div className="kvs">
                    <span className="k">matched</span>
                    <span className="v">{String(data.bio.matched)}</span>
                    <span className="k">source</span>
                    <span className="v">{data.bio.source || "—"}</span>
                    <span className="k">greeting</span>
                    <span className="v">{data.bio.greeting || "No prior match"}</span>
                  </div>
                </div>
              )}
            </div>
          </section>
        </div>
      )}

      {/* ── Marketplace ─────────────────────────────────────────────────── */}
      {tab === "marketplace" && (
        <section className="panel">
          <h2>Pack marketplace</h2>
          <div className="row" style={{ marginBottom: 14 }}>
            <button
              type="button"
              className="primary"
              onClick={async () => {
                try {
                  setErr("");
                  await jpost("/api/frontline/marketplace/install", {
                    pack_id: "automotive_nhtsa",
                  });
                  await loadTab();
                  flash("Pack registered");
                } catch (e) {
                  setErr(String(e.message || e));
                }
              }}
            >
              Re-register automotive
            </button>
          </div>
          {packs.length === 0 ? (
            <Empty>No packs in the local registry yet.</Empty>
          ) : (
            <div className="table-wrap">
              <table>
                <thead>
                  <tr>
                    <th>Pack</th>
                    <th>Version</th>
                    <th>Path</th>
                    <th>Changelog</th>
                  </tr>
                </thead>
                <tbody>
                  {packs.map((p) => (
                    <tr key={p.pack_id}>
                      <td className="mono">{p.pack_id}</td>
                      <td className="mono">{p.version}</td>
                      <td className="mono faint">{p.path}</td>
                      <td className="muted small">
                        {(p.changelog || []).slice(-1)[0] || "—"}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </section>
      )}

      {/* ── Ops ─────────────────────────────────────────────────────────── */}
      {tab === "ops" && (
        <div className="stack">
          <div className="stat-grid">
            <div className="stat-card">
              <div className="label">Ops backend</div>
              <div className="value" style={{ fontSize: 20 }}>
                {data.backend?.ops_backend || "—"}
              </div>
              <div className="hint">
                {data.backend?.dsn_set ? "DSN set" : "DuckDB default"} · alembic{" "}
                {data.backend?.alembic_ready ? "ready" : "n/a"}
              </div>
            </div>
            <div className={`stat-card ${data.drain?.draining ? "danger" : "ok"}`}>
              <div className="label">Drain</div>
              <div className="value" style={{ fontSize: 20 }}>
                {data.drain?.draining ? "DRAINING" : "READY"}
              </div>
              <div className="hint">{data.drain?.active_count ?? 0} active contacts</div>
            </div>
            <div className="stat-card accent">
              <div className="label">Contacts metered</div>
              <div className="value">
                {data.usage?.metrics?.contacts ?? "—"}
              </div>
              <div className="hint">{data.usage?.month || "this month"}</div>
            </div>
            <div className="stat-card">
              <div className="label">OIDC</div>
              <div className="value" style={{ fontSize: 20 }}>
                {data.oidc?.configured ? "ON" : "OFF"}
              </div>
              <div className="hint">
                roles {(data.oidc?.roles || []).join(", ") || "—"}
              </div>
            </div>
          </div>

          <div className="grid-2">
            <section className="panel">
              <h2>Deploy drain</h2>
              <p className="muted small">
                Stops new contacts; active calls finish. Maps to SIGTERM in production.
              </p>
              <button
                type="button"
                className="danger"
                onClick={async () => {
                  try {
                    setErr("");
                    const r = await jpost("/api/frontline/ops/drain", {});
                    setData((d) => ({ ...d, drain: r }));
                    flash("Drain started");
                  } catch (e) {
                    setErr(String(e.message || e));
                  }
                }}
              >
                Begin drain
              </button>
              {data.drain?.active_interactions?.length > 0 && (
                <ul className="plain" style={{ marginTop: 12 }}>
                  {data.drain.active_interactions.map((id) => (
                    <li key={id} className="mono">
                      {id}
                    </li>
                  ))}
                </ul>
              )}
            </section>

            <section className="panel">
              <h2>Report subscriptions</h2>
              <div className="row" style={{ marginBottom: 12 }}>
                <label style={{ minWidth: 200 }}>
                  Email target
                  <input value={subTarget} onChange={(e) => setSubTarget(e.target.value)} />
                </label>
                <button
                  type="button"
                  className="primary"
                  onClick={async () => {
                    try {
                      setErr("");
                      await jpost("/api/frontline/subscriptions", {
                        channel: "email",
                        target: subTarget,
                        report_type: "daily_digest",
                      });
                      await loadTab();
                      flash("Subscribed");
                    } catch (e) {
                      setErr(String(e.message || e));
                    }
                  }}
                >
                  Subscribe
                </button>
                <button
                  type="button"
                  onClick={async () => {
                    try {
                      setErr("");
                      const t = await jpost("/api/frontline/subscriptions/tick?force=true", {});
                      setData((d) => ({ ...d, tick: t }));
                      flash(`Sent ${t.count ?? 0}`);
                    } catch (e) {
                      setErr(String(e.message || e));
                    }
                  }}
                >
                  Send due now
                </button>
              </div>
              {!Array.isArray(subs) || subs.length === 0 ? (
                <Empty>No subscriptions yet.</Empty>
              ) : (
                <div className="table-wrap">
                  <table>
                    <thead>
                      <tr>
                        <th>ID</th>
                        <th>Channel</th>
                        <th>Target</th>
                        <th>Report</th>
                        <th>Enabled</th>
                      </tr>
                    </thead>
                    <tbody>
                      {(Array.isArray(subs) ? subs : []).map((s) => (
                        <tr key={s.subscription_id}>
                          <td className="mono">{s.subscription_id}</td>
                          <td>{s.channel}</td>
                          <td>{s.target}</td>
                          <td>{s.report_type}</td>
                          <td>
                            <StatusTag ok={!!s.enabled}>{s.enabled ? "yes" : "no"}</StatusTag>
                          </td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              )}
              {data.usage?.metrics && (
                <>
                  <div className="h-divider" />
                  <h3>Usage this period</h3>
                  {Object.entries(data.usage.metrics).map(([k, v]) => (
                    <MetricRow key={k} label={k} value={v} />
                  ))}
                </>
              )}
            </section>
          </div>
        </div>
      )}
    </div>
  );
}
