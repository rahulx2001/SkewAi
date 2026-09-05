import { useState, useEffect } from "react";
import { apiHeaders } from "../src/apiAuth.js";
import { goHash, openCases, openConsole, simulateTraffic } from "../src/ui/opsActions.js";
import {
  IconMic,
  IconHeadset,
  IconFolder,
  IconShield,
  IconAlert,
  IconPulse,
  IconSpark,
  IconLayers,
  IconPhone,
} from "../src/icons.jsx";

export default function UserJourneyGuide() {
  const [activeTab, setActiveTab] = useState("journey");
  const [activeStep, setActiveStep] = useState(0);
  const [simRunning, setSimRunning] = useState(false);
  const [simFeedback, setSimFeedback] = useState(null);
  const [healthInfo, setHealthInfo] = useState(null);

  useEffect(() => {
    fetch("/health", { headers: apiHeaders() })
      .then((r) => r.json())
      .then((d) => setHealthInfo(d))
      .catch(() => {});
  }, []);

  async function handleSimulate(count = 15) {
    setSimRunning(true);
    setSimFeedback(null);
    try {
      const res = await simulateTraffic({ count, speed: "instant" });
      setSimFeedback({
        ok: true,
        msg: `Successfully generated ${res.simulated || count} contacts. Tables, cases, and early warning clusters are populated!`,
      });
    } catch (e) {
      setSimFeedback({ ok: false, msg: String(e.message || e) });
    } finally {
      setSimRunning(false);
    }
  }

  const STEPS = [
    {
      num: "01",
      id: "call",
      title: "Inbound Voice Contact & Intake",
      route: "call",
      icon: IconMic,
      tagline: "High-speed streaming telephony with zero-latency deterministic extraction",
      description:
        "The customer calls in via phone or browser microphone. Real-time Voice Activity Detection (VAD) slices spoken utterances and streams them to the ASR engine. The fast-path deterministic orchestrator extracts vehicle attributes, mechanical symptoms, and complaint categories within milliseconds — without burning expensive LLM tokens.",
      whatHappens: [
        "Streams audio packets bidirectionally through the low-latency WebSocket audio bridge.",
        "Deterministic slot extraction populates entity_1 (Make), entity_2 (Model), entity_3 (Year), category, and description.",
        "Calculates acoustic frustration scores (0–10) based on caller cadence, volume, and conversational stress.",
        "Immediately checks NHTSA safety lexicon: flags emergencies (fire, rollover, unintended acceleration) for instant P1 escalation.",
      ],
      sampleScripts: [
        {
          label: "Safety Emergency (P1)",
          text: "I was driving my 2020 Honda CR-V at 65 mph on the freeway and the engine completely died without warning.",
          tests: "Automatic P1 Critical priority, supervisor safety banner trigger, Highway Stall failure mode.",
        },
        {
          label: "Warranty Defect (Brakes)",
          text: "My front brakes make a loud grinding sound every time I slow down under 20 mph.",
          tests: "Cluster 14 match (SERVICE BRAKES), NHTSA advisory lookup, automatic remedy drafting.",
        },
        {
          label: "Electrical / Auxiliary",
          text: "The driver side power window will not go up after being parked in the rain.",
          tests: "Cluster 31 match (ELECTRICAL SYSTEM), component slot extraction.",
        },
      ],
      ctaLabel: "Launch Voice Agent",
      action: () => goHash("call"),
    },
    {
      num: "02",
      id: "console",
      title: "Live Supervisor Console & Intercept",
      route: "console",
      icon: IconHeadset,
      tagline: "Real-time fleet oversight, human-in-the-loop takeover, and shadow ML verification",
      description:
        "Frontline supervisors monitor active calls in real time. The wallboard displays live turn transcripts, frustration meters, safety alerts, and ML model predictions. If a customer is in distress, the supervisor can immediately intervene and take over the call.",
      whatHappens: [
        "Live audio transcript streams in real time as the caller and AI converse.",
        "Supervisor Takeover: Click 'Takeover' to take direct control of the call, then 'Release' to hand it back to the deterministic AI.",
        "Semantic Shadow Divergence: Compares active hash-based cluster chips with shadow neural MiniLM representations in parallel.",
        "'Shadow looks wrong' button: 1-click human feedback that enqueues misclassifications into the blind eval queue for annotators.",
      ],
      ctaLabel: "Open Live Console",
      action: () => openConsole(),
    },
    {
      num: "03",
      id: "cases",
      title: "Automated Case Creation & RCA Investigations",
      route: "cases",
      icon: IconFolder,
      tagline: "Deterministic root-cause attribution, case deduplication, and anomaly spike detection",
      description:
        "Upon call wrap-up, the system creates a formal Case (cas_...) with structured metadata. Returning callers are automatically attached to existing cases to avoid corpus double-counting. The Investigator agent projects the complaint into domain failure clusters to detect emerging defect spikes.",
      whatHappens: [
        "Structured Case Generation: Populates symptom description, severity (Critical, High, Medium, Low), and vehicle identification.",
        "Deduplication Guards: Matches returning customers within the temporal window using cryptographically hashed contact IDs.",
        "Root-Cause Clustering: Assigns complaints to clusters (e.g. Service Brakes, Air Bags, Electrical System).",
        "Spike Detection & Early Warning: When a cluster exceeds the statistical anomaly threshold, an automated Investigation (inv_...) is launched.",
      ],
      ctaLabel: "Explore Case Queue",
      action: () => openCases(),
    },
    {
      num: "04",
      id: "audits",
      title: "Qubot v2 Audit & Cryptographic Merkle Ledger",
      route: "audits",
      icon: IconShield,
      tagline: "100% grounded assertions, zero hallucination, and tamper-proof hash chains",
      description:
        "Every single agent utterance, recommendation, and state transition is hashed into an append-only cryptographic Merkle tree. Immediately upon call completion, the Qubot v2 auditor scans the transcript against domain database facts to ensure no ungrounded claims or hallucinated advice were given to the caller.",
      whatHappens: [
        "Merkle Tree Anchoring: Generates a tamper-evident root hash for every interaction, verifiable with `make verify-chain`.",
        "Evidence Pinning: Every cited recall advisory, repair procedure, or cluster attribution is pinned to source database rows.",
        "Qubot Audit Report: Flags uncited advisory IDs, unsupported promises, or hallucinated failure modes.",
        "Audit Status Badges: Green badge guarantees mathematical proof of factual groundedness.",
      ],
      ctaLabel: "View Audit Reports",
      action: () => goHash("audits"),
    },
    {
      num: "05",
      id: "warning",
      title: "Early Warning & Quality Economics",
      route: "warning",
      icon: IconAlert,
      tagline: "Proactive recall prevention and Cost of Poor Quality (COPQ) tracking",
      description:
        "Quality and reliability engineers monitor fleet trends before warranty claims turn into regulatory recalls. The Early Warning board quantifies the Cost of Poor Quality (COPQ), tracks anomaly lead times, and surfaces weekly failure spikes.",
      whatHappens: [
        "Anomaly Cluster Radar: Visualizes volume trends, severity multipliers, and week-over-week complaint surges.",
        "Financial COPQ Hotspots: Maps defect clusters to estimated warranty repair liability and projected recall exposure.",
        "Automated RCA Briefs: Generates engineering root-cause briefs with timeline distribution and sample customer complaints.",
        "Investigation Lifecycle: Engineers track investigations from 'Active' to 'Monitoring' or 'Resolved'.",
      ],
      ctaLabel: "View Early Warning Board",
      action: () => goHash("warning"),
    },
    {
      num: "06",
      id: "labels",
      title: "Human Evaluation Desk & Model Governance",
      route: "labels",
      icon: IconSpark,
      tagline: "Statistical Cohen's kappa agreement gates for safe ML upgrades",
      description:
        "Before any new embedding model or clustering algorithm is allowed into production, external domain experts (automotive quality engineers and contact center leads) perform blind double-annotation on real customer complaint pairs.",
      whatHappens: [
        "Blind Annotation Desk: Evaluators see verbatim complaint text with model identities and cluster IDs stripped.",
        "Double-Annotation & Adjudication: Disagreements between Annotator 1 and Annotator 2 are resolved by an independent senior adjudicator.",
        "Cohen's Kappa Gate (kappa >= 0.70): Semantic cutover remains programmatically blocked until agreement standards are met.",
        "Zero Artificial Labels: Strict governance guarantees no synthetic or author-generated labels can bypass the gate.",
      ],
      ctaLabel: "Open Label Desk",
      action: () => goHash("labels"),
    },
  ];

  const ROLES = [
    {
      title: "Frontline Supervisor",
      badge: "Contact Center",
      desc: "Manages live customer queue, monitors speech frustration, and protects caller safety.",
      keySteps: [
        "Keep Live Console open (g then l) to monitor active voice calls in real time.",
        "Watch the frustration meter (0–10) and safety banner for P1 emergencies.",
        "Use 'Takeover' when a caller needs human empathy, then 'Release' back to AI.",
        "Click 'Shadow looks wrong' whenever an AI cluster assignment looks inaccurate.",
      ],
      targetHash: "console",
    },
    {
      title: "Automotive Quality Engineer",
      badge: "Reliability & RCA",
      desc: "Tracks component failure modes, investigates defect clusters, and prevents regulatory recalls.",
      keySteps: [
        "Inspect the Early Warning Board (g then w) for weekly statistical anomaly spikes.",
        "Open Investigations (inv_...) to review automated RCA briefs and sample complaints.",
        "Map warranty failure trends against NHTSA advisories and service campaigns.",
        "Track Cost of Poor Quality (COPQ) dollar liability on the Quality Economics board.",
      ],
      targetHash: "warning",
    },
    {
      title: "Compliance & Risk Officer",
      badge: "Governance & Trust",
      desc: "Verifies regulatory compliance, ensures zero hallucination, and audits tamper-proof evidence.",
      keySteps: [
        "Review Qubot v2 post-contact audit reports on the Audit Reports page (g then a).",
        "Verify that 100% of cited advisories and repair remedies are pinned to database records.",
        "Verify Merkle cryptographic tree heads to confirm tamper-proof audit trails.",
        "Export SOC 2 engineering baseline evidence packages for third-party audits.",
      ],
      targetHash: "audits",
    },
    {
      title: "Machine Learning Engineer",
      badge: "ML Runtime & Platform",
      desc: "Monitors shadow embedding divergence, maintains ONNX runtime, and oversees human evaluation gates.",
      keySteps: [
        "Verify embedding runtime health at /health (ensuring mode=legacy until calibrated).",
        "Monitor rank overlap and divergence rates in the embedding_shadow_comparisons table.",
        "Supervise external annotators on the Label Desk (/ui/#/labels) to achieve kappa >= 0.70.",
        "Execute offline ONNX backfills using scripts.embedding_backfill without altering live clusters.",
      ],
      targetHash: "labels",
    },
  ];

  const curr = STEPS[activeStep];
  const StepIcon = curr.icon;

  return (
    <div className="panel user-journey-guide">
      {/* Top Banner & Quick Controls */}
      <div
        style={{
          display: "flex",
          justifyContent: "space-between",
          alignItems: "flex-start",
          flexWrap: "wrap",
          gap: "16px",
          borderBottom: "1px solid var(--edge)",
          paddingBottom: "20px",
          marginBottom: "24px",
        }}
      >
        <div>
          <div
            style={{
              display: "inline-flex",
              alignItems: "center",
              gap: "8px",
              padding: "4px 10px",
              borderRadius: "20px",
              background: "var(--accent-muted, rgba(216, 212, 204, 0.1))",
              fontSize: "12px",
              fontWeight: "600",
              color: "var(--accent)",
              marginBottom: "8px",
            }}
          >
            <IconSpark style={{ width: 14, height: 14 }} />
            <span>Interactive Platform Walkthrough</span>
          </div>
          <h1 style={{ fontSize: "24px", fontWeight: "600", margin: "0 0 6px 0", color: "var(--ink)" }}>
            Product Guide & End-to-End User Journey
          </h1>
          <p style={{ margin: 0, color: "var(--ink-soft)", fontSize: "14px", maxWidth: "780px" }}>
            Skew AI automates frontline contact center telephony, roots customer complaints into verifiable
            engineering clusters, and generates cryptographically audited root-cause investigations. Follow this
            guide to explore every stage of the system.
          </p>
        </div>

        {/* 1-Click Simulation Tool */}
        <div
          style={{
            background: "var(--bg-panel, #1c1c1a)",
            border: "1px solid var(--edge-strong, #3a3a36)",
            borderRadius: "var(--radius, 12px)",
            padding: "12px 16px",
            minWidth: "260px",
          }}
        >
          <div style={{ fontSize: "12px", fontWeight: "600", color: "var(--ink)", marginBottom: "4px" }}>
            Quick Data Starter
          </div>
          <div style={{ fontSize: "12px", color: "var(--ink-soft)", marginBottom: "10px" }}>
            Populate all tables, cases, and early warning boards instantly with real NHTSA complaints:
          </div>
          <button
            type="button"
            className="btn"
            disabled={simRunning}
            onClick={() => handleSimulate(15)}
            style={{
              width: "100%",
              display: "flex",
              justifyContent: "center",
              alignItems: "center",
              gap: "8px",
              background: "var(--accent, #d8d4cc)",
              color: "#141413",
              fontWeight: "600",
              fontSize: "13px",
              padding: "8px 12px",
            }}
          >
            <IconLayers style={{ width: 14, height: 14 }} />
            {simRunning ? "Simulating Traffic…" : "⚡ Populate 15 Real Contacts"}
          </button>
          {simFeedback && (
            <div
              style={{
                marginTop: "8px",
                fontSize: "11px",
                color: simFeedback.ok ? "var(--ok, #8aab84)" : "var(--danger, #c97a72)",
              }}
            >
              {simFeedback.msg}
            </div>
          )}
        </div>
      </div>

      {/* Main View Mode Selector */}
      <div
        style={{
          display: "flex",
          gap: "8px",
          marginBottom: "24px",
          borderBottom: "1px solid var(--edge)",
          paddingBottom: "8px",
        }}
      >
        <button
          type="button"
          className={`tab-btn ${activeTab === "journey" ? "active" : ""}`}
          onClick={() => setActiveTab("journey")}
          style={{
            padding: "8px 16px",
            borderRadius: "8px",
            border: "none",
            cursor: "pointer",
            background: activeTab === "journey" ? "var(--bg-panel)" : "transparent",
            color: activeTab === "journey" ? "var(--ink)" : "var(--ink-soft)",
            fontWeight: activeTab === "journey" ? "600" : "400",
            fontSize: "14px",
            display: "flex",
            alignItems: "center",
            gap: "8px",
          }}
        >
          <IconPulse style={{ width: 16, height: 16 }} />
          <span>Interactive 6-Stage Journey</span>
        </button>

        <button
          type="button"
          className={`tab-btn ${activeTab === "playbooks" ? "active" : ""}`}
          onClick={() => setActiveTab("playbooks")}
          style={{
            padding: "8px 16px",
            borderRadius: "8px",
            border: "none",
            cursor: "pointer",
            background: activeTab === "playbooks" ? "var(--bg-panel)" : "transparent",
            color: activeTab === "playbooks" ? "var(--ink)" : "var(--ink-soft)",
            fontWeight: activeTab === "playbooks" ? "600" : "400",
            fontSize: "14px",
            display: "flex",
            alignItems: "center",
            gap: "8px",
          }}
        >
          <IconFolder style={{ width: 16, height: 16 }} />
          <span>Role-Based Playbooks</span>
        </button>

        <button
          type="button"
          className={`tab-btn ${activeTab === "scenarios" ? "active" : ""}`}
          onClick={() => setActiveTab("scenarios")}
          style={{
            padding: "8px 16px",
            borderRadius: "8px",
            border: "none",
            cursor: "pointer",
            background: activeTab === "scenarios" ? "var(--bg-panel)" : "transparent",
            color: activeTab === "scenarios" ? "var(--ink)" : "var(--ink-soft)",
            fontWeight: activeTab === "scenarios" ? "600" : "400",
            fontSize: "14px",
            display: "flex",
            alignItems: "center",
            gap: "8px",
          }}
        >
          <IconSpark style={{ width: 16, height: 16 }} />
          <span>Live Test Scenarios</span>
        </button>
      </div>

      {/* TAB 1: 6-STAGE USER JOURNEY */}
      {activeTab === "journey" && (
        <div>
          {/* Stage Stepper Buttons */}
          <div
            style={{
              display: "grid",
              gridTemplateColumns: "repeat(auto-fit, minmax(170px, 1fr))",
              gap: "10px",
              marginBottom: "24px",
            }}
          >
            {STEPS.map((s, idx) => {
              const SIcon = s.icon;
              const isSel = idx === activeStep;
              return (
                <button
                  key={s.id}
                  type="button"
                  onClick={() => setActiveStep(idx)}
                  style={{
                    background: isSel ? "var(--bg-panel, #1c1c1a)" : "var(--bg-raised, #1a1a18)",
                    border: isSel ? "1px solid var(--accent, #d8d4cc)" : "1px solid var(--edge, #2c2c29)",
                    borderRadius: "10px",
                    padding: "12px 14px",
                    textAlign: "left",
                    cursor: "pointer",
                    transition: "all 150ms ease",
                    display: "flex",
                    flexDirection: "column",
                    gap: "6px",
                  }}
                >
                  <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center" }}>
                    <span
                      style={{
                        fontFamily: "var(--mono)",
                        fontSize: "11px",
                        fontWeight: "700",
                        color: isSel ? "var(--accent)" : "var(--ink-faint)",
                      }}
                    >
                      STAGE {s.num}
                    </span>
                    <SIcon style={{ width: 16, height: 16, color: isSel ? "var(--accent)" : "var(--ink-soft)" }} />
                  </div>
                  <div
                    style={{
                      fontSize: "13px",
                      fontWeight: isSel ? "600" : "500",
                      color: isSel ? "var(--ink)" : "var(--ink-soft)",
                      lineHeight: "1.3",
                    }}
                  >
                    {s.title.split("&")[0]}
                  </div>
                </button>
              );
            })}
          </div>

          {/* Current Stage Card */}
          <div
            style={{
              background: "var(--bg-panel, #1c1c1a)",
              border: "1px solid var(--edge-strong, #3a3a36)",
              borderRadius: "var(--radius, 14px)",
              padding: "24px",
            }}
          >
            <div
              style={{
                display: "flex",
                justifyContent: "space-between",
                alignItems: "flex-start",
                flexWrap: "wrap",
                gap: "16px",
                marginBottom: "16px",
              }}
            >
              <div>
                <div style={{ display: "flex", alignItems: "center", gap: "10px", marginBottom: "6px" }}>
                  <div
                    style={{
                      width: "36px",
                      height: "36px",
                      borderRadius: "8px",
                      background: "var(--bg-hover)",
                      display: "flex",
                      alignItems: "center",
                      justifyContent: "center",
                      color: "var(--accent)",
                    }}
                  >
                    <StepIcon style={{ width: 20, height: 20 }} />
                  </div>
                  <div>
                    <span
                      style={{
                        fontFamily: "var(--mono)",
                        fontSize: "12px",
                        color: "var(--ink-faint)",
                        fontWeight: "600",
                        textTransform: "uppercase",
                      }}
                    >
                      Stage {curr.num}
                    </span>
                    <h2 style={{ margin: 0, fontSize: "20px", fontWeight: "600", color: "var(--ink)" }}>
                      {curr.title}
                    </h2>
                  </div>
                </div>
                <div style={{ fontSize: "14px", color: "var(--ink-soft)", fontStyle: "italic", marginTop: "4px" }}>
                  "{curr.tagline}"
                </div>
              </div>

              {/* Direct Route Action Button */}
              <button
                type="button"
                className="btn"
                onClick={curr.action}
                style={{
                  background: "var(--accent, #d8d4cc)",
                  color: "#141413",
                  fontWeight: "600",
                  padding: "10px 18px",
                  borderRadius: "8px",
                  fontSize: "14px",
                  display: "inline-flex",
                  alignItems: "center",
                  gap: "8px",
                  cursor: "pointer",
                }}
              >
                <span>{curr.ctaLabel}</span>
                <span style={{ fontSize: "16px" }}>→</span>
              </button>
            </div>

            <p style={{ fontSize: "14.5px", lineHeight: "1.6", color: "var(--ink)", marginBottom: "20px" }}>
              {curr.description}
            </p>

            {/* What Happens Under the Hood */}
            <div style={{ marginBottom: "24px" }}>
              <div
                style={{
                  fontSize: "13px",
                  fontWeight: "600",
                  color: "var(--ink-soft)",
                  textTransform: "uppercase",
                  letterSpacing: "0.5px",
                  marginBottom: "10px",
                }}
              >
                What happens at this stage:
              </div>
              <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: "10px" }}>
                {curr.whatHappens.map((wh, wIdx) => (
                  <div
                    key={wIdx}
                    style={{
                      background: "var(--bg-raised, #1a1a18)",
                      border: "1px solid var(--edge)",
                      borderRadius: "8px",
                      padding: "10px 14px",
                      fontSize: "13.5px",
                      color: "var(--ink)",
                      display: "flex",
                      alignItems: "flex-start",
                      gap: "10px",
                    }}
                  >
                    <span style={{ color: "var(--ok, #8aab84)", fontWeight: "bold" }}>✓</span>
                    <span>{wh}</span>
                  </div>
                ))}
              </div>
            </div>

            {/* If Stage 1 has sample scripts, show them */}
            {curr.sampleScripts && (
              <div style={{ marginTop: "20px" }}>
                <div
                  style={{
                    fontSize: "13px",
                    fontWeight: "600",
                    color: "var(--ink-soft)",
                    textTransform: "uppercase",
                    letterSpacing: "0.5px",
                    marginBottom: "10px",
                  }}
                >
                  Try speaking or testing these real customer scenarios:
                </div>
                <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr 1fr", gap: "12px" }}>
                  {curr.sampleScripts.map((sc, sIdx) => (
                    <div
                      key={sIdx}
                      style={{
                        background: "var(--bg-raised)",
                        border: "1px solid var(--edge)",
                        borderRadius: "8px",
                        padding: "12px",
                      }}
                    >
                      <div
                        style={{
                          fontSize: "12px",
                          fontWeight: "700",
                          color: "var(--accent)",
                          marginBottom: "6px",
                        }}
                      >
                        {sc.label}
                      </div>
                      <div
                        style={{
                          fontSize: "13px",
                          color: "var(--ink)",
                          fontStyle: "italic",
                          lineHeight: "1.4",
                          marginBottom: "8px",
                        }}
                      >
                        "{sc.text}"
                      </div>
                      <div style={{ fontSize: "11.5px", color: "var(--ink-faint)" }}>
                        <strong>Verifies:</strong> {sc.tests}
                      </div>
                    </div>
                  ))}
                </div>
              </div>
            )}

            {/* Stepper Navigation */}
            <div
              style={{
                display: "flex",
                justifyContent: "space-between",
                alignItems: "center",
                marginTop: "28px",
                paddingTop: "16px",
                borderTop: "1px solid var(--edge)",
              }}
            >
              <button
                type="button"
                className="ghost"
                disabled={activeStep === 0}
                onClick={() => setActiveStep((s) => Math.max(0, s - 1))}
                style={{ opacity: activeStep === 0 ? 0.4 : 1 }}
              >
                ← Previous Stage
              </button>
              <div style={{ fontSize: "13px", color: "var(--ink-faint)", fontFamily: "var(--mono)" }}>
                Stage {activeStep + 1} of {STEPS.length}
              </div>
              <button
                type="button"
                className="ghost"
                disabled={activeStep === STEPS.length - 1}
                onClick={() => setActiveStep((s) => Math.min(STEPS.length - 1, s + 1))}
                style={{ opacity: activeStep === STEPS.length - 1 ? 0.4 : 1 }}
              >
                Next Stage →
              </button>
            </div>
          </div>
        </div>
      )}

      {/* TAB 2: ROLE-BASED PLAYBOOKS */}
      {activeTab === "playbooks" && (
        <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: "16px" }}>
          {ROLES.map((r, idx) => (
            <div
              key={idx}
              style={{
                background: "var(--bg-panel, #1c1c1a)",
                border: "1px solid var(--edge, #2c2c29)",
                borderRadius: "var(--radius, 12px)",
                padding: "20px",
                display: "flex",
                flexDirection: "column",
                justifyContent: "space-between",
              }}
            >
              <div>
                <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: "8px" }}>
                  <h3 style={{ margin: 0, fontSize: "17px", fontWeight: "600", color: "var(--ink)" }}>{r.title}</h3>
                  <span
                    style={{
                      fontSize: "11px",
                      fontWeight: "600",
                      padding: "2px 8px",
                      borderRadius: "12px",
                      background: "var(--accent-muted)",
                      color: "var(--accent)",
                    }}
                  >
                    {r.badge}
                  </span>
                </div>
                <p style={{ fontSize: "13.5px", color: "var(--ink-soft)", margin: "0 0 14px 0", lineHeight: "1.4" }}>
                  {r.desc}
                </p>
                <div style={{ fontSize: "12px", fontWeight: "600", color: "var(--ink-soft)", textTransform: "uppercase", marginBottom: "8px" }}>
                  Daily Operating Protocol:
                </div>
                <ul style={{ margin: "0 0 16px 0", paddingLeft: "20px", fontSize: "13px", color: "var(--ink)", lineHeight: "1.5" }}>
                  {r.keySteps.map((ks, kIdx) => (
                    <li key={kIdx} style={{ marginBottom: "6px" }}>{ks}</li>
                  ))}
                </ul>
              </div>

              <button
                type="button"
                className="btn"
                onClick={() => goHash(r.targetHash)}
                style={{
                  width: "100%",
                  background: "var(--bg-hover)",
                  border: "1px solid var(--edge-strong)",
                  color: "var(--ink)",
                  padding: "8px 14px",
                  fontSize: "13px",
                  fontWeight: "500",
                  cursor: "pointer",
                  borderRadius: "8px",
                }}
              >
                Go to {r.title} Workspace →
              </button>
            </div>
          ))}
        </div>
      )}

      {/* TAB 3: LIVE TEST SCENARIOS */}
      {activeTab === "scenarios" && (
        <div style={{ display: "flex", flexDirection: "column", gap: "16px" }}>
          <div
            style={{
              background: "var(--bg-panel)",
              border: "1px solid var(--edge)",
              borderRadius: "12px",
              padding: "16px 20px",
            }}
          >
            <h3 style={{ margin: "0 0 6px 0", fontSize: "16px", color: "var(--ink)" }}>
              How to Test Skew AI End-to-End Right Now
            </h3>
            <p style={{ margin: 0, fontSize: "13.5px", color: "var(--ink-soft)", lineHeight: "1.5" }}>
              To experience the entire operational pipeline in under 2 minutes, choose one of the guided
              testing flows below:
            </p>
          </div>

          <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr 1fr", gap: "16px" }}>
            <div
              style={{
                background: "var(--bg-panel)",
                border: "1px solid var(--edge)",
                borderRadius: "12px",
                padding: "18px",
              }}
            >
              <div style={{ display: "flex", alignItems: "center", gap: "8px", marginBottom: "8px" }}>
                <span style={{ fontSize: "18px" }}>🎙️</span>
                <h4 style={{ margin: 0, fontSize: "15px", fontWeight: "600", color: "var(--ink)" }}>
                  Path A: Live Voice Call
                </h4>
              </div>
              <p style={{ fontSize: "13px", color: "var(--ink-soft)", lineHeight: "1.4", margin: "0 0 12px 0" }}>
                Use your browser microphone to speak directly with the AI agent. Speak an automotive problem
                and watch slot extraction live.
              </p>
              <ol style={{ fontSize: "12.5px", color: "var(--ink)", margin: "0 0 16px 0", paddingLeft: "18px" }}>
                <li>Click <strong>Start Voice Call</strong> below.</li>
                <li>Allow microphone access in browser.</li>
                <li>Say: <em>"My 2019 CR-V brakes are grinding."</em></li>
                <li>Open <strong>Live Console</strong> in a split tab.</li>
              </ol>
              <button
                type="button"
                className="btn"
                onClick={() => goHash("call")}
                style={{
                  width: "100%",
                  background: "var(--accent)",
                  color: "#141413",
                  fontWeight: "600",
                  padding: "8px",
                  fontSize: "13px",
                }}
              >
                Start Voice Call →
              </button>
            </div>

            <div
              style={{
                background: "var(--bg-panel)",
                border: "1px solid var(--edge)",
                borderRadius: "12px",
                padding: "18px",
              }}
            >
              <div style={{ display: "flex", alignItems: "center", gap: "8px", marginBottom: "8px" }}>
                <span style={{ fontSize: "18px" }}>⚡</span>
                <h4 style={{ margin: 0, fontSize: "15px", fontWeight: "600", color: "var(--ink)" }}>
                  Path B: Batch Fleet Simulation
                </h4>
              </div>
              <p style={{ fontSize: "13px", color: "var(--ink-soft)", lineHeight: "1.4", margin: "0 0 12px 0" }}>
                Instantly replay 25 real historical NHTSA complaints through the intake and triage pipeline to
                populate charts, investigations, and queues.
              </p>
              <ol style={{ fontSize: "12.5px", color: "var(--ink)", margin: "0 0 16px 0", paddingLeft: "18px" }}>
                <li>Click <strong>Run 25-Call Simulation</strong>.</li>
                <li>Observe cases generated in <strong>Case Queue</strong>.</li>
                <li>Check <strong>Early Warning</strong> for cluster spikes.</li>
                <li>Verify <strong>Audit Reports</strong> for green badges.</li>
              </ol>
              <button
                type="button"
                className="btn"
                disabled={simRunning}
                onClick={() => handleSimulate(25)}
                style={{
                  width: "100%",
                  background: "var(--bg-hover)",
                  border: "1px solid var(--edge-strong)",
                  color: "var(--ink)",
                  fontWeight: "600",
                  padding: "8px",
                  fontSize: "13px",
                }}
              >
                {simRunning ? "Simulating…" : "Run 25-Call Simulation →"}
              </button>
            </div>

            <div
              style={{
                background: "var(--bg-panel)",
                border: "1px solid var(--edge)",
                borderRadius: "12px",
                padding: "18px",
              }}
            >
              <div style={{ display: "flex", alignItems: "center", gap: "8px", marginBottom: "8px" }}>
                <span style={{ fontSize: "18px" }}>🛡️</span>
                <h4 style={{ margin: 0, fontSize: "15px", fontWeight: "600", color: "var(--ink)" }}>
                  Path C: Trust & Groundedness Audit
                </h4>
              </div>
              <p style={{ fontSize: "13px", color: "var(--ink-soft)", lineHeight: "1.4", margin: "0 0 12px 0" }}>
                Inspect the mathematical proof of truth: see how Qubot v2 verifies that every AI claim is
                anchored to NHTSA database rows.
              </p>
              <ol style={{ fontSize: "12.5px", color: "var(--ink)", margin: "0 0 16px 0", paddingLeft: "18px" }}>
                <li>Open <strong>Audit Reports</strong> page.</li>
                <li>Select any contact audit report.</li>
                <li>Review pinned evidence IDs & claim bindings.</li>
                <li>Verify Merkle chain integrity in terminal.</li>
              </ol>
              <button
                type="button"
                className="btn"
                onClick={() => goHash("audits")}
                style={{
                  width: "100%",
                  background: "var(--bg-hover)",
                  border: "1px solid var(--edge-strong)",
                  color: "var(--ink)",
                  fontWeight: "600",
                  padding: "8px",
                  fontSize: "13px",
                }}
              >
                Open Audit Reports →
              </button>
            </div>
          </div>
        </div>
      )}

      {/* Footer System Status Bar */}
      <div
        style={{
          marginTop: "32px",
          padding: "14px 18px",
          background: "var(--bg-raised, #1a1a18)",
          border: "1px solid var(--edge, #2c2c29)",
          borderRadius: "10px",
          display: "flex",
          justifyContent: "space-between",
          alignItems: "center",
          flexWrap: "wrap",
          gap: "12px",
          fontSize: "12.5px",
          color: "var(--ink-soft)",
        }}
      >
        <div style={{ display: "flex", alignItems: "center", gap: "16px", flexWrap: "wrap" }}>
          <span>
            <strong>Active Pack:</strong>{" "}
            <code style={{ fontFamily: "var(--mono)", color: "var(--ink)" }}>
              {healthInfo?.active_pack || "automotive_nhtsa"}
            </code>
          </span>
          <span>
            <strong>Embedding Mode:</strong>{" "}
            <code style={{ fontFamily: "var(--mono)", color: "var(--ink)" }}>
              {healthInfo?.embedding?.mode || "legacy"} (customer-visible: {healthInfo?.embedding?.visible_provider || "hash"})
            </code>
          </span>
          <span>
            <strong>Audit Engine:</strong>{" "}
            <span style={{ color: "var(--ok, #8aab84)", fontWeight: "600" }}>● Qubot v2 Active</span>
          </span>
          <span>
            <strong>Merkle Ledger:</strong>{" "}
            <span style={{ color: "var(--ok, #8aab84)", fontWeight: "600" }}>● Append-Only Sealed</span>
          </span>
        </div>

        <div style={{ display: "flex", gap: "8px" }}>
          <button
            type="button"
            className="ghost"
            onClick={() => goHash("settings")}
            style={{ fontSize: "12px", padding: "4px 8px" }}
          >
            Pack Settings
          </button>
          <button
            type="button"
            className="ghost"
            onClick={() => goHash("command")}
            style={{ fontSize: "12px", padding: "4px 8px" }}
          >
            Command Center
          </button>
        </div>
      </div>
    </div>
  );
}
