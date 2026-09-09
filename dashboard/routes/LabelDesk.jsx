import { useCallback, useEffect, useState } from "react";
import { apiHeaders } from "../src/apiAuth.js";
import { humanizeKey } from "../src/ui/labels.js";

const DEFAULT_CLASSES = [
  "paraphrase_positive",
  "hard_negative_same_category",
  "hard_negative_same_components",
  "multi_symptom",
  "negation_mention",
  "safety_true_positive",
  "safety_false_positive_trigger",
  "novel_true",
  "novel_false",
  "cross_entity_same_symptom",
];

export default function LabelDesk({ embedded }) {
  const [annotator, setAnnotator] = useState("human-operator");
  const [item, setItem] = useState(null);
  const [classes, setClasses] = useState(DEFAULT_CLASSES);
  const [chosen, setChosen] = useState("");
  const [status, setStatus] = useState("");

  // Agreement and acceptance gate state
  const [agreementData, setAgreementData] = useState(null);
  const [loadingAgreement, setLoadingAgreement] = useState(false);

  // Adjudication state
  const [adjEvalId, setAdjEvalId] = useState("");
  const [adjAnnotator, setAdjAnnotator] = useState("human-adjudicator");
  const [adjLabel, setAdjLabel] = useState("paraphrase_positive");
  const [adjNotes, setAdjNotes] = useState("");
  const [adjStatus, setAdjStatus] = useState("");

  const loadAgreement = useCallback(async () => {
    setLoadingAgreement(true);
    try {
      const r = await fetch("/api/frontline/eval/labels/agreement", { headers: apiHeaders() });
      if (r.ok) {
        const d = await r.json();
        setAgreementData(d);
      }
    } catch {
      // ignore network error
    } finally {
      setLoadingAgreement(false);
    }
  }, []);

  useEffect(() => {
    loadAgreement();
  }, [loadAgreement]);

  const loadNext = useCallback(async () => {
    setStatus("");
    const r = await fetch(
      `/api/frontline/eval/labels/next?annotator_id=${encodeURIComponent(annotator)}`,
      { headers: apiHeaders() }
    );
    if (!r.ok) {
      setStatus(
        r.status === 422
          ? "Annotator id must be at least 7 characters (e.g. human-you)."
          : "Could not load an item.",
      );
      return;
    }
    const data = await r.json();
    setItem(data.item);
    if (data.classes && data.classes.length > 0) {
      setClasses(data.classes);
    }
    setChosen("");
    if (!data.item) setStatus("Queue empty.");
  }, [annotator]);

  useEffect(() => {
    loadNext();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

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
    loadAgreement();
  }

  async function submitAdjudication(e) {
    e.preventDefault();
    if (!adjEvalId || !adjAnnotator || !adjLabel) return;
    setAdjStatus("");
    try {
      const r = await fetch("/api/frontline/eval/labels/adjudicate", {
        method: "POST",
        headers: { ...apiHeaders(), "Content-Type": "application/json" },
        body: JSON.stringify({
          eval_id: adjEvalId,
          adjudicator_id: adjAnnotator,
          label: adjLabel,
          notes: adjNotes,
        }),
      });
      if (!r.ok) {
        setAdjStatus("Adjudication failed. Adjudicator id must start with human- and eval_id must exist.");
        return;
      }
      setAdjStatus("Adjudication recorded successfully.");
      setAdjEvalId("");
      setAdjNotes("");
      loadAgreement();
    } catch (err) {
      setAdjStatus(String(err.message || err));
    }
  }

  const agr = agreementData?.agreement;
  const elig = agreementData?.eligibility;
  const isAcceptanceReady = Boolean(elig?.acceptance_ready);

  return (
    <div className="page">
      {!embedded && (
        <header className="page-head">
          <h1>Eval Labels & Quality Gates</h1>
          <p className="faint">
            Blind human annotation and Cohen's Kappa agreement gates. Annotators evaluate query-candidate pairs without model hints.
          </p>
        </header>
      )}

      {/* Agreement & Acceptance Gate Summary */}
      <div className="panel" style={{ maxWidth: 880, marginBottom: 24 }}>
        <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: 16 }}>
          <h2 style={{ fontSize: 16, fontWeight: 600, margin: 0 }}>Cohen's Kappa Gate & Acceptance Readiness</h2>
          <button
            type="button"
            className="btn"
            onClick={loadAgreement}
            disabled={loadingAgreement}
            style={{ fontSize: 12, padding: "4px 10px" }}
          >
            {loadingAgreement ? "Refreshing…" : "↻ Refresh Metrics"}
          </button>
        </div>

        <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(180px, 1fr))", gap: 12, marginBottom: 16 }}>
          <div style={{ padding: 12, background: "var(--bg-subtle, rgba(255,255,255,0.03))", borderRadius: 8, border: "1px solid var(--edge)" }}>
            <div className="faint" style={{ fontSize: 11, textTransform: "uppercase" }}>Required Kappa (Gate)</div>
            <div style={{ fontSize: 20, fontWeight: 700, marginTop: 4 }}>
              ≥ {agr?.kappa_min ?? 0.7}
            </div>
            <div className="faint" style={{ fontSize: 11, marginTop: 2 }}>Inter-rater threshold</div>
          </div>

          <div style={{ padding: 12, background: "var(--bg-subtle, rgba(255,255,255,0.03))", borderRadius: 8, border: "1px solid var(--edge)" }}>
            <div className="faint" style={{ fontSize: 11, textTransform: "uppercase" }}>Paired Annotations</div>
            <div style={{ fontSize: 20, fontWeight: 700, marginTop: 4 }}>
              {agr?.paired_items ?? 0}
            </div>
            <div className="faint" style={{ fontSize: 11, marginTop: 2 }}>Multi-annotator pairs</div>
          </div>

          <div style={{ padding: 12, background: "var(--bg-subtle, rgba(255,255,255,0.03))", borderRadius: 8, border: "1px solid var(--edge)" }}>
            <div className="faint" style={{ fontSize: 11, textTransform: "uppercase" }}>Acceptance Gate Status</div>
            <div style={{ marginTop: 6 }}>
              {isAcceptanceReady ? (
                <span style={{ background: "rgba(138, 171, 132, 0.2)", color: "var(--ok, #8aab84)", padding: "3px 8px", borderRadius: 4, fontWeight: 600, fontSize: 13 }}>
                  ✓ ACCEPTANCE READY
                </span>
              ) : (
                <span style={{ background: "rgba(201, 122, 114, 0.2)", color: "var(--danger, #c97a72)", padding: "3px 8px", borderRadius: 4, fontWeight: 600, fontSize: 13 }}>
                  BLOCKED (Pending κ ≥ 0.70)
                </span>
              )}
            </div>
            <div className="faint" style={{ fontSize: 11, marginTop: 4 }}>
              {elig?.rules_version ? `Rules: ${elig.rules_version}` : "Decision rules active"}
            </div>
          </div>
        </div>

        {agr?.per_class && (
          <div style={{ marginTop: 12 }}>
            <div className="faint" style={{ fontSize: 12, marginBottom: 6, fontWeight: 600 }}>Class Agreement Breakdown</div>
            <div style={{ maxHeight: 180, overflowY: "auto", border: "1px solid var(--edge)", borderRadius: 6 }}>
              <table style={{ width: "100%", fontSize: 12, borderCollapse: "collapse" }}>
                <thead>
                  <tr style={{ background: "var(--bg-subtle, rgba(255,255,255,0.02))", textAlign: "left" }}>
                    <th style={{ padding: "6px 10px" }}>Class</th>
                    <th style={{ padding: "6px 10px" }}>Paired</th>
                    <th style={{ padding: "6px 10px" }}>Cohen's κ</th>
                    <th style={{ padding: "6px 10px" }}>Eligibility</th>
                  </tr>
                </thead>
                <tbody>
                  {Object.entries(agr.per_class).map(([cls, stat]) => (
                    <tr key={cls} style={{ borderTop: "1px solid var(--edge)" }}>
                      <td style={{ padding: "6px 10px" }}>{humanizeKey(cls)}</td>
                      <td style={{ padding: "6px 10px" }}>{stat.n_paired}</td>
                      <td style={{ padding: "6px 10px" }}>
                        {stat.cohens_kappa !== null && stat.cohens_kappa !== undefined ? Number(stat.cohens_kappa).toFixed(3) : "—"}
                      </td>
                      <td style={{ padding: "6px 10px" }}>
                        {stat.eligible ? (
                          <span style={{ color: "var(--ok, #8aab84)" }}>✓ Eligible</span>
                        ) : (
                          <span className="faint">Pending</span>
                        )}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </div>
        )}
      </div>

      {/* Blind Labeling Queue */}
      <div className="panel" style={{ maxWidth: 880, marginBottom: 24 }}>
        <h2 style={{ fontSize: 16, fontWeight: 600, margin: "0 0 12px 0" }}>Blind Labeling Queue</h2>
        <div className="slot-row">
          <label htmlFor="annotator-input" className="k">annotator</label>
          <input
            id="annotator-input"
            value={annotator}
            onChange={(e) => setAnnotator(e.target.value)}
            placeholder="human-yourname"
            aria-label="Annotator id"
          />
        </div>
        <button
          type="button"
          className="primary"
          onClick={loadNext}
          style={{ marginTop: 12 }}
          disabled={annotator.trim().length < 7}
        >
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
                    aria-label={`Label class ${humanizeKey(c)}`}
                  />{" "}
                  {humanizeKey(c)}
                </label>
              ))}
            </fieldset>
            <button type="submit" className="primary" style={{ marginTop: 16 }} disabled={!chosen}>
              Save label
            </button>
          </form>
        )}
        {status && (
          <p className={/fail|could not|must/i.test(status) ? "err-text" : "faint"} style={{ marginTop: 12 }}>
            {status}
          </p>
        )}
      </div>

      {/* Senior Adjudication Form */}
      <div className="panel" style={{ maxWidth: 880 }}>
        <h2 style={{ fontSize: 16, fontWeight: 600, margin: "0 0 8px 0" }}>Senior Adjudication</h2>
        <p className="faint" style={{ fontSize: 13, margin: "0 0 16px 0" }}>
          Resolve disputed or divergent pair evaluations. Adjudications override annotator disagreements for acceptance eligibility.
        </p>

        <form onSubmit={submitAdjudication}>
          <div className="slot-row">
            <label htmlFor="adj-eval-id" className="k">eval_id</label>
            <input
              id="adj-eval-id"
              value={adjEvalId}
              onChange={(e) => setAdjEvalId(e.target.value)}
              placeholder="e.g. eval-c4a7f2"
              aria-label="Evaluation ID to adjudicate"
              required
            />
          </div>

          <div className="slot-row" style={{ marginTop: 10 }}>
            <label htmlFor="adj-annotator" className="k">adjudicator</label>
            <input
              id="adj-annotator"
              value={adjAnnotator}
              onChange={(e) => setAdjAnnotator(e.target.value)}
              placeholder="human-adjudicator"
              aria-label="Adjudicator identity"
              required
            />
          </div>

          <div className="slot-row" style={{ marginTop: 10 }}>
            <label htmlFor="adj-label-select" className="k">adjudicated class</label>
            <select
              id="adj-label-select"
              value={adjLabel}
              onChange={(e) => setAdjLabel(e.target.value)}
              aria-label="Adjudicated class"
              style={{
                background: "var(--bg-input, #1c1c1a)",
                color: "var(--ink)",
                border: "1px solid var(--edge)",
                borderRadius: 4,
                padding: "6px 10px",
              }}
            >
              {classes.map((c) => (
                <option key={c} value={c}>
                  {humanizeKey(c)}
                </option>
              ))}
            </select>
          </div>

          <div className="slot-row" style={{ marginTop: 10 }}>
            <label htmlFor="adj-notes" className="k">rationale / notes</label>
            <input
              id="adj-notes"
              value={adjNotes}
              onChange={(e) => setAdjNotes(e.target.value)}
              placeholder="Reason for adjudication resolution"
              aria-label="Adjudication notes"
            />
          </div>

          <button
            type="submit"
            className="primary"
            style={{ marginTop: 16 }}
            disabled={!adjEvalId || !adjAnnotator}
          >
            Submit Adjudication
          </button>
        </form>

        {adjStatus && (
          <p className="faint" style={{ marginTop: 12, color: adjStatus.includes("success") ? "var(--ok, #8aab84)" : "var(--danger, #c97a72)" }}>
            {adjStatus}
          </p>
        )}
      </div>
    </div>
  );
}
