import { useCallback, useState } from "react";
import { apiHeaders } from "../src/apiAuth.js";

export default function LabelDesk() {
  const [annotator, setAnnotator] = useState("human-");
  const [item, setItem] = useState(null);
  const [classes, setClasses] = useState([]);
  const [chosen, setChosen] = useState("");
  const [status, setStatus] = useState("");

  const loadNext = useCallback(async () => {
    setStatus("");
    const r = await fetch(
      `/api/frontline/eval/labels/next?annotator_id=${encodeURIComponent(annotator)}`,
      { headers: apiHeaders() }
    );
    if (!r.ok) {
      setStatus("Could not load an item.");
      return;
    }
    const data = await r.json();
    setItem(data.item);
    setClasses(data.classes || []);
    setChosen("");
    if (!data.item) setStatus("Queue empty.");
  }, [annotator]);

  async function submit(e) {
    e.preventDefault();
    if (!item || !chosen) return;
    const r = await fetch("/api/frontline/eval/labels", {
      method: "POST",
      headers: { ...apiHeaders(), "Content-Type": "application/json" },
      body: JSON.stringify({
        eval_id: item.eval_id,
        annotator_id: annotator,
        label: chosen,
        source_record_id: item.source_record_id,
      }),
    });
    if (!r.ok) {
      setStatus("Submit failed. Check annotator id (must start with human-).");
      return;
    }
    setStatus("Saved.");
    loadNext();
  }

  return (
    <div className="page">
      <header className="page-head">
        <h1>Eval labels</h1>
        <p className="faint">
          Blind labeling. You see complaint text and entity context only — not
          similarity scores, model output, or current clusters.
        </p>
      </header>
      <div className="panel" style={{ maxWidth: 880 }}>
        <div className="slot-row">
          <span className="k">annotator</span>
          <input
            value={annotator}
            onChange={(e) => setAnnotator(e.target.value)}
            placeholder="human-yourname"
            aria-label="Annotator id"
          />
        </div>
        <button type="button" className="primary" onClick={loadNext} style={{ marginTop: 12 }}>
          Next unlabeled pair
        </button>
        {item && (
          <form onSubmit={submit} style={{ marginTop: 20 }}>
            <div className="slot-row">
              <span className="k">category</span>
              <span className="v">{item.category || "—"}</span>
            </div>
            <div className="slot-row">
              <span className="k">entity</span>
              <span className="v">
                {[item.entity_2, item.entity_3].filter(Boolean).join(" / ") || "—"}
              </span>
            </div>
            <div className="activity-card" style={{ marginTop: 12 }}>
              <div className="faint">Query</div>
              <p>{item.query_text}</p>
            </div>
            <div className="activity-card" style={{ marginTop: 8 }}>
              <div className="faint">Candidate</div>
              <p>{item.candidate_text}</p>
            </div>
            <fieldset style={{ marginTop: 16, border: 0, padding: 0 }}>
              <legend className="faint">Class</legend>
              {classes.map((c) => (
                <label key={c} style={{ display: "block", marginTop: 6 }}>
                  <input
                    type="radio"
                    name="eval_class"
                    value={c}
                    checked={chosen === c}
                    onChange={() => setChosen(c)}
                  />{" "}
                  {c}
                </label>
              ))}
            </fieldset>
            <button type="submit" className="primary" style={{ marginTop: 16 }} disabled={!chosen}>
              Save label
            </button>
          </form>
        )}
        {status && <p className="faint" style={{ marginTop: 12 }}>{status}</p>}
      </div>
    </div>
  );
}
