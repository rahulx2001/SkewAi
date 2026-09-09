import { useState } from "react";
import { apiHeaders } from "../src/apiAuth.js";

const CANON = [
  "record_id",
  "text",
  "entity_1",
  "entity_2",
  "entity_3",
  "category",
  "received_at",
  "source",
];

export default function PackBuilder({ embedded }) {
  const [columns, setColumns] = useState([]);
  const [mapping, setMapping] = useState({});
  const [csvPath, setCsvPath] = useState("");
  const [lint, setLint] = useState(null);
  const [insight, setInsight] = useState(null);
  const [err, setErr] = useState("");
  const [busy, setBusy] = useState(false);

  async function onFile(e) {
    const file = e.target.files && e.target.files[0];
    if (!file) return;
    setErr("");
    setInsight(null);
    setColumns([]);
    setMapping({});
    setCsvPath("");
    setLint(null);
    setBusy(true);
    try {
      const body = new FormData();
      body.append("file", file);
      const r = await fetch("/api/frontline/pack-builder/profile", {
        method: "POST",
        headers: apiHeaders(),
        body,
      });
      if (!r.ok) throw new Error(`profile ${r.status}`);
      const data = await r.json();
      setColumns(data.columns || []);
      setMapping(data.proposed_mapping || {});
      setCsvPath(data.csv_path || "");
      setLint(data.lint || null);
    } catch (ex) {
      setErr(String(ex.message || ex));
    } finally {
      setBusy(false);
      e.target.value = "";
    }
  }

  async function runInsight() {
    if (!csvPath) return;
    setBusy(true);
    setErr("");
    try {
      const r = await fetch("/api/frontline/pack-builder/insight", {
        method: "POST",
        headers: { ...apiHeaders(), "Content-Type": "application/json" },
        body: JSON.stringify({
          csv_path: csvPath,
          mapping,
          pack_id: "builder_preview",
          display_name: "Preview pack",
        }),
      });
      if (!r.ok) throw new Error(`insight ${r.status}`);
      const data = await r.json();
      setLint(data.lint || lint);
      setInsight(data.insight || null);
      if (data.ok === false) setErr((data.lint && data.lint.errors && data.lint.errors.join("; ")) || "lint failed");
    } catch (ex) {
      setErr(String(ex.message || ex));
    } finally {
      setBusy(false);
    }
  }

  return (
    <div>
      {!embedded && (
        <header className="page-header">
          <div>
            <h1>Pack builder</h1>
            <p className="sub">Upload a CSV, confirm column mapping, lint, then get a first insight.</p>
          </div>
        </header>
      )}
      {err && (
        <div className="banner banner-error" role="alert">
          {err}
        </div>
      )}
      <section className="panel">
        <label>
          Source CSV
          <input type="file" accept=".csv,text/csv" onChange={onFile} disabled={busy} aria-label="Source CSV file" />
        </label>
      </section>
      {columns.length > 0 && (
        <section className="panel" style={{ marginTop: 16 }}>
          <h2>Column mapping</h2>
          {CANON.map((field) => (
            <label key={field} style={{ display: "block", marginBottom: 8 }}>
              {field}
              <select
                value={mapping[field] || ""}
                onChange={(e) =>
                  setMapping((m) => {
                    const next = { ...m };
                    if (e.target.value) next[field] = e.target.value;
                    else delete next[field];
                    return next;
                  })
                }
              >
                <option value="">—</option>
                {columns.map((c) => (
                  <option key={c} value={c}>
                    {c}
                  </option>
                ))}
              </select>
            </label>
          ))}
          <button type="button" onClick={runInsight} disabled={busy || !csvPath}>
            {busy ? "Working…" : "Lint and first insight"}
          </button>
        </section>
      )}
      {lint && (
        <section className="panel" style={{ marginTop: 16 }}>
          <h2>Lint</h2>
          <p>{lint.ok ? "Mapping is usable." : "Mapping has errors."}</p>
          {(lint.errors || []).map((e) => (
            <p key={e} className="sub">
              {e}
            </p>
          ))}
        </section>
      )}
      {insight && (
        <section className="panel" style={{ marginTop: 16 }}>
          <h2>First insight</h2>
          <p>{insight.headline}</p>
          <p className="sub">
            {insight.theme} · {insight.count} of {insight.n}
          </p>
        </section>
      )}
    </div>
  );
}
