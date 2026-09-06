import { useEffect, useState } from "react";
import {
  apiHeaders,
  getStoredApiKey,
  notifyAuthChange,
  setApiKey as storeApiKey,
} from "../src/apiAuth.js";

export default function Settings() {
  const [packs, setPacks] = useState([]);
  const [active, setActive] = useState(null);
  const [loading, setLoading] = useState(true);
  const [switching, setSwitching] = useState(false);
  const [error, setError] = useState(null);
  const [alertWebhook, setAlertWebhook] = useState("");
  const [apiKey, setApiKey] = useState(() => getStoredApiKey());
  // Explicit opt-in persistence (item 20): memory-only by default, disk
  // only when the operator checks "Remember on this device".
  const [rememberKey, setRememberKey] = useState(true);
  const [authRequired, setAuthRequired] = useState(false);
  const [deadLetters, setDeadLetters] = useState([]);
  const [dlLoading, setDlLoading] = useState(false);
  const [dlMsg, setDlMsg] = useState(null);
  const [singleWorker, setSingleWorker] = useState(null);
  const [connEnabled, setConnEnabled] = useState(false);
  const [connUrl, setConnUrl] = useState("");
  const [connSecret, setConnSecret] = useState("");
  const [connStatus, setConnStatus] = useState(null);
  const [connDeliveries, setConnDeliveries] = useState([]);
  const [connMsg, setConnMsg] = useState(null);
  const [connLoading, setConnLoading] = useState(false);

  // All requests go through the centralized credential helper
  // (src/apiAuth.js) — no direct storage reads in components (item 46).

  async function load() {
    setLoading(true);
    setError(null);
    try {
      const r = await fetch("/api/packs", { headers: apiHeaders() });
      if (!r.ok) throw new Error(`HTTP ${r.status}`);
      const d = await r.json();
      setPacks(d.packs || []);
      setActive(d.active || null);
    } catch (e) {
      setError(String(e));
    } finally {
      setLoading(false);
    }
  }

  async function loadDeadLetters() {
    setDlLoading(true);
    setDlMsg(null);
    try {
      const r = await fetch("/api/frontline/alerts/dead-letter?status=pending&limit=50", {
        headers: apiHeaders(),
      });
      if (!r.ok) throw new Error(`HTTP ${r.status}: ${await r.text()}`);
      const d = await r.json();
      setDeadLetters(d.dead_letters || []);
    } catch (e) {
      setDlMsg(String(e));
      setDeadLetters([]);
    } finally {
      setDlLoading(false);
    }
  }

  async function replayDeadLetter(id) {
    setDlMsg(null);
    try {
      const r = await fetch(
        `/api/frontline/alerts/dead-letter/${encodeURIComponent(id)}/replay`,
        { method: "POST", headers: apiHeaders() }
      );
      if (!r.ok) throw new Error(`HTTP ${r.status}: ${await r.text()}`);
      setDlMsg(`Replayed ${id}`);
      await loadDeadLetters();
    } catch (e) {
      setDlMsg(String(e));
    }
  }

  async function loadConnector() {
    setConnLoading(true);
    setConnMsg(null);
    try {
      const [st, dl] = await Promise.all([
        fetch("/api/frontline/connectors/status", { headers: apiHeaders() }),
        fetch("/api/frontline/connectors/deliveries?status=pending&limit=50", {
          headers: apiHeaders(),
        }),
      ]);
      if (!st.ok) throw new Error(`status HTTP ${st.status}`);
      if (!dl.ok) throw new Error(`deliveries HTTP ${dl.status}`);
      const s = await st.json();
      const d = await dl.json();
      setConnStatus(s);
      setConnEnabled(!!s.enabled);
      // Do not put redacted host into the edit field (would overwrite real URL on save).
      setConnDeliveries(d.deliveries || []);
    } catch (e) {
      setConnMsg(String(e));
      setConnStatus(null);
      setConnDeliveries([]);
    } finally {
      setConnLoading(false);
    }
  }

  async function saveConnector() {
    setConnMsg(null);
    try {
      const body = { enabled: !!connEnabled };
      // Only send webhook_url when the operator typed a new value (avoids
      // overwriting a configured URL with the redacted display form).
      if (connUrl.trim()) body.webhook_url = connUrl.trim();
      if (connSecret.trim()) body.shared_secret = connSecret.trim();
      const r = await fetch("/api/frontline/connectors/config", {
        method: "PUT",
        headers: {
          ...apiHeaders(),
          "Content-Type": "application/json",
        },
        body: JSON.stringify(body),
      });
      if (!r.ok) throw new Error(`HTTP ${r.status}: ${await r.text()}`);
      setConnSecret("");
      setConnUrl("");
      setConnMsg("Connector config saved.");
      await loadConnector();
    } catch (e) {
      setConnMsg(String(e));
    }
  }

  async function replayConnector(id) {
    setConnMsg(null);
    try {
      const r = await fetch(
        `/api/frontline/connectors/deliveries/${encodeURIComponent(id)}/replay`,
        { method: "POST", headers: apiHeaders() }
      );
      if (!r.ok) throw new Error(`HTTP ${r.status}: ${await r.text()}`);
      setConnMsg(`Replayed delivery ${id}`);
      await loadConnector();
    } catch (e) {
      setConnMsg(String(e));
    }
  }

  useEffect(() => {
    load();
    loadDeadLetters();
    loadConnector();
    fetch("/health")
      .then((r) => (r.ok ? r.json() : {}))
      .then((d) => {
        setAuthRequired(!!d.auth_required);
        setSingleWorker(d.single_worker);
        if (d.alert_webhook_url) setAlertWebhook(d.alert_webhook_url);
        else setAlertWebhook("Configured on server");
      })
      .catch(() => setAlertWebhook("Configured on server"));
  }, []);

  function saveApiKey() {
    // Centralized credential handling: sync the live input into the store
    // first so saved requests use exactly what the operator typed.
    storeApiKey(apiKey.trim(), { remember: rememberKey });
    setApiKey(apiKey.trim());
    notifyAuthChange();
    // Reload pack list + ops surfaces that require the key when auth is on.
    load();
    loadDeadLetters();
    loadConnector();
  }

  async function selectPack(packId) {
    if (packId === active) return;
    setSwitching(true);
    setError(null);
    try {
      const r = await fetch(
        `/api/packs/active?pack_id=${encodeURIComponent(packId)}`,
        {
          method: "PUT",
          headers: apiHeaders(),
        }
      );
      if (!r.ok) {
        const detail = await r.text();
        throw new Error(`HTTP ${r.status}: ${detail}`);
      }
      const d = await r.json();
      setActive(d.active);
    } catch (e) {
      setError(String(e));
    } finally {
      setSwitching(false);
    }
  }

  const activePack = packs.find((p) => p.id === active);

  return (
    <div>
      <header className="page-header">
        <div>
          <h1>Settings</h1>
          <p className="sub">Packs, pilot API key, connectors, and alert dead-letter replay.</p>
        </div>
        <div className="page-actions">
          <button type="button" onClick={load} disabled={loading}>
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

      <div className="panel" style={{ marginBottom: 16 }}>
        <h2>Pilot API key</h2>
        <p className="muted" style={{ fontSize: 12, marginBottom: 8 }}>
          Stored in this browser only. Sent on write routes when the server
          requires authentication.
          {authRequired
            ? " Server currently requires a key."
            : " Server is open (no key configured)."}
          {singleWorker === true && (
            <>
              {" "}
              Deploy note: single-worker process (in-process active registry).
            </>
          )}
        </p>
        <div className="row" style={{ gap: 8 }}>
          <input
            type="password"
            value={apiKey}
            onChange={(e) => setApiKey(e.target.value)}
            placeholder="Paste pilot API key"
            aria-label="Pilot API key"
            autoComplete="off"
            style={{ flex: 1 }}
          />
          <button className="primary" onClick={saveApiKey}>
            Save
          </button>
        </div>
        <label className="row" style={{ gap: 8, marginTop: 8, fontSize: 12 }}>
          <input
            type="checkbox"
            checked={rememberKey}
            onChange={(e) => setRememberKey(e.target.checked)}
            aria-label="Remember API key on this device"
          />
          Remember on this device (otherwise the key lives in memory only)
        </label>
      </div>

      <div className="panel" style={{ marginBottom: 16 }}>
        <h2>Active Domain Pack</h2>
        {loading && <div className="empty">loading packs…</div>}
        {!loading && (
          <>
            <div className="kvs" style={{ marginBottom: 14 }}>
              <span className="k">active pack</span>
              <span className="v mono">
                {activePack ? (
                  <>
                    {activePack.id}{" "}
                    <span className="muted">
                      ({activePack.display_name} · v{activePack.pack_version})
                    </span>
                  </>
                ) : (
                  <span className="faint">{active || "—"}</span>
                )}
              </span>
            </div>

            <table>
              <thead>
                <tr>
                  <th>pack id</th>
                  <th>display name</th>
                  <th>version</th>
                  <th>slots</th>
                  <th>lint</th>
                  <th></th>
                </tr>
              </thead>
              <tbody>
                {packs.filter((p) => p.id && !String(p.id).startsWith("_") && !p.error).map((p) => (
                  <tr key={p.id} className={p.is_active ? "selected" : ""}>
                    <td className="mono">{p.id}</td>
                    <td>
                      {p.display_name || <span className="faint">—</span>}
                    </td>
                    <td className="mono">{p.pack_version || "—"}</td>
                    <td>
                      {(p.slots || []).slice(0, 4).map((s) => (
                        <span className="chip" key={s} style={{ fontSize: 10 }}>
                          {s}
                        </span>
                      ))}
                      {(p.slots || []).length > 4 && (
                        <span className="faint"> +{p.slots.length - 4}</span>
                      )}
                    </td>
                    <td>
                      {p.error ? (
                        <span className="chip red">invalid</span>
                      ) : p.lint_errors && p.lint_errors.length > 0 ? (
                        <span className="chip red">
                          {p.lint_errors.length} lint error(s)
                        </span>
                      ) : (
                        <span className="chip green">clean</span>
                      )}
                    </td>
                    <td style={{ textAlign: "right" }}>
                      {p.is_active ? (
                        <span className="chip green">active</span>
                      ) : (
                        <button
                          className="primary"
                          disabled={
                            switching ||
                            Boolean(p.error) ||
                            (p.lint_errors && p.lint_errors.length > 0)
                          }
                          onClick={() => selectPack(p.id)}
                          title={
                            p.lint_errors && p.lint_errors.length > 0
                              ? "pack has lint errors"
                              : ""
                          }
                        >
                          Activate
                        </button>
                      )}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </>
        )}
      </div>

      <div className="panel" style={{ marginBottom: 16 }}>
        <h2>Alerts</h2>
        <div className="field">
          <label>Alert webhook</label>
          <input
            value={alertWebhook}
            onChange={(e) => setAlertWebhook(e.target.value)}
            readOnly
            style={{ width: "100%" }}
            placeholder="Configured on server"
            aria-label="Alert webhook URL"
          />
          <span className="faint" style={{ fontSize: 11, marginTop: 4 }}>
            Display only. Set the webhook URL on the server environment and
            restart to enable outbound alert webhooks.
          </span>
        </div>
      </div>

      <div className="panel" style={{ marginBottom: 16 }}>
        <div
          style={{
            display: "flex",
            justifyContent: "space-between",
            alignItems: "center",
            marginBottom: 8,
          }}
        >
          <h2 style={{ margin: 0 }}>Alert dead-letters</h2>
          <button className="ghost" onClick={loadDeadLetters} disabled={dlLoading}>
            {dlLoading ? "…" : "⟳ Refresh"}
          </button>
        </div>
        <p className="muted" style={{ fontSize: 12, marginBottom: 10 }}>
          Failed Slack/webhook deliveries after retries. Replay resends the
          stored payload to the original endpoint.
        </p>
        {dlMsg && (
          <div className="muted" style={{ fontSize: 12, marginBottom: 8 }}>
            {dlMsg}
          </div>
        )}
        {deadLetters.length === 0 && !dlLoading && (
          <div className="empty">No pending dead-letters.</div>
        )}
        {deadLetters.length > 0 && (
          <table>
            <thead>
              <tr>
                <th>id</th>
                <th>event</th>
                <th>ref</th>
                <th>attempts</th>
                <th>error</th>
                <th></th>
              </tr>
            </thead>
            <tbody>
              {deadLetters.map((d) => (
                <tr key={d.dead_letter_id}>
                  <td className="mono" style={{ fontSize: 11 }}>
                    {(d.dead_letter_id || "").slice(0, 18)}…
                  </td>
                  <td>{d.event}</td>
                  <td className="mono" style={{ fontSize: 11 }}>
                    {d.ref_id}
                  </td>
                  <td className="mono">{d.attempts}</td>
                  <td style={{ fontSize: 11, maxWidth: 180 }} className="muted">
                    {(d.error || "—").slice(0, 80)}
                  </td>
                  <td style={{ textAlign: "right" }}>
                    <button
                      className="primary"
                      onClick={() => replayDeadLetter(d.dead_letter_id)}
                    >
                      Replay
                    </button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </div>

      <div className="panel" style={{ marginBottom: 16 }}>
        <div
          style={{
            display: "flex",
            justifyContent: "space-between",
            alignItems: "center",
            marginBottom: 8,
          }}
        >
          <h2 style={{ margin: 0 }}>Outbound connector</h2>
          <button className="ghost" onClick={loadConnector} disabled={connLoading}>
            {connLoading ? "…" : "⟳ refresh"}
          </button>
        </div>
        <p className="muted" style={{ fontSize: 12, marginBottom: 10 }}>
          Generic HTTP webhook + dry-run file outbox for case / investigation
          events. <strong>Not</strong> Salesforce, ServiceNow, or Twilio product
          integration. Files land under <code>data/connectors/outbox/</code>.
        </p>
        <div className="field" style={{ marginBottom: 12 }}>
          <label className="check-row">
            <input
              type="checkbox"
              checked={connEnabled}
              onChange={(e) => setConnEnabled(e.target.checked)}
              aria-label="Enable outbound connectors"
            />
            <span>
              Enabled
              <span className="faint" style={{ display: "block", fontWeight: 400, fontSize: 11.5, marginTop: 2 }}>
                When on, case and investigation events are posted to the webhook or written to the outbox.
              </span>
            </span>
          </label>
        </div>
        <div className="field" style={{ marginBottom: 10 }}>
          <label>Webhook URL (optional)</label>
          <input
            value={connUrl}
            onChange={(e) => setConnUrl(e.target.value)}
            placeholder={
              connStatus?.webhook_url_redacted
                ? `Configured: ${connStatus.webhook_url_redacted} — type to replace`
                : "https://hooks.example.com/skewai"
            }
            aria-label="Connector webhook URL"
            style={{ width: "100%" }}
          />
          <span className="faint" style={{ fontSize: 11, marginTop: 4 }}>
            Leave empty to keep the current URL (or outbox-only dry-run when none
            is set). Paste a full URL only when changing it.
          </span>
        </div>
        <div className="field" style={{ marginBottom: 10 }}>
          <label>Shared secret (optional → X-Connector-Secret)</label>
          <input
            type="password"
            value={connSecret}
            onChange={(e) => setConnSecret(e.target.value)}
            placeholder={
              connStatus?.shared_secret_set
                ? "(set — enter to replace)"
                : "Optional"
            }
            aria-label="Connector shared secret"
            style={{ width: "100%" }}
          />
        </div>
        <div className="row" style={{ gap: 8, marginBottom: 10 }}>
          <button className="primary" onClick={saveConnector}>
            Save connector
          </button>
          {connStatus && (
            <span className="muted" style={{ fontSize: 12 }}>
              sink={connStatus.sink || "—"} · counts={" "}
              {Object.entries(connStatus.delivery_counts || {}).length === 0
                ? "none yet"
                : Object.entries(connStatus.delivery_counts || {})
                    .map(([k, v]) => `${k}: ${v}`)
                    .join(" · ")}
            </span>
          )}
        </div>
        {connMsg && (
          <div className="muted" style={{ fontSize: 12, marginBottom: 8 }}>
            {connMsg}
          </div>
        )}
        <h3 style={{ fontSize: 13, margin: "12px 0 8px" }}>
          Pending deliveries
        </h3>
        {connDeliveries.length === 0 && !connLoading && (
          <div className="empty">No pending connector deliveries.</div>
        )}
        {connDeliveries.length > 0 && (
          <table>
            <thead>
              <tr>
                <th>id</th>
                <th>event</th>
                <th>ref</th>
                <th>sink</th>
                <th>error</th>
                <th></th>
              </tr>
            </thead>
            <tbody>
              {connDeliveries.map((d) => (
                <tr key={d.delivery_id}>
                  <td className="mono" style={{ fontSize: 11 }}>
                    {(d.delivery_id || "").slice(0, 18)}…
                  </td>
                  <td>{d.event}</td>
                  <td className="mono" style={{ fontSize: 11 }}>
                    {d.ref_id}
                  </td>
                  <td className="mono" style={{ fontSize: 11 }}>
                    {d.sink}
                  </td>
                  <td style={{ fontSize: 11, maxWidth: 160 }} className="muted">
                    {(d.error || "—").slice(0, 80)}
                  </td>
                  <td style={{ textAlign: "right" }}>
                    <button
                      className="primary"
                      onClick={() => replayConnector(d.delivery_id)}
                    >
                      Replay
                    </button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </div>
    </div>
  );
}
