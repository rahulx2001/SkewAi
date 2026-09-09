import PlatformOS from "./PlatformOS.jsx";
import EnterpriseOps from "./EnterpriseOps.jsx";
import { hashQueryObject, patchHashQuery } from "../src/ui/opsActions.js";

const TABS = [
  { id: "learn", label: "Learning" },
  { id: "ops", label: "Ops" },
];

export default function PlatformDesk({ refreshKey }) {
  const tab = hashQueryObject().tab || "learn";

  return (
    <div>
      <header className="page-header">
        <div>
          <h1>Platform</h1>
          <p className="sub">Learning proposals, deployments, and warehouse ops.</p>
        </div>
      </header>
      <div className="tabs" role="tablist" aria-label="Platform">
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
      {tab === "ops" ? (
        <EnterpriseOps refreshKey={refreshKey} embedded />
      ) : (
        <PlatformOS refreshKey={refreshKey} embedded />
      )}
    </div>
  );
}
