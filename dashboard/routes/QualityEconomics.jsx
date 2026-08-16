import { useCallback, useEffect, useState } from "react";
import { apiHeaders } from "../src/apiAuth.js";

export default function QualityEconomics() {
  const [rank, setRank] = useState([]);
  const [hotspots, setHotspots] = useState(null);
  const [err, setErr] = useState("");

  const load = useCallback(async () => {
    setErr("");
    try {
      const h = apiHeaders();
      const [a, b] = await Promise.all([
        fetch("/api/frontline/copq/rank", { headers: h }),
        fetch("/api/frontline/analytics/hotspots-map", { headers: h }),
      ]);
      if (a.ok) setRank((await a.json()).clusters || []);
      if (b.ok) setHotspots(await b.json());
    } catch (e) {
      setErr(String(e.message || e));
    }
  }, []);

  useEffect(() => {
    load();
  }, [load]);

  return (
    <div>
      <header className="page-header">
        <div>
          <h1>Quality economics</h1>
          <p className="sub">
            Early-warning ranked by dollar impact. Hotspots include lat/lon for a map, not names only.
          </p>
        </div>
        <button type="button" onClick={load}>
          Refresh
        </button>
      </header>
      {err && (
        <div className="banner banner-error" role="alert">
          {err}
        </div>
      )}
      <section className="panel">
        <h2>Dollar-weighted risk</h2>
        <ol>
          {rank.map((c) => (
            <li key={`${c.pack_id}-${c.cluster_id}`}>
              cluster {c.cluster_id}: ${c.dollar_impact || 0} · volume {c.live_case_count || 0}
            </li>
          ))}
        </ol>
      </section>
      <section className="panel" style={{ marginTop: 16 }}>
        <h2>Hotspot map</h2>
        <svg viewBox="0 0 400 200" width="100%" height="200" role="img" aria-label="hotspot map">
          {(hotspots?.hotspots || []).map((h) => {
            const x = ((h.lon + 180) / 360) * 400;
            const y = ((90 - h.lat) / 180) * 200;
            const r = 4 + Math.min(12, (h.volume || 1) / 2);
            return <circle key={h.region} cx={x} cy={y} r={r} fill="currentColor" />;
          })}
        </svg>
      </section>
    </div>
  );
}
