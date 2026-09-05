import { useEffect, useRef, useState } from "react";
import { apiHeaders, sendWsAuth, withApiKeyQuery } from "../src/apiAuth.js";
import { SS, consumeSession } from "../src/ui/opsActions.js";

const AGENT_BADGE_CLASS = {
  intake: "intake",
  sentiment: "sentiment",
  triage: "triage",
  sentinel: "sentinel",
  investigator: "investigator",
  case: "case",
  orchestrator: "orchestrator",
  supervisor: "supervisor",
};

const FRUSTRATION_THRESHOLD = 0.65;

export default function LiveContactConsole() {
  const [interactions, setInteractions] = useState([]); // active list from polling
  const [selectedId, setSelectedId] = useState(null);
  const [turns, setTurns] = useState({}); // iid → [{speaker, text, ts}]
  const [activities, setActivities] = useState({}); // iid → [activity]
  const [slots, setSlots] = useState({}); // iid → {key:value}
  const [takenOver, setTakenOver] = useState({}); // iid → bool
  const [frustration, setFrustration] = useState({}); // iid → number
  const [reply, setReply] = useState("");
  const [pack, setPack] = useState(null);
  const [wsStatus, setWsStatus] = useState("connecting");

  const wsRef = useRef(null);
  const pollRef = useRef(null);

  const selected = interactions.find((i) => i.interaction_id === selectedId);

  // Deep-link: Command Center can pre-select a live contact.
  useEffect(() => {
    const pick = consumeSession(SS.consoleSelect);
    if (pick) setSelectedId(pick);
  }, []);

  // ── Poll active interactions every 2s ────────────────────────────────
  useEffect(() => {
    let mounted = true;

    async function poll() {
      try {
        const r = await fetch("/api/interactions?status=active&limit=50", {
          headers: apiHeaders(),
        });
        if (!r.ok) return;
        const data = await r.json();
        if (!mounted) return;
        const list = data.interactions || [];
        setInteractions(list);
        // Keep deep-linked selection if still active.
        setSelectedId((cur) => {
          if (cur && list.some((i) => i.interaction_id === cur)) return cur;
          return cur;
        });
      } catch {
        /* network blip — try again next tick */
      }
    }
    poll();
    pollRef.current = setInterval(poll, 2000);
    return () => {
      mounted = false;
      clearInterval(pollRef.current);
    };
  }, []);

  // ── Connect to /ws/console (reconnect with backoff on drop) ─────────
  useEffect(() => {
    let cancelled = false;
    let retryTimer = null;
    let attempt = 0;
    const maxAttempts = 12;

    function handleMessage(ev) {
      let msg;
      try {
        msg = JSON.parse(ev.data);
      } catch {
        return;
      }
      if (msg.type === "agent_activity") {
        const iid = msg.interaction_id;
        const sum = msg.output_summary || msg.summary || msg.input_summary || "";
        const fp = `${msg.agent || ""}|${msg.action_type || ""}|${sum}`;
        setActivities((prev) => {
          const list = prev[iid] || [];
          const dup = list.some((a) => {
            if (msg.action_id && a.action_id && a.action_id === msg.action_id) return true;
            const as = a.output_summary || a.summary || a.input_summary || "";
            return `${a.agent || ""}|${a.action_type || ""}|${as}` === fp;
          });
          if (dup) return prev;
          const normalized = {
            ...msg,
            summary: sum,
            output_summary: sum,
          };
          return { ...prev, [iid]: [...list, normalized].slice(-200) };
        });
      } else if (msg.type === "agent_turn" || msg.type === "customer_turn") {
        const iid = msg.interaction_id;
        setTurns((prev) => ({
          ...prev,
          [iid]: [
            ...(prev[iid] || []),
            { speaker: msg.speaker || (msg.type === "customer_turn" ? "customer" : "agent"), text: msg.text, ts: msg.ts },
          ].slice(-200),
        }));
      } else if (msg.type === "slots_update") {
        const iid = msg.interaction_id;
        setSlots((prev) => ({ ...prev, [iid]: msg.slots || {} }));
      } else if (msg.type === "frustration_update") {
        const iid = msg.interaction_id;
        setFrustration((prev) => ({ ...prev, [iid]: msg.value }));
      } else if (msg.type === "error") {
        console.warn("console ws error:", msg.detail);
      }
    }

    function connect() {
      if (cancelled) return;
      const proto = window.location.protocol === "https:" ? "wss:" : "ws:";
      const url = withApiKeyQuery(
        `${proto}//${window.location.host}/ws/console`
      );
      const ws = new WebSocket(url);
      wsRef.current = ws;

      ws.onopen = () => {
        sendWsAuth(ws);
        attempt = 0;
        setWsStatus("live");
      };
      ws.onerror = () => setWsStatus("error");
      ws.onmessage = handleMessage;
      ws.onclose = () => {
        if (cancelled) return;
        setWsStatus("disconnected");
        if (attempt >= maxAttempts) {
          setWsStatus("disconnected");
          return;
        }
        setWsStatus("reconnecting");
        const delay = Math.min(8000, 500 * Math.pow(1.5, attempt));
        attempt += 1;
        retryTimer = setTimeout(connect, delay);
      };
    }

    connect();

    return () => {
      cancelled = true;
      if (retryTimer) clearTimeout(retryTimer);
      try {
        wsRef.current?.close();
      } catch {
        /* ignore */
      }
    };
  }, []);

  // Load pack metadata once for slot labels.
  useEffect(() => {
    fetch("/api/packs", { headers: apiHeaders() })
      .then((r) => {
        if (!r.ok) throw new Error(String(r.status));
        return r.json();
      })
      .then((d) => {
        const ap = (d.packs || []).find((p) => p.is_active);
        if (ap) setPack(ap);
      })
      .catch(() => {});
  }, []);

  // ── Sort: flagged (frustration > threshold) first ───────────────────
  const sorted = [...interactions].sort((a, b) => {
    const fa = frustration[a.interaction_id] ?? a.last_frustration ?? 0;
    const fb = frustration[b.interaction_id] ?? b.last_frustration ?? 0;
    if (fa > FRUSTRATION_THRESHOLD && fb <= FRUSTRATION_THRESHOLD) return -1;
    if (fb > FRUSTRATION_THRESHOLD && fa <= FRUSTRATION_THRESHOLD) return 1;
    return fb - fa;
  });

  // Auto-select first if none selected.
  useEffect(() => {
    if (!selectedId && sorted.length) setSelectedId(sorted[0].interaction_id);
  }, [sorted, selectedId]);

  // ── Takeover / release ─────────────────────────────────────────────
  async function takeover(iid) {
    const r = await fetch(`/api/interactions/${iid}/takeover`, {
      method: "POST",
      headers: apiHeaders(),
    });
    if (r.ok) {
      setTakenOver((t) => ({ ...t, [iid]: true }));
    }
  }
  async function release(iid) {
    const r = await fetch(`/api/interactions/${iid}/release`, {
      method: "POST",
      headers: apiHeaders(),
    });
    if (r.ok) {
      setTakenOver((t) => ({ ...t, [iid]: false }));
      setReply("");
    }
  }

  function sendReply(e) {
    e.preventDefault();
    if (!selectedId || !reply.trim()) return;
    const ws = wsRef.current;
    if (ws && ws.readyState === WebSocket.OPEN) {
      ws.send(
        JSON.stringify({
          type: "human_turn",
          interaction_id: selectedId,
          text: reply.trim(),
        })
      );
      setReply("");
    }
  }

  function packLabeledSlots(iid) {
    const s = slots[iid] || {};
    const labels = pack?.entity_labels || [];
    if (labels.length) {
      return labels.map((label, i) => ({
        label,
        value: s[`entity_${i + 1}`] ?? s[label] ?? "",
      }));
    }
    return Object.entries(s).map(([k, v]) => ({ label: k, value: v }));
  }

  function fmtDuration(ms) {
    if (!ms && ms !== 0) return "—";
    if (ms < 1000) return `${ms}ms`;
    return `${(ms / 1000).toFixed(1)}s`;
  }

  function fmtTime(ts) {
    if (!ts) return "";
    try {
      return new Date(ts).toLocaleTimeString([], {
        hour: "2-digit",
        minute: "2-digit",
        second: "2-digit",
      });
    } catch {
      return "";
    }
  }

  const selTurns = (selectedId && turns[selectedId]) || [];
  const selActivities = (selectedId && activities[selectedId]) || [];
  const selFrustration = selectedId
    ? frustration[selectedId] ?? selected?.last_frustration ?? selected?.peak_frustration ?? 0
    : 0;
  const isFlagged = selFrustration > FRUSTRATION_THRESHOLD;
  const isTakenOver = selectedId ? !!takenOver[selectedId] : false;

  return (
    <div className="page-enter">
      <header className="page-header">
        <div>
          <h1>Live console</h1>
          <p className="sub">
            Supervisor view of active contacts. Take over when frustration spikes or the agent needs a human.
          </p>
        </div>
        <div className="page-actions">
          <button type="button" className="ghost" onClick={() => (window.location.hash = "call")}>
            Open voice agent
          </button>
          <button type="button" className="primary" onClick={() => (window.location.hash = "warning")}>
            Simulate traffic
          </button>
        </div>
      </header>

      <div className="ops-ribbon" aria-live="polite">
        <span
          className={
            "pip" +
            (wsStatus === "live" ? " live" : wsStatus === "error" || wsStatus === "disconnected" ? " err" : " warn")
          }
          aria-hidden="true"
        />
        <span>
          WebSocket{" "}
          <strong
            className={
              wsStatus === "live"
                ? "ok-text"
                : wsStatus === "connecting" || wsStatus === "reconnecting"
                  ? "warn-text"
                  : "err-text"
            }
          >
            {wsStatus}
          </strong>
        </span>
        <span className="faint">·</span>
        <span>
          Active contacts <strong className="mono">{interactions.length}</strong>
        </span>
        <span className="faint">·</span>
        <span>
          Flagged{" "}
          <strong className="mono">
            {
              sorted.filter((it) => {
                const f =
                  frustration[it.interaction_id] ??
                  it.last_frustration ??
                  it.peak_frustration ??
                  0;
                return f > FRUSTRATION_THRESHOLD;
              }).length
            }
          </strong>
        </span>
        <span className="faint">·</span>
        <span className="build-stamp">Live strip</span>
      </div>

      {sorted.length === 0 ? (
        <div className="hero-empty" style={{ marginBottom: 16 }}>
          <h3>No live contacts</h3>
          <p>
            When a call is active it appears here with transcript, slots, and agent activity.
            Start a contact from Voice agent, or simulate traffic from Early warning.
          </p>
          <div className="row">
            <button type="button" className="primary" onClick={() => (window.location.hash = "call")}>
              Start voice contact
            </button>
            <button type="button" className="ghost" onClick={() => (window.location.hash = "warning")}>
              Simulate traffic
            </button>
          </div>
        </div>
      ) : (
        <div className="contact-strip" role="list" aria-label="Active contacts">
          {sorted.map((it) => {
            const f =
              frustration[it.interaction_id] ??
              it.last_frustration ??
              it.peak_frustration ??
              0;
            const flagged = f > FRUSTRATION_THRESHOLD;
            return (
              <div
                key={it.interaction_id}
                role="listitem"
                className={
                  "interaction-card" +
                  (it.interaction_id === selectedId ? " selected" : "") +
                  (flagged ? " flagged" : "")
                }
                style={{ width: 240, flex: "0 0 auto", margin: 0 }}
                onClick={() => setSelectedId(it.interaction_id)}
                onKeyDown={(e) => {
                  if (e.key === "Enter" || e.key === " ") {
                    e.preventDefault();
                    setSelectedId(it.interaction_id);
                  }
                }}
                tabIndex={0}
              >
                <div className="top">
                  <span className="mono" style={{ fontSize: 11 }}>
                    {it.interaction_id.slice(0, 18)}…
                  </span>
                  <span className="state">{it.status}</span>
                </div>
                <div className="fr-meter" style={{ margin: "8px 0 6px" }}>
                  <div className="fr-meter-track">
                    <div
                      className={"fr-meter-fill" + (flagged ? " high" : "")}
                      style={{ width: `${Math.min(100, Math.round(f * 100))}%` }}
                    />
                  </div>
                  <span className={"fr-meter-label" + (flagged ? " err-text" : "")}>{f.toFixed(2)}</span>
                </div>
                <div className="row" style={{ gap: 4 }}>
                  <span className="chip">{it.channel}</span>
                  {it.supervised && <span className="chip teal">supervised</span>}
                  {flagged && <span className="chip red pulse">fr high</span>}
                </div>
                <div style={{ marginTop: 6, fontSize: 12 }}>
                  <span className="muted">category:</span>{" "}
                  <span className="mono">{it.category || "—"}</span>
                </div>
              </div>
            );
          })}
        </div>
      )}

      {!selected ? (
        sorted.length > 0 && (
          <div className="hero-empty">
            <h3>Select a contact</h3>
            <p>Pick a card above to watch the transcript, filled slots, and agent activity in real time.</p>
          </div>
        )
      ) : (
        <div className="console-grid">
          <div className="panel">
            <div
              style={{
                display: "flex",
                justifyContent: "space-between",
                alignItems: "center",
                marginBottom: 8,
              }}
            >
              <h2 style={{ margin: 0 }}>Transcript</h2>
              <span className="mono faint" style={{ fontSize: 11 }}>
                {selected.interaction_id}
              </span>
            </div>

            <div className="fr-meter" aria-label="Frustration">
              <div className="fr-meter-track">
                <div
                  className={"fr-meter-fill" + (isFlagged ? " high" : "")}
                  style={{ width: `${Math.min(100, Math.round(selFrustration * 100))}%` }}
                />
              </div>
              <span className={"fr-meter-label" + (isFlagged ? " err-text" : "")}>
                {selFrustration.toFixed(2)}
              </span>
            </div>

            <div style={{ marginBottom: 12, fontSize: 12 }}>
              <span className="muted">state:</span>{" "}
              <span className="mono">{selected.status}</span>
              {isFlagged && (
                <span className="chip red pulse" style={{ marginLeft: 8 }}>
                  high frustration
                </span>
              )}
            </div>

            <div className="scroll-y transcript" style={{ maxHeight: 420, paddingRight: 6 }}>
              {selTurns.length === 0 && <div className="empty">Waiting for turns…</div>}
              {selTurns.map((t, i) => (
                <div key={i} className={"turn " + t.speaker} style={{ maxWidth: "100%" }}>
                  <div className="who">
                    {t.speaker} · {fmtTime(t.ts)}
                  </div>
                  <div>{t.text}</div>
                </div>
              ))}
            </div>

            {isTakenOver && (
              <form onSubmit={sendReply} style={{ marginTop: 12 }}>
                <div className="row">
                  <input
                    style={{ flex: 1 }}
                    placeholder="Type supervisor reply…"
                    value={reply}
                    onChange={(e) => setReply(e.target.value)}
                    autoFocus
                  />
                  <button type="submit" className="primary">
                    Send
                  </button>
                </div>
              </form>
            )}
          </div>

          <div className="panel">
            <h2>Agent activity</h2>

            <div className={"takeover-bar" + (isTakenOver ? " active" : "")}>
              {!isTakenOver ? (
                <>
                  <button className="primary" onClick={() => takeover(selected.interaction_id)}>
                    Take over
                  </button>
                  <span className="faint" style={{ fontSize: 12 }}>
                    AI keeps talking until you take over
                  </span>
                </>
              ) : (
                <>
                  <button className="danger" onClick={() => release(selected.interaction_id)}>
                    Release to AI
                  </button>
                  <span className="err-text" style={{ fontSize: 12, fontWeight: 600 }}>
                    You are live on this contact
                  </span>
                </>
              )}
            </div>

            <div className="activity-card" style={{ marginBottom: 12 }}>
              <div className="head">
                <span className="state mono">{selected.status}</span>
                <span className="chip teal">fr {selFrustration.toFixed(2)}</span>
              </div>
              <div style={{ marginTop: 6 }}>
                {packLabeledSlots(selected.interaction_id).map((s, i) => (
                  <div className="slot-row" key={i}>
                    <span className="k">{s.label}</span>
                    <span className={"v" + (s.value ? "" : " empty")}>{s.value || "—"}</span>
                  </div>
                ))}
              </div>
            </div>

            <div className="scroll-y activity-feed" style={{ maxHeight: 360, paddingRight: 6 }}>
              {selActivities.length === 0 && <div className="empty">No agent activity yet.</div>}
              {[...selActivities].reverse().map((a, i) => (
                <div className="activity-card" key={a.action_id || `${a.agent}-${a.action_type}-${a.ts}-${i}`}>
                  <div className="head">
                    <span className={"badge " + (AGENT_BADGE_CLASS[a.agent] || "")}>{a.agent}</span>
                    <span className="faint mono">{a.action_type}</span>
                    {a.ok === false && <span className="err-text">error</span>}
                  </div>
                  <div className="summary">{a.output_summary || a.summary || a.input_summary || "—"}</div>
                  <div className="meta">
                    <span>{fmtDuration(a.duration_ms)}</span>
                    {(a.evidence_ids || []).slice(0, 4).map((eid) => (
                      <span className="chip" key={eid} style={{ fontSize: 10 }}>
                        {eid}
                      </span>
                    ))}
                    <span>{fmtTime(a.ts)}</span>
                  </div>
                </div>
              ))}
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
