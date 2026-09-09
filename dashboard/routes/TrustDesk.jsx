import AuditReports from "./AuditReports.jsx";
import TrustPipeline from "./TrustPipeline.jsx";
import LabelDesk from "./LabelDesk.jsx";
import { hashQueryObject, patchHashQuery } from "../src/ui/opsActions.js";

const TABS = [
  { id: "reports", label: "Reports" },
  { id: "lineage", label: "Lineage" },
  { id: "labels", label: "Labels" },
];

export default function TrustDesk({ refreshKey }) {
  const tab = hashQueryObject().tab || "reports";

  return (
    <div>
      <header className="page-header">
        <div>
          <h1>Trust</h1>
          <p className="sub">Audit reports, figure lineage, and eval labels in one desk.</p>
        </div>
      </header>
      <div className="tabs" role="tablist" aria-label="Trust desk">
        {TABS.map((t) => (
          <button
            key={t.id}
            type="button"
            role="tab"
            aria-selected={tab === t.id}
            className={"tab" + (tab === t.id ? " active" : "")}
            onClick={() => patchHashQuery({ tab: t.id })}
          >
            {t.label}
          </button>
        ))}
      </div>
      {tab === "reports" && <AuditReports refreshKey={refreshKey} embedded />}
      {tab === "lineage" && <TrustPipeline refreshKey={refreshKey} embedded />}
      {tab === "labels" && <LabelDesk refreshKey={refreshKey} embedded />}
    </div>
  );
}
