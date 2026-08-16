import { useCallback, useEffect, useState } from "react";
import { apiHeaders } from "../src/apiAuth.js";

function Chain({ chain }) {
  if (!chain || !chain.length) return null;
  return (
    <ol className="chain">
      {chain.map((step, i) => (
        <li key={`${step.step}-${i}`}>
          <strong>{step.step}</strong> {String(step.value ?? "")}
        </li>
      ))}
    </ol>
  );
}

export default function TrustPipeline() {
  const [kpis, setKpis] = useState([]);
  const [picked, setPicked] = useState(null);
  const [queue, setQueue] = useState([]);
  const [usage, setUsage] = useState(null);
  const [err, setErr] = useState("");

  const load = useCallback(async () => {
    setErr("");
    try {
      const h = apiHeaders();
      const [a, b, c] = await Promise.all([
        fetch("/api/frontline/provenance/kpis", { headers: h }),
        fetch("/api/frontline/validation-queue", { headers: h }),
        fetch("/api/frontline/usage", { headers: h }),
      ]);
      if (!a.ok) throw new Error(`provenance ${a.status}`);
      const ka = await a.json();
      setKpis(ka.kpis || []);
      if (b.ok) setQueue((await b.json()).items || []);
      if (c.ok) setUsage(await c.json());
    } catch (e) {
      setErr(String(e.message || e));
    }
  }, []);

  useEffect(() => {
    load();
  }, [load]);

  async function openFigure(kpiId) {
    const h = apiHeaders();
    const r = await fetch(`/api/frontline/provenance/kpis/${kpiId}`, { headers: h });
    if (!r.ok) {
      setErr(`figure ${r.status}`);
      return;
    }
    setPicked(await r.json());
  }

  return (
    <div>
      <header className="page-header">
        <div>
          <h1>Pipeline trust</h1>
          <p className="sub">
            Every figure carries source, freshness, and a grounded verdict. Click a number for its chain of custody.
          </p>
        </div>
        <div className="page-actions">
          <button type="button" onClick={load}>
            Refresh
          </button>
        </div>
      </header>
      {err && (
        <div className="banner banner-error" role="alert">
          {err}
        </div>
      )}
      <div className="stat-grid">
        {kpis.map((k) => (
          <button
            type="button"
            className="stat-card"
            key={k.kpi_id}
            onClick={() => openFigure(k.kpi_id)}
          >
            <div className="label">{k.kpi_id.replaceAll("_", " ")}</div>
            <div className="value">{k.value}</div>
            <div className="hint">{k.badge?.why_trusted}</div>
          </button>
        ))}
      </div>
      {picked && (
        <section className="panel" style={{ marginTop: 16 }}>
          <h2>{picked.kpi_id}</h2>
          <p>
            {picked.badge?.source} · {picked.badge?.freshness} · {picked.badge?.grounded_verdict}
          </p>
          <Chain chain={picked.chain_of_custody} />
        </section>
      )}
      {usage && (
        <section className="panel" style={{ marginTop: 16 }}>
          <h2>Usage</h2>
          <p>
            Plan {usage.plan}, seats {usage.seats_used}
          </p>
        </section>
      )}
      <section className="panel" style={{ marginTop: 16 }}>
        <h2>Validation queue</h2>
        {queue.length === 0 ? (
          <p className="sub">No items waiting for a reviewer.</p>
        ) : (
          <ul>
            {queue.map((item) => (
              <li key={item.ref_id || item.queue_id}>
                <strong>{item.queue_kind}</strong> {item.summary}
                {(item.span_evidence || []).map((ev) => (
                  <p key={ev.evidence_id} className="sub">
                    {ev.span?.before}
                    <mark>{ev.span?.hit}</mark>
                    {ev.span?.after}
                  </p>
                ))}
              </li>
            ))}
          </ul>
        )}
      </section>
    </div>
  );
}
