import { useEffect, useRef, useState } from "react";
import { apiHeaders, sendWsAuth, withApiKeyQuery } from "../src/apiAuth.js";
import { IconHangup, IconMic, IconSpeaker } from "../src/icons.jsx";
import {
  BARGE_IN_GRACE_MS,
  CALL_STATE,
  buildSlotEntries,
  callPhaseHint,
  callStateLabel,
  capabilitySnapshot,
  greetingSpeakText,
  mapInteractionEnded,
  mergeTranscriptTurn,
  shouldAcceptSpeechResult,
  shouldAllowBargeIn,
  shouldReconnectOnClose,
  shouldResumeListeningOnOpen,
  slotProgress,
} from "../src/voiceHelpers.js";
import { capabilityLabel } from "../src/ui/labels.js";

function getSpeechRecognition() {
  if (typeof window === "undefined") return null;
  return window.SpeechRecognition || window.webkitSpeechRecognition || null;
}

export default function CallWidget() {
  const [state, setState] = useState(CALL_STATE.IDLE);
  const [error, setError] = useState(null);
  const [info, setInfo] = useState(null);
  const [transcript, setTranscript] = useState([]);
  const [slots, setSlots] = useState({});
  const [pack, setPack] = useState(null);
  const [interactionId, setInteractionId] = useState(null);
  const [handoff, setHandoff] = useState(false);
  const [ended, setEnded] = useState(null);
  const [wsStatus, setWsStatus] = useState("idle");
  const [textFallback, setTextFallback] = useState("");
  const [activity, setActivity] = useState(null);
  const [micGranted, setMicGranted] = useState(null);
  const [turnCount, setTurnCount] = useState(0);
  const [speakPhase, setSpeakPhase] = useState("normal"); // 'greeting' | 'normal'

  const hasSR = !!getSpeechRecognition();
  const hasTTS = typeof window !== "undefined" && "speechSynthesis" in window;

  const wsRef = useRef(null);
  const recogRef = useRef(null);
  const speakingRef = useRef(false);
  const speakPhaseRef = useRef("normal"); // 'greeting' | 'normal'
  const ttsStartedAtRef = useRef(0);
  const bargeStreakRef = useRef(0);
  const audioCtxRef = useRef(null);
  const analyserRef = useRef(null);
  const micStreamRef = useRef(null);
  const bargeRafRef = useRef(null);
  const transcriptEndRef = useRef(null);
  const transcriptScrollRef = useRef(null);
  const intentionalCloseRef = useRef(false);
  const callEndedRef = useRef(false);
  const reconnectAttemptRef = useRef(0);
  const reconnectTimerRef = useRef(null);
  const activeWsUrlRef = useRef(null);
  const interactionIdRef = useRef(null);
  const turnSeqRef = useRef(0);

  function markCallTerminal() {
    // Prevent onclose reconnect from treating a normal server hangup as a drop.
    intentionalCloseRef.current = true;
    callEndedRef.current = true;
    activeWsUrlRef.current = null;
    if (reconnectTimerRef.current) {
      clearTimeout(reconnectTimerRef.current);
      reconnectTimerRef.current = null;
    }
  }

  function closeWsQuietly() {
    try {
      wsRef.current?.close();
    } catch {
      /* ignore */
    }
  }

  function pushTurn(entry) {
    turnSeqRef.current += 1;
    const withId = { ...entry, id: entry.id || `t${turnSeqRef.current}` };
    setTranscript((t) => mergeTranscriptTurn(t, withId));
    if (!entry.interim) setTurnCount((n) => n + 1);
  }

  function stopRecognition() {
    try {
      recogRef.current?.stop();
    } catch {
      /* ignore */
    }
  }

  function startRecognitionSafe() {
    if (!recogRef.current) return;
    if (speakingRef.current) return;
    if (!wsRef.current || wsRef.current.readyState !== WebSocket.OPEN) return;
    try {
      recogRef.current.start();
    } catch {
      /* already started */
    }
  }

  /**
   * Speak agent text. opts.phase === 'greeting' disables barge-in so speaker
   * bleed cannot cancel the pack greeting mid-word ("than" from "Thanks").
   */
  function speak(text, opts = {}) {
    const full = greetingSpeakText(text);
    const phase = opts.phase || "normal";
    speakPhaseRef.current = phase;
    setSpeakPhase(phase);
    bargeStreakRef.current = 0;

    if (!hasTTS || !full) {
      speakingRef.current = false;
      speakPhaseRef.current = "normal";
      setSpeakPhase("normal");
      setState(CALL_STATE.LISTENING);
      startRecognitionSafe();
      return;
    }
    // Pause STT while agent talks so we do not echo TTS into user_turn.
    speakingRef.current = true;
    setState(CALL_STATE.AGENT_SPEAKING);
    stopRecognition();

    // Cancel any prior utterance, then speak on next task so Chrome does not
    // drop the new utterance when cancel+speak run in the same turn.
    try {
      window.speechSynthesis.cancel();
    } catch {
      /* ignore */
    }

    const finishSpeaking = () => {
      speakingRef.current = false;
      speakPhaseRef.current = "normal";
      setSpeakPhase("normal");
      bargeStreakRef.current = 0;
      if (bargeRafRef.current) {
        cancelAnimationFrame(bargeRafRef.current);
        bargeRafRef.current = null;
      }
      if (wsRef.current && wsRef.current.readyState === WebSocket.OPEN) {
        setState(CALL_STATE.LISTENING);
        startRecognitionSafe();
      }
    };

    window.setTimeout(() => {
      if (!speakingRef.current) return;
      const u = new SpeechSynthesisUtterance(full);
      u.rate = 1.0;
      u.onstart = () => {
        ttsStartedAtRef.current = Date.now();
        bargeStreakRef.current = 0;
        // Barge-in only for non-greeting agent turns, and only after grace.
        if (phase !== "greeting") {
          startBargeWatch();
        }
      };
      u.onend = finishSpeaking;
      u.onerror = finishSpeaking;
      try {
        window.speechSynthesis.speak(u);
      } catch {
        finishSpeaking();
      }
      // If onstart never fires (some engines), still arm barge after grace for non-greeting.
      if (phase !== "greeting" && !ttsStartedAtRef.current) {
        ttsStartedAtRef.current = Date.now();
        startBargeWatch();
      }
    }, 40);
  }

  function startBargeWatch() {
    const ctx = audioCtxRef.current;
    const analyser = analyserRef.current;
    if (!ctx || !analyser) return;
    if (bargeRafRef.current) cancelAnimationFrame(bargeRafRef.current);
    const data = new Uint8Array(analyser.frequencyBinCount);
    const started = ttsStartedAtRef.current || Date.now();

    const tick = () => {
      if (!speakingRef.current) {
        bargeRafRef.current = null;
        bargeStreakRef.current = 0;
        return;
      }
      // Never barge during pack greeting.
      if (speakPhaseRef.current === "greeting") {
        bargeRafRef.current = requestAnimationFrame(tick);
        return;
      }
      analyser.getByteTimeDomainData(data);
      let sum = 0;
      for (let i = 0; i < data.length; i += 8) {
        const v = (data[i] - 128) / 128;
        sum += v * v;
      }
      const rms = Math.sqrt(sum / (data.length / 8));
      const elapsedMs = Date.now() - started;
      const high = rms >= 0.14;
      if (high) bargeStreakRef.current += 1;
      else bargeStreakRef.current = 0;

      if (
        shouldAllowBargeIn({
          phase: speakPhaseRef.current,
          elapsedMs,
          graceMs: BARGE_IN_GRACE_MS,
          rms,
          rmsThreshold: 0.14,
          highRmsStreak: bargeStreakRef.current,
          streakNeeded: 4,
        })
      ) {
        try {
          window.speechSynthesis.cancel();
        } catch {
          /* ignore */
        }
        speakingRef.current = false;
        speakPhaseRef.current = "normal";
        setSpeakPhase("normal");
        bargeStreakRef.current = 0;
        sendWs({ type: "barge_in" });
        setState(CALL_STATE.LISTENING);
        setInfo("Barge-in — listening again");
        startRecognitionSafe();
        bargeRafRef.current = null;
        return;
      }
      bargeRafRef.current = requestAnimationFrame(tick);
    };
    bargeRafRef.current = requestAnimationFrame(tick);
  }

  function sendWs(obj) {
    const ws = wsRef.current;
    if (ws && ws.readyState === WebSocket.OPEN) {
      ws.send(JSON.stringify(obj));
    }
  }

  function handleWsMessage(msg) {
    switch (msg.type) {
      case "agent_turn": {
        const agentText = greetingSpeakText(msg.text || "");
        pushTurn({ speaker: msg.speaker || "agent", text: agentText });
        if (msg.speaker === "supervisor") return;
        speak(agentText, { phase: "normal" });
        break;
      }
      case "agent_activity": {
        setActivity({
          agent: msg.agent,
          action_type: msg.action_type,
          summary: msg.summary || "",
        });
        break;
      }
      case "slots_update": {
        setSlots(msg.slots || {});
        break;
      }
      case "handoff_offer": {
        setHandoff(true);
        setInfo("A supervisor can take over this contact");
        break;
      }
      case "interaction_ended": {
        // Server sends flat case_id / investigation_id — not nested payload.
        // Mark terminal BEFORE close so onclose does not reconnect / wipe summary.
        const summary = mapInteractionEnded(msg);
        markCallTerminal();
        setEnded(summary);
        setState(CALL_STATE.ENDED);
        setWsStatus("disconnected");
        cleanupCall();
        closeWsQuietly();
        break;
      }
      case "error": {
        setError(msg.detail || msg.message || "Server error");
        break;
      }
      default:
        break;
    }
  }

  function cleanupCall() {
    stopRecognition();
    if (bargeRafRef.current) cancelAnimationFrame(bargeRafRef.current);
    bargeRafRef.current = null;
    if (hasTTS) {
      try {
        window.speechSynthesis.cancel();
      } catch {
        /* ignore */
      }
    }
    speakingRef.current = false;
    if (micStreamRef.current) {
      micStreamRef.current.getTracks().forEach((t) => t.stop());
      micStreamRef.current = null;
    }
    if (audioCtxRef.current && audioCtxRef.current.state !== "closed") {
      audioCtxRef.current.close().catch(() => {});
    }
    audioCtxRef.current = null;
    analyserRef.current = null;
  }

  async function setupMic() {
    try {
      const stream = await navigator.mediaDevices.getUserMedia({ audio: true });
      micStreamRef.current = stream;
      const ctx = new (window.AudioContext || window.webkitAudioContext)();
      const src = ctx.createMediaStreamSource(stream);
      const analyser = ctx.createAnalyser();
      analyser.fftSize = 512;
      src.connect(analyser);
      audioCtxRef.current = ctx;
      analyserRef.current = analyser;
      setMicGranted(true);
      return true;
    } catch {
      setMicGranted(false);
      setInfo("Microphone blocked — use the text box to talk");
      return false;
    }
  }

  function setupSpeechRecognition() {
    const SR = getSpeechRecognition();
    if (!SR) return null;
    const recog = new SR();
    recog.continuous = true;
    recog.interimResults = true;
    recog.lang = "en-US";
    recog.onresult = (ev) => {
      const accept = shouldAcceptSpeechResult({
        speaking: speakingRef.current,
        wsOpen: !!(wsRef.current && wsRef.current.readyState === WebSocket.OPEN),
      });
      if (!accept) return;

      let interim = "";
      for (let i = ev.resultIndex; i < ev.results.length; i++) {
        const res = ev.results[i];
        const txt = (res[0].transcript || "").trim();
        if (!txt) continue;
        if (res.isFinal) {
          pushTurn({ speaker: "customer", text: txt });
          sendWs({ type: "user_turn", text: txt, final: true });
        } else {
          interim += (interim ? " " : "") + txt;
        }
      }
      if (interim) {
        pushTurn({ speaker: "customer", text: interim, interim: true });
      }
    };
    recog.onerror = (e) => {
      if (e.error === "no-speech" || e.error === "aborted") return;
      if (e.error === "not-allowed") {
        setMicGranted(false);
        setInfo("Speech recognition denied — type your replies below");
        return;
      }
      setError(`Speech: ${e.error}`);
    };
    recog.onend = () => {
      if (speakingRef.current) return;
      if (speakPhaseRef.current === "greeting") return;
      if (!wsRef.current || wsRef.current.readyState !== WebSocket.OPEN) return;
      if (intentionalCloseRef.current) return;
      startRecognitionSafe();
    };
    recogRef.current = recog;
    return recog;
  }

  async function startCall() {
    setError(null);
    setInfo(null);
    setTranscript([]);
    setSlots({});
    setHandoff(false);
    setEnded(null);
    setActivity(null);
    setTurnCount(0);
    turnSeqRef.current = 0;
    setState(CALL_STATE.CONNECTING);

    let startRes;
    try {
      const r = await fetch("/api/interactions/start?channel=web_voice", {
        method: "POST",
        headers: apiHeaders(),
      });
      if (!r.ok) {
        const detail = await r.text().catch(() => "");
        throw new Error(`Could not start call (${r.status})${detail ? `: ${detail.slice(0, 120)}` : ""}`);
      }
      startRes = await r.json();
    } catch (e) {
      setError(String(e.message || e));
      setState(CALL_STATE.IDLE);
      return;
    }

    setInteractionId(startRes.interaction_id);
    interactionIdRef.current = startRes.interaction_id;
    setPack(startRes.pack || null);
    intentionalCloseRef.current = false;
    callEndedRef.current = false;
    reconnectAttemptRef.current = 0;

    await setupMic();
    setupSpeechRecognition();

    const proto = window.location.protocol === "https:" ? "wss:" : "ws:";
    const wsUrl = withApiKeyQuery(`${proto}//${window.location.host}${startRes.ws_url}`);
    activeWsUrlRef.current = wsUrl;

    function bindWs(ws, { isReconnect }) {
      wsRef.current = ws;
      ws.onopen = () => {
        if (
          !shouldResumeListeningOnOpen({
            intentionalClose: intentionalCloseRef.current,
            callEnded: callEndedRef.current,
            isReconnect,
          }) &&
          isReconnect
        ) {
          // Call already ended while reconnect was queued — stay quiet.
          setWsStatus("disconnected");
          closeWsQuietly();
          return;
        }
        sendWsAuth(ws);
        setWsStatus("live");
        reconnectAttemptRef.current = 0;
        if (!isReconnect && startRes.greeting_text) {
          // Full pack greeting — transcript + TTS must match start response.
          const greet = greetingSpeakText(startRes.greeting_text);
          pushTurn({ speaker: "agent", text: greet });
          speak(greet, { phase: "greeting" });
        } else if (
          shouldResumeListeningOnOpen({
            intentionalClose: intentionalCloseRef.current,
            callEnded: callEndedRef.current,
            isReconnect: true,
          }) ||
          !isReconnect
        ) {
          // Reconnect resume OR first open without greeting path.
          if (isReconnect || !startRes.greeting_text) {
            speakingRef.current = false;
            setState(CALL_STATE.LISTENING);
            startRecognitionSafe();
          }
        }
      };
      ws.onmessage = (ev) => {
        try {
          handleWsMessage(JSON.parse(ev.data));
        } catch {
          /* ignore bad frames */
        }
      };
      ws.onerror = () => {
        if (!callEndedRef.current && !intentionalCloseRef.current) {
          setError("WebSocket connection error");
        }
      };
      ws.onclose = () => {
        if (
          !shouldReconnectOnClose({
            intentionalClose: intentionalCloseRef.current,
            callEnded: callEndedRef.current,
          })
        ) {
          setWsStatus("disconnected");
          return;
        }
        if (reconnectAttemptRef.current >= 5) {
          setWsStatus("disconnected");
          setState(CALL_STATE.ENDED);
          setEnded((prev) => prev || { reason: "connection_lost" });
          markCallTerminal();
          cleanupCall();
          return;
        }
        setWsStatus("reconnecting");
        setInfo("Connection dropped — reconnecting…");
        const delay = Math.min(5000, 400 * Math.pow(1.6, reconnectAttemptRef.current));
        reconnectAttemptRef.current += 1;
        reconnectTimerRef.current = setTimeout(() => {
          if (
            !shouldReconnectOnClose({
              intentionalClose: intentionalCloseRef.current,
              callEnded: callEndedRef.current,
            }) ||
            !activeWsUrlRef.current
          ) {
            return;
          }
          bindWs(new WebSocket(activeWsUrlRef.current), { isReconnect: true });
        }, delay);
      };
    }

    bindWs(new WebSocket(wsUrl), { isReconnect: false });
  }

  function endCall() {
    markCallTerminal();
    setWsStatus("disconnected");
    sendWs({ type: "hangup" });
    setState(CALL_STATE.ENDED);
    setEnded((prev) => prev || { reason: "user_hangup" });
    cleanupCall();
    const iid = interactionIdRef.current || interactionId;
    if (iid) {
      fetch(`/api/interactions/${iid}/end`, {
        method: "POST",
        headers: apiHeaders(),
      }).catch(() => {});
    }
    closeWsQuietly();
  }

  // Cleanup on unmount: arm intentional close + clear reconnect timer (no ghost reconnects).
  useEffect(() => {
    return () => {
      markCallTerminal();
      cleanupCall();
      closeWsQuietly();
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  // Auto-scroll transcript to newest turn
  useEffect(() => {
    const el = transcriptScrollRef.current;
    if (!el) return;
    el.scrollTop = el.scrollHeight;
  }, [transcript]);

  function submitTextFallback(e) {
    e.preventDefault();
    const text = textFallback.trim();
    if (!text) return;
    if (!wsRef.current || wsRef.current.readyState !== WebSocket.OPEN) {
      setError("Not connected — start a call first");
      return;
    }
    // If agent is speaking, cancel TTS so we don't talk over ourselves.
    // speechSynthesis.cancel often does not fire utterance onend — resume STT explicitly.
    if (speakingRef.current && hasTTS) {
      try {
        window.speechSynthesis.cancel();
      } catch {
        /* ignore */
      }
      speakingRef.current = false;
    }
    pushTurn({ speaker: "customer", text });
    sendWs({ type: "user_turn", text, final: true });
    setTextFallback("");
    setState(CALL_STATE.LISTENING);
    startRecognitionSafe();
  }

  const slotEntries = buildSlotEntries(pack, slots);
  const progress = slotProgress(slotEntries);
  const caps = capabilitySnapshot({
    hasSpeechRecognition: hasSR,
    hasSpeechSynthesis: hasTTS,
    hasMicStream: !!micStreamRef.current || micGranted === true,
  });

  const inCall = state !== CALL_STATE.IDLE && state !== CALL_STATE.ENDED;
  const canStart = state === CALL_STATE.IDLE || state === CALL_STATE.ENDED;
  const showCompose = inCall || state === CALL_STATE.CONNECTING;

  return (
    <div className="voice-page page-enter">
      <header className="page-header">
        <div>
          <h1>Voice agent</h1>
          <p className="sub">
            Live contact with the Skew AI orchestrator. Speak or type — STT pauses while the agent
            talks so your mic does not echo the reply.
            {pack ? (
              <>
                {" "}
                Pack <span className="mono">{pack.id}</span>
                {pack.display_name ? ` · ${pack.display_name}` : ""}.
              </>
            ) : null}
          </p>
        </div>
        <div className="page-actions">
          {canStart ? (
            <button
              type="button"
              className="primary voice-cta"
              onClick={startCall}
              disabled={state === CALL_STATE.CONNECTING}
            >
              <IconMic />
              Start voice call
            </button>
          ) : (
            <button type="button" className="danger voice-cta" onClick={endCall}>
              <IconHangup />
              End call
            </button>
          )}
        </div>
      </header>

      {error && (
        <div className="banner banner-error" role="alert">
          {error}{" "}
          <button type="button" className="ghost" onClick={() => setError(null)}>
            Dismiss
          </button>
        </div>
      )}
      {info && !error && (
        <div className="banner banner-ok" role="status">
          {info}{" "}
          <button type="button" className="ghost" onClick={() => setInfo(null)}>
            Dismiss
          </button>
        </div>
      )}

      <div className="call-layout">
        <div className="call-stage">
          <div className="call-hero">
            <div
              className={
                "call-ring " +
                state +
                (speakPhase === "greeting" ? " greeting" : "")
              }
              aria-hidden="true"
            >
              <div className="mic-orbit">
                <span className="call-aura call-aura-a" />
                <span className="call-aura call-aura-b" />
                <span className="call-aura call-aura-c" />
                <button
                  type="button"
                  className={
                    "mic-btn " +
                    state +
                    (speakPhase === "greeting" ? " greeting" : "")
                  }
                  onClick={canStart ? startCall : endCall}
                  disabled={state === CALL_STATE.CONNECTING}
                  aria-label={canStart ? "Start call" : "End call"}
                >
                  {state === CALL_STATE.CONNECTING ? (
                    <span className="spinner" aria-hidden="true" />
                  ) : canStart ? (
                    <IconMic width={32} height={32} />
                  ) : state === CALL_STATE.LISTENING ? (
                    <IconMic width={32} height={32} />
                  ) : state === CALL_STATE.AGENT_SPEAKING ? (
                    <IconSpeaker width={32} height={32} />
                  ) : (
                    <IconHangup width={32} height={32} />
                  )}
                </button>
              </div>
              {(state === CALL_STATE.LISTENING || state === CALL_STATE.AGENT_SPEAKING) && (
                <div className="voice-waves-wrap">
                  <div
                    className={
                      "voice-waves" +
                      (state === CALL_STATE.AGENT_SPEAKING ? " speaking" : " listening") +
                      (speakPhase === "greeting" ? " greeting" : "")
                    }
                  >
                    <span /><span /><span /><span /><span />
                  </div>
                </div>
              )}
            </div>
            <div
              className={
                "call-state " +
                state +
                (speakPhase === "greeting" ? " greeting" : "")
              }
            >
              <span className="label">{callStateLabel(state, { speakPhase })}</span>
              {callPhaseHint(state, { speakPhase }) && (
                <span className="phase-hint">{callPhaseHint(state, { speakPhase })}</span>
              )}
              <span className="call-meta">
                <span className={"status-pip " + (wsStatus === "live" ? "ok" : wsStatus === "reconnecting" ? "warn" : "")} />
                {wsStatus === "idle" ? "idle" : `ws ${wsStatus}`}
                {interactionId && (
                  <>
                    {" · "}
                    <span className="mono" title={interactionId}>
                      {interactionId.slice(0, 16)}…
                    </span>
                  </>
                )}
                {turnCount > 0 && <> · {turnCount} turns</>}
              </span>
            </div>
            {progress.total > 0 && (
              <div className="slot-meter" aria-label={`Slots ${progress.filled} of ${progress.total}`}>
                <div className="slot-meter-track">
                  <div className="slot-meter-fill" style={{ width: `${progress.pct}%` }} />
                </div>
                <span className="slot-meter-label mono">
                  {progress.filled}/{progress.total} slots
                </span>
              </div>
            )}
          </div>

          {activity && inCall && (
            <div className="activity-strip" aria-live="polite">
              <span className="mono faint">{activity.agent}</span>
              <span>{activity.summary || activity.action_type}</span>
            </div>
          )}

          <div
            className="transcript"
            ref={(node) => {
              transcriptScrollRef.current = node;
              transcriptEndRef.current = node;
            }}
            aria-live="polite"
            aria-relevant="additions"
          >
            {transcript.length === 0 && (
              <div className="empty-state">
                <p className="empty-state-text">
                  {state === CALL_STATE.IDLE
                    ? hasSR
                      ? "Start a call, allow the microphone, then speak naturally. You can always type below."
                      : "This browser has no Web Speech API. Start a call and type every customer turn."
                    : state === CALL_STATE.CONNECTING
                      ? "Opening the contact and waiting for the greeting…"
                      : "Waiting for the first turn…"}
                </p>
              </div>
            )}
            {transcript.map((t) => (
              <div
                key={t.id || `${t.speaker}-${t.text.slice(0, 12)}`}
                className={"turn " + t.speaker + (t.interim ? " interim" : "")}
              >
                <div className="who">
                  {t.speaker}
                  {t.interim ? " · listening" : ""}
                </div>
                <div>{t.text}</div>
              </div>
            ))}
          </div>

          {showCompose && (
            <form className="call-compose" onSubmit={submitTextFallback}>
              <input
                aria-label="Type a customer turn"
                placeholder={
                  hasSR
                    ? "Type a reply (or speak) — Enter to send"
                    : "Type your reply — Enter to send"
                }
                value={textFallback}
                onChange={(e) => setTextFallback(e.target.value)}
                disabled={state === CALL_STATE.ENDED || state === CALL_STATE.CONNECTING}
                autoComplete="off"
              />
              <button
                type="submit"
                className="primary"
                disabled={
                  state === CALL_STATE.ENDED ||
                  state === CALL_STATE.CONNECTING ||
                  !textFallback.trim()
                }
              >
                Send
              </button>
            </form>
          )}

          {handoff && inCall && (
            <p className="tag live" style={{ marginTop: 12 }}>
              Supervisor handoff offered — open Live console to take over
            </p>
          )}

          {ended && state === CALL_STATE.ENDED && (
            <div className="result-card" style={{ marginTop: 14 }}>
              <div className="result-card-title">Call ended</div>
              <div className="kvs">
                <span className="k">reason</span>
                <span className="v mono">{ended.reason || "ended"}</span>
                <span className="k">case</span>
                <span className="v mono">{ended.case_id || "—"}</span>
                <span className="k">investigation</span>
                <span className="v mono">
                  {ended.investigation_id ||
                    (ended.investigation_opened ? "opened" : "—")}
                </span>
                <span className="k">audit</span>
                <span className="v">{ended.audit_pending ? "pending" : "n/a"}</span>
              </div>
              <div className="row" style={{ marginTop: 12 }}>
                <button type="button" className="primary" onClick={startCall}>
                  New call
                </button>
                {ended.case_id && (
                  <button
                    type="button"
                    className="ghost"
                    onClick={() => {
                      window.location.hash = "cases";
                    }}
                  >
                    Open case queue
                  </button>
                )}
              </div>
            </div>
          )}
        </div>

        <aside className="stack">
          <div className="panel">
            <h2>Slot frame</h2>
            {slotEntries.length === 0 ? (
              <div className="empty-state">
                <p className="empty-state-text">
                  Slots appear as the agent fills the pack frame from your answers.
                </p>
              </div>
            ) : (
              slotEntries.map((s) => (
                <div className="slot-row" key={s.key || s.label}>
                  <span className="k">{s.label}</span>
                  <span className={"v" + (s.value ? "" : " empty")}>{s.value || "—"}</span>
                </div>
              ))
            )}
          </div>

          <div className="panel">
            <h2>Capabilities</h2>
            <div className="kvs">
              <span className="k">{capabilityLabel("stt")}</span>
              <span className="v">
                {caps.sttOk ? (
                  <span className="ok-text">{caps.stt}</span>
                ) : (
                  <span className="warn-text">{caps.stt}</span>
                )}
              </span>
              <span className="k">{capabilityLabel("tts")}</span>
              <span className="v">
                {caps.ttsOk ? (
                  <span className="ok-text">{caps.tts}</span>
                ) : (
                  <span className="warn-text">{caps.tts}</span>
                )}
              </span>
              <span className="k">{capabilityLabel("barge_in")}</span>
              <span className="v">
                {caps.bargeOk ? (
                  <span className="ok-text">{caps.bargeIn}</span>
                ) : (
                  <span className="faint">{caps.bargeIn}</span>
                )}
              </span>
              <span className="k">{capabilityLabel("mic")}</span>
              <span className="v">
                {micGranted === true ? (
                  <span className="ok-text">Granted</span>
                ) : micGranted === false ? (
                  <span className="warn-text">Denied / blocked</span>
                ) : (
                  <span className="faint">Not requested</span>
                )}
              </span>
              <span className="k">{capabilityLabel("text path")}</span>
              <span className="v ok-text">Always available in-call</span>
            </div>
            <p className="muted small" style={{ marginTop: 12 }}>
              While the agent speaks, recognition is paused so TTS is not captured as a customer
              turn. Interrupt by speaking (barge-in) or typing.
            </p>
          </div>

          <div className="panel">
            <h2>Related</h2>
            <div className="row">
              <button type="button" className="ghost" onClick={() => (window.location.hash = "console")}>
                Live console
              </button>
              <button type="button" className="ghost" onClick={() => (window.location.hash = "cases")}>
                Case queue
              </button>
            </div>
          </div>
        </aside>
      </div>
    </div>
  );
}
