/**
 * Pure helpers for the Voice agent call surface.
 * Kept free of DOM/WebSocket so unit tests can drive the real shipped logic.
 */

export const CALL_STATE = {
  IDLE: "idle",
  CONNECTING: "connecting",
  LISTENING: "listening",
  AGENT_SPEAKING: "agent-speaking",
  ENDED: "ended",
};

export const STATE_LABELS = {
  [CALL_STATE.IDLE]: "Ready to start",
  [CALL_STATE.CONNECTING]: "Connecting…",
  [CALL_STATE.LISTENING]: "Listening to you",
  [CALL_STATE.AGENT_SPEAKING]: "Agent speaking",
  [CALL_STATE.ENDED]: "Call ended",
};

/**
 * Human label for call machine state.
 * Greeting TTS uses AGENT_SPEAKING with phase "greeting" — distinct copy so
 * operators know barge-in is off until the pack greeting finishes.
 */
export function callStateLabel(state, opts = {}) {
  if (state === CALL_STATE.AGENT_SPEAKING && opts.speakPhase === "greeting") {
    return "Greeting you";
  }
  return STATE_LABELS[state] || String(state || "unknown");
}

/** Short status line under the hero label (barge-in honesty). */
export function callPhaseHint(state, opts = {}) {
  const phase = opts.speakPhase || "normal";
  if (state === CALL_STATE.AGENT_SPEAKING && phase === "greeting") {
    return "Barge-in off · full greeting plays through";
  }
  if (state === CALL_STATE.AGENT_SPEAKING) {
    return "Barge-in after ~1.8s · speak to interrupt";
  }
  if (state === CALL_STATE.LISTENING) {
    return "Your turn · speak or type below";
  }
  if (state === CALL_STATE.CONNECTING) {
    return "Opening contact · greeting next";
  }
  return "";
}

/**
 * Merge a turn into the transcript list.
 * Interim replaces trailing interim; final drops trailing interim then appends.
 * @param {Array<{speaker:string,text:string,interim?:boolean,id?:string}>} turns
 * @param {{speaker:string,text:string,interim?:boolean,id?:string}} entry
 */
export function mergeTranscriptTurn(turns, entry) {
  const list = Array.isArray(turns) ? turns : [];
  if (!entry || !entry.text) return list;
  if (entry.interim && list.length && list[list.length - 1].interim) {
    return [...list.slice(0, -1), entry];
  }
  if (entry.interim) return [...list, entry];
  const cleaned = list.length && list[list.length - 1].interim ? list.slice(0, -1) : list;
  return [...cleaned, { ...entry, interim: false }];
}

/**
 * Map a server WS frame for interaction_ended into a summary object.
 * Server sends flat fields on the message (not nested under payload).
 * @param {Record<string, unknown>} msg
 */
export function mapInteractionEnded(msg) {
  if (!msg || typeof msg !== "object") {
    return { reason: "ended" };
  }
  const nested = msg.payload && typeof msg.payload === "object" ? msg.payload : {};
  return {
    reason: nested.reason || msg.reason || "ended",
    case_id: nested.case_id ?? msg.case_id ?? null,
    investigation_id: nested.investigation_id ?? msg.investigation_id ?? null,
    investigation_opened: Boolean(
      nested.investigation_opened ?? msg.investigation_opened ?? false
    ),
    audit_pending: Boolean(nested.audit_pending ?? msg.audit_pending ?? true),
  };
}

/**
 * Should SpeechRecognition process a result right now?
 * Ignore customer STT while agent TTS is playing (unless barge-in already stopped TTS).
 */
export function shouldAcceptSpeechResult({ speaking, wsOpen }) {
  if (!wsOpen) return false;
  if (speaking) return false;
  return true;
}

/** Default settle before barge-in can cancel TTS (ms). */
export const BARGE_IN_GRACE_MS = 1800;

/**
 * Whether barge-in may cancel the current agent utterance.
 * - Disabled entirely for the initial pack greeting (phase === 'greeting').
 * - Disabled until graceMs after TTS start (speaker bleed is not barge-in).
 * - Requires sustained high RMS samples (not a single tick).
 *
 * @param {{
 *   phase?: string,
 *   elapsedMs: number,
 *   graceMs?: number,
 *   rms: number,
 *   rmsThreshold?: number,
 *   highRmsStreak?: number,
 *   streakNeeded?: number,
 * }} opts
 */
export function shouldAllowBargeIn(opts) {
  const {
    phase = "normal",
    elapsedMs = 0,
    graceMs = BARGE_IN_GRACE_MS,
    rms = 0,
    rmsThreshold = 0.14,
    highRmsStreak = 0,
    streakNeeded = 4,
  } = opts || {};
  if (phase === "greeting") return false;
  if (elapsedMs < graceMs) return false;
  if (rms < rmsThreshold) return false;
  // highRmsStreak is the count of consecutive high-RMS frames already observed.
  if ((highRmsStreak || 0) < streakNeeded) return false;
  return true;
}

/** Preserve greeting text for transcript + TTS (no truncation). */
export function normalizeGreetingText(text) {
  if (text == null) return "";
  return String(text).trim();
}

/**
 * Decide what string to pass to speechSynthesis for the start greeting.
 * Always the full start response field — never a partial interim.
 */
export function greetingSpeakText(greetingText) {
  return normalizeGreetingText(greetingText);
}

/**
 * Build slot display rows from pack entity_labels + live slots map.
 */
export function buildSlotEntries(pack, slots) {
  const s = slots && typeof slots === "object" ? slots : {};
  const labels = pack?.entity_labels;
  if (labels && !Array.isArray(labels) && typeof labels === "object") {
    const rows = Object.entries(labels).map(([key, label]) => ({
      key,
      label: label || key,
      value: s[key] ?? "",
    }));
    for (const [k, v] of Object.entries(s)) {
      if (k.startsWith("__")) continue;
      if (!rows.some((r) => r.key === k)) {
        rows.push({ key: k, label: k, value: v });
      }
    }
    return rows;
  }
  if (Array.isArray(labels) && labels.length) {
    return labels.map((label, i) => {
      const key = `entity_${i + 1}`;
      return {
        key,
        label,
        value: s[key] ?? s[label] ?? "",
      };
    });
  }
  return Object.entries(s)
    .filter(([k]) => !k.startsWith("__"))
    .map(([k, v]) => ({ key: k, label: k, value: v }));
}

/** Filled / total for progress meter. */
export function slotProgress(entries) {
  const list = Array.isArray(entries) ? entries : [];
  const total = list.length;
  const filled = list.filter((e) => String(e.value || "").trim()).length;
  return { filled, total, pct: total ? Math.round((filled / total) * 100) : 0 };
}

/**
 * Capability honesty flags for the side panel.
 */
export function capabilitySnapshot({ hasSpeechRecognition, hasSpeechSynthesis, hasMicStream }) {
  return {
    stt: hasSpeechRecognition ? "Web Speech" : "text only",
    sttOk: !!hasSpeechRecognition,
    tts: hasSpeechSynthesis ? "Browser TTS" : "unavailable",
    ttsOk: !!hasSpeechSynthesis,
    bargeIn: hasMicStream ? "armed" : hasSpeechRecognition ? "needs mic permission" : "n/a",
    bargeOk: !!hasMicStream,
    textFallback: true,
  };
}

/**
 * After a normal interaction_ended (or user hangup), WS onclose must not reconnect.
 * @param {{ intentionalClose: boolean, callEnded: boolean }} flags
 */
export function shouldReconnectOnClose({ intentionalClose, callEnded }) {
  if (intentionalClose) return false;
  if (callEnded) return false;
  return true;
}

/**
 * On WS open after reconnect: only resume listening if the call is still live.
 */
export function shouldResumeListeningOnOpen({ intentionalClose, callEnded, isReconnect }) {
  if (intentionalClose || callEnded) return false;
  // Fresh connect may start with greeting path instead; reconnect always resumes listen.
  return !!isReconnect;
}

/**
 * Is a server `error` frame fatal for this call?
 *
 * The server tags unrecoverable errors with `recoverable: false` (the contact is
 * gone, already ended, or held by another socket). Retrying those just burns the
 * reconnect budget and shows the raw 404 detail to the operator, so the widget
 * ends the call cleanly instead. Older servers only send `detail` — fall back to
 * matching the known unrecoverable details.
 *
 * @param {{ recoverable?: boolean, code?: string, detail?: string }} msg
 */
export function isFatalWsError(msg) {
  if (!msg || typeof msg !== "object") return false;
  if (msg.recoverable === false) return true;
  if (msg.recoverable === true) return false;
  const detail = String(msg.detail || msg.message || "").toLowerCase();
  return (
    detail.includes("active interaction not found") ||
    detail.includes("interaction already ended") ||
    detail.includes("already has an active customer websocket") ||
    detail.startsWith("server error")
  );
}

/** Operator-facing copy for a fatal WS error (never the raw interaction id). */
export function fatalWsErrorMessage(msg) {
  const code = msg && msg.code;
  if (code === "interaction_busy") {
    return "This contact is already open in another tab or window.";
  }
  if (code === "server_error") {
    return "The contact hit a server error and was closed. Start a new call.";
  }
  return "This contact could not be resumed — it was closed while you were disconnected.";
}

/**
 * Rebuild the transcript from the server's authoritative turn list on resume.
 * The client may have missed turns while its socket was down, so the server
 * list replaces the local one rather than being appended to it.
 *
 * @param {Array<{id?:string,turn_id?:string,speaker?:string,text?:string}>} turns
 */
export function transcriptFromResume(turns) {
  if (!Array.isArray(turns)) return null;
  const rows = turns
    .filter((t) => t && String(t.text || "").trim())
    .map((t, i) => ({
      id: t.id || t.turn_id || `r${i + 1}`,
      speaker: t.speaker || "agent",
      text: String(t.text),
      interim: false,
    }));
  return rows.length ? rows : null;
}
