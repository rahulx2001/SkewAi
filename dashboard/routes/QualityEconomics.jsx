import { useCallback, useEffect, useState } from "react";
import { apiHeaders } from "../src/apiAuth.js";
import { includeSimQuery, openWarning } from "../src/ui/opsActions.js";
import { packLabel } from "../src/ui/labels.js";

export default function QualityEconomics({ embedded }) {
  const [rank, setRank] = useState([]);
  const [hotspots, setHotspots] = useState(null);
  const [err, setErr] = useState("");

  const load = useCallback(async () => {
    setErr("");
    try {
      const h = apiHeaders();
      const [a, b] = await Promise.all([
        fetch(`/api/frontline/copq/rank?include_simulated=${includeSimQuery()}`, { headers: h }),
        fetch("/api/frontline/analytics/hotspots-map", { headers: h }),
      ]);
      if (!a.ok) throw new Error(`copq ${a.status}`);
      if (!b.ok) throw new Error(`hotspots ${b.status}`);
      setRank((await a.json()).clusters || []);
      setHotspots(await b.json());
    } catch (e) {
      setErr(String(e.message || e));
    }
  }, []);

  useEffect(() => {
    load();
  }, [load]);

  return (
    <div>
      {!embedded && (
        <header className="page-header">
          <div>
            <h1>Quality economics</h1>
            <p className="sub">
              Cluster risk ranked by pack cost model dollars. Map is a sketch of volume, not a GIS product.
            </p>
          </div>
          <button type="button" onClick={load}>
            Refresh
          </button>
        </header>
      )}
      {err && (
        <div className="banner banner-error" role="alert">
          {err}
        </div>
      )}
      <section className="panel">
        <h2>Dollar-weighted risk</h2>
        {rank.length === 0 ? (
          <p className="sub">No dollar-weighted clusters yet.</p>
        ) : (
          <div className="table-wrap">
            <table>
              <thead>
                <tr>
                  <th>Pack</th>
                  <th>Cluster</th>
                  <th>Volume</th>
                  <th>Critical</th>
                  <th>Dollars</th>
                </tr>
              </thead>
              <tbody>
                {rank.map((c) => (
                  <tr
                    key={`${c.pack_id}-${c.cluster_id}`}
                    style={{ cursor: "pointer" }}
                    tabIndex={0}
                    onClick={() => openWarning({ clusterId: c.cluster_id, packId: c.pack_id, tab: "risk" })}
                    onKeyDown={(e) => {
                      if (e.key === "Enter" || e.key === " ") {
                        e.preventDefault();
                        openWarning({ clusterId: c.cluster_id, packId: c.pack_id, tab: "risk" });
                      }
                    }}
                  >
                    <td>{packLabel(c.pack_id)}</td>
                    <td className="mono">{c.cluster_id}</td>
                    <td className="mono">{c.live_case_count || 0}</td>
                    <td className="mono">{c.critical_count || 0}</td>
                    <td className="mono">${Number(c.dollar_impact || 0).toLocaleString()}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </section>
      {(hotspots?.hotspots || []).length > 0 && (
        <section className="panel" style={{ marginTop: 16 }}>
          <h2>Hotspot sketch</h2>
          <svg viewBox="0 0 400 200" width="100%" height="200" role="img" aria-label="hotspot map">
            {(hotspots?.hotspots || []).map((h) => {
              const x = ((h.lon + 180) / 360) * 400;
              const y = ((90 - h.lat) / 180) * 200;
              const r = 4 + Math.min(12, (h.volume || 1) / 2);
              return (
                <circle key={h.region} cx={x} cy={y} r={r} fill="currentColor">
                  <title>{`${h.region || "region"} · vol ${h.volume || 0}`}</title>
                </circle>
              );
            })}
          </svg>
        </section>
      )}
    </div>
  );
}
