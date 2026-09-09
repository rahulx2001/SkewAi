import { useCallback, useEffect, useState } from "react";
import { apiHeaders } from "../src/apiAuth.js";
import { humanizeKey, whyTrustedLabel } from "../src/ui/labels.js";

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

export default function TrustPipeline({ embedded }) {
  const [kpis, setKpis] = useState([]);
  const [picked, setPicked] = useState(null);
  const [queue, setQueue] = useState([]);
  const [reviews, setReviews] = useState([]);
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
      if (!b.ok) throw new Error(`validation queue ${b.status}`);
      if (!c.ok) throw new Error(`usage ${c.status}`);
      const ka = await a.json();
      const qb = await b.json();
      setKpis(ka.kpis || []);
      setQueue(qb.items || []);
      setReviews(qb.reviews || []);
      setUsage(await c.json());
    } catch (e) {
      setErr(String(e.message || e));
    }
  }, []);

  useEffect(() => {
    load();
  }, [load]);

  async function openFigure(kpiId) {
    try {
      const h = apiHeaders();
      const r = await fetch(`/api/frontline/provenance/kpis/${kpiId}`, { headers: h });
      if (!r.ok) {
        setErr(`figure ${r.status}`);
        return;
      }
      setPicked(await r.json());
    } catch (e) {
      setErr(String(e.message || e));
    }
  }

  async function assignReview(id) {
    try {
      setErr("");
      const r = await fetch(`/api/frontline/reviews/${encodeURIComponent(id)}/assign`, {
        method: "POST",
        headers: { ...apiHeaders(), "Content-Type": "application/json" },
        body: JSON.stringify({}),
      });
      if (!r.ok) throw new Error(`assign ${r.status}`);
      await load();
    } catch (e) {
      setErr(String(e.message || e));
    }
  }

  async function resolveReview(id, verdict) {
    try {
      setErr("");
      const r = await fetch(`/api/frontline/reviews/${encodeURIComponent(id)}/resolve`, {
        method: "POST",
        headers: { ...apiHeaders(), "Content-Type": "application/json" },
        body: JSON.stringify({ verdict }),
      });
      if (!r.ok) throw new Error(`resolve ${r.status}`);
      await load();
    } catch (e) {
      setErr(String(e.message || e));
    }
  }

  return (
    <div>
      {!embedded && (
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
      )}
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
            <div className="label">{humanizeKey(k.kpi_id)}</div>
            <div className="value">{k.value}</div>
            <div className="hint">{whyTrustedLabel(k.badge?.why_trusted)}</div>
          </button>
        ))}
      </div>
      {picked && (
        <section className="panel" style={{ marginTop: 16 }}>
          <h2>{humanizeKey(picked.kpi_id)}</h2>
          <p>
            {whyTrustedLabel(
              [picked.badge?.source, picked.badge?.freshness, picked.badge?.grounded_verdict]
                .filter(Boolean)
                .join(" "),
            )}
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
        {queue.length === 0 && reviews.length === 0 ? (
          <p className="sub">No items waiting for a reviewer.</p>
        ) : (
          <ul>
            {queue.map((item) => (
              <li key={item.ref_id || item.queue_id}>
                <strong>{humanizeKey(item.queue_kind)}</strong> {item.summary}
                {(item.span_evidence || []).map((ev) => (
                  <p key={ev.evidence_id} className="sub">
                    {ev.span?.before}
                    <mark>{ev.span?.hit}</mark>
                    {ev.span?.after}
                  </p>
                ))}
              </li>
            ))}
            {reviews.map((rev) => (
              <li key={rev.review_id} style={{ marginTop: 10 }}>
                <strong>{rev.reason || "review"}</strong>{" "}
                <span className="mono">{rev.review_id}</span>{" "}
                <span className="chip">{rev.status}</span>
                {rev.status === "open" && (
                  <button type="button" className="ghost" style={{ marginLeft: 8 }} onClick={() => assignReview(rev.review_id)}>
                    Assign to me
                  </button>
                )}
                {(rev.status === "open" || rev.status === "assigned") && (
                  <>
                    <button type="button" className="ghost" style={{ marginLeft: 8 }} onClick={() => resolveReview(rev.review_id, "false_alarm")}>
                      False alarm
                    </button>
                    <button type="button" className="ghost" onClick={() => resolveReview(rev.review_id, "ai_wrong")}>
                      AI wrong
                    </button>
                  </>
                )}
              </li>
            ))}
          </ul>
        )}
      </section>
    </div>
  );
}
