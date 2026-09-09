import { useEffect, useState } from "react";
import { apiHeaders, fetchMe, getStoredApiKey } from "../src/apiAuth.js";
import { goHash, simulateTraffic } from "../src/ui/opsActions.js";
import { Banner, bannerTone } from "../src/ui/Feedback.jsx";

/**
 * Short operator checklist matching the eight-item console, not a product brochure.
 */
export default function UserJourneyGuide() {
  const [simRunning, setSimRunning] = useState(false);
  const [simFeedback, setSimFeedback] = useState(null);
  const [healthInfo, setHealthInfo] = useState(null);
  const [signedIn, setSignedIn] = useState(false);

  useEffect(() => {
    fetch("/health", { headers: apiHeaders() })
      .then((r) => r.json())
      .then((d) => setHealthInfo(d))
      .catch(() => {});
    fetchMe()
      .then((m) => setSignedIn(Boolean(m?.signed_in)))
      .catch(() => setSignedIn(false));
  }, []);

  async function handleSimulate(count = 15) {
    if (
      typeof window !== "undefined" &&
      !window.confirm(
        `This generates ${count} synthetic contacts (channel=simulated). They stay out of live metrics until you check Include simulated. Proceed?`,
      )
    ) {
      return;
    }
    setSimRunning(true);
    setSimFeedback(null);
    try {
      const res = await simulateTraffic({ count, speed: "instant" });
      setSimFeedback({
        ok: true,
        msg: `Seeded ${res.completed ?? count} simulated contacts. Turn on Include simulated on Case queue or Early warning to see them.`,
      });
    } catch (e) {
      setSimFeedback({ ok: false, msg: String(e.message || e) });
    } finally {
      setSimRunning(false);
    }
  }

  return (
    <div className="page-enter">
      <header className="page-header">
        <div>
          <h1>Operator guide</h1>
          <p className="sub">
            Three loops. The sidebar is Command, Voice, Live console, Cases, Early warning, Trust,
            Platform, Settings. Hidden tools (lab, pack builder, labels) live under those desks.
          </p>
        </div>
      </header>

      {healthInfo?.auth_required && !getStoredApiKey() && !signedIn && (
        <Banner tone="error">
          API key required.{" "}
          <button type="button" className="ghost" onClick={() => goHash("settings")}>
            Open Settings
          </button>
        </Banner>
      )}

      {simFeedback && (
        <Banner tone={simFeedback.ok ? "ok" : bannerTone(simFeedback.msg)}>
          {simFeedback.msg}
        </Banner>
      )}

      <section className="panel" style={{ marginBottom: 16 }}>
        <h2>1. Take a contact</h2>
        <p>
          Start a voice or text contact, watch it on the live console, then open the case it creates.
        </p>
        <ol>
          <li>Voice agent: start a call (or text contact if this browser has no speech API).</li>
          <li>Say something like: “My 2019 CR-V brakes grind under 20 mph.”</li>
          <li>Live console: take over if frustration spikes, then release back to the agent.</li>
          <li>Case queue: open the new case, set status, add a note.</li>
        </ol>
        <div className="row" style={{ gap: 8, marginTop: 12 }}>
          <button type="button" className="primary" onClick={() => goHash("call")}>
            Start with voice
          </button>
        </div>
      </section>

      <section className="panel" style={{ marginBottom: 16 }}>
        <h2>2. Watch risk</h2>
        <p>
          Early warning is clusters, investigations, and a friction proxy (not survey NPS). Click a
          cluster to open matching cases.
        </p>
        <ol>
          <li>Risk tab: clusters and the weekly funnel.</li>
          <li>Insights: friction proxy and product-gap board.</li>
          <li>Dollars: pack cost-model ranking (a sketch, not a GIS product).</li>
        </ol>
        <div className="row" style={{ gap: 8, marginTop: 12 }}>
          <button type="button" className="primary" onClick={() => goHash("warning")}>
            Open early warning
          </button>
        </div>
      </section>

      <section className="panel" style={{ marginBottom: 16 }}>
        <h2>3. Trust the output</h2>
        <p>
          Trust desk holds audit reports, figure lineage, and eval labels. Labels are a tab, not a
          separate page.
        </p>
        <ol>
          <li>Reports: groundedness write-up for a contact.</li>
          <li>Lineage: why a KPI number is trusted.</li>
          <li>Labels: blind pairs until kappa meets the gate.</li>
        </ol>
        <div className="row" style={{ gap: 8, marginTop: 12 }}>
          <button type="button" className="primary" onClick={() => goHash("audits")}>
            Open Trust
          </button>
        </div>
      </section>

      <section className="panel" style={{ marginBottom: 16 }}>
        <h2>Demo data</h2>
        <p>
          Simulated contacts are tagged <span className="mono">channel=simulated</span> and excluded
          from live metrics until you check Include simulated on Case queue or Early warning.
        </p>
        <div className="row" style={{ gap: 8, marginTop: 12 }}>
          <button type="button" className="primary" disabled={simRunning} onClick={() => handleSimulate(15)}>
            {simRunning ? "Seeding…" : "Seed 15 simulated contacts"}
          </button>
        </div>
      </section>

      <section className="panel" style={{ marginBottom: 16 }}>
        <h2>Where the rest went</h2>
        <ul>
          <li>
            Pack builder and Feature lab: Settings tabs. Lab is for booking, drain, coach, and other
            experiments.
          </li>
          <li>Platform learning and warehouse ops: Platform desk.</li>
          <li>
            Keyboard: <kbd>g</kbd> then <kbd>c</kbd> command, <kbd>v</kbd> voice, <kbd>l</kbd>{" "}
            console, <kbd>q</kbd> queue, <kbd>w</kbd> warning, <kbd>a</kbd> trust, <kbd>p</kbd>{" "}
            platform, <kbd>s</kbd> settings. <kbd>?</kbd> for the full sheet.
          </li>
        </ul>
        {healthInfo?.active_pack && (
          <p className="muted" style={{ marginTop: 12 }}>
            Active pack <span className="mono">{healthInfo.active_pack}</span>
            {healthInfo.embedding?.mode ? ` · embedding ${healthInfo.embedding.mode}` : ""}
            {healthInfo.llm_available === false ? " · LLM off" : ""}
          </p>
        )}
      </section>
    </div>
  );
}
