/**
 * Display label maps for ops UI.
 * Backend enums stay snake_case; UI shows human Title Case.
 */

const STATUS_LABELS = {
  All: "All",
  open: "Open",
  pending_followup: "Pending follow-up",
  closed: "Closed",
};

const WEAKNESS_LABELS = {
  abandoned_or_incomplete: "Abandoned or incomplete",
  abandoned: "Abandoned",
  incomplete: "Incomplete",
  intake: "Intake",
  triage: "Triage",
  routing: "Routing",
  safety: "Safety",
  retrieval: "Retrieval",
  narration: "Narration",
  unknown: "Unknown",
};

const OUTCOME_LABELS = {
  advisory_notified: "Advisory sent",
  orphan_db_sweep: "Orphan sweep",
  escalated_safety: "Safety escalation",
  case_created: "Case created",
  completed: "Completed",
  resolved: "Resolved",
  escalated: "Escalated",
  incomplete: "Incomplete",
};

const PACK_LABELS = {
  automotive_nhtsa: "Automotive",
  finance_cfpb: "Finance",
  consumer_cpsc: "Consumer products",
  medical_maude: "Medical devices",
};

const CAPABILITY_LABELS = {
  stt: "Speech to text",
  tts: "Text to speech",
  barge_in: "Barge-in",
  mic: "Microphone",
  text_path: "Text while in call",
  "text path": "Text while in call",
};

/** Case / interaction status enum → human label. */
export function statusLabel(value) {
  if (value == null || value === "") return "—";
  const key = String(value);
  if (STATUS_LABELS[key] != null) return STATUS_LABELS[key];
  return humanizeKey(key);
}

/** Weakness class / trend key → human label. */
export function weaknessLabel(value) {
  if (value == null || value === "") return "—";
  const key = String(value);
  if (WEAKNESS_LABELS[key] != null) return WEAKNESS_LABELS[key];
  return humanizeKey(key);
}

/** Capability panel key → human label. */
export function capabilityLabel(value) {
  if (value == null || value === "") return "—";
  const key = String(value);
  if (CAPABILITY_LABELS[key] != null) return CAPABILITY_LABELS[key];
  return humanizeKey(key);
}

export function outcomeLabel(value) {
  if (value == null || value === "") return "—";
  const key = String(value);
  if (OUTCOME_LABELS[key] != null) return OUTCOME_LABELS[key];
  return humanizeKey(key);
}

export function packLabel(id) {
  if (id == null || id === "") return "—";
  const key = String(id);
  if (PACK_LABELS[key]) return PACK_LABELS[key];
  return humanizeKey(key);
}

export function safetyFlagLabel(value) {
  const s = String(value || "");
  const q = /^safety_q_(\d+)$/i.exec(s);
  if (q) return `Safety check ${q[1]}`;
  return humanizeKey(s);
}

export function whyTrustedLabel(raw) {
  if (!raw) return "";
  return humanizeKey(
    String(raw)
      .replace(/→/g, " ")
      .replace(/\blive\b/g, "live data")
      .replace(/\bcomputed\b/g, "calculated"),
  );
}

export function displayCopy(text) {
  return String(text || "").replace(/\bP1\b/g, "Critical");
}

export function caseDescription(raw) {
  const s = String(raw || "").trim();
  if (!s || /^nothing$/i.test(s) || s === "—" || s === "-") return "";
  return s;
}

export function cleanFollowupDraft(raw) {
  const s = String(raw || "");
  if (/\(\s*\)/.test(s) && /support case/i.test(s)) return "";
  return s;
}

/** snake_case / kebab → Title Case words. */
export function humanizeKey(value) {
  return String(value)
    .replace(/[_-]+/g, " ")
    .replace(/\s+/g, " ")
    .trim()
    .replace(/\b\w/g, (c) => c.toUpperCase());
}

/**
 * Platform proposal title from raw API fields.
 * Prefer humanized weakness + short id tail over raw snake title.
 */
export function proposalTitle(proposal) {
  if (!proposal || typeof proposal !== "object") return "Improvement proposal";
  const weakness = proposal.weakness_class || "";
  const id = proposal.interaction_id || "";
  const raw = proposal.title || "";
  // If API already sent a human sentence, keep it
  if (raw && !/[_]| on int_/i.test(raw) && raw.length < 120 && /[a-zA-Z]{4,}/.test(raw) && !/^[a-z0-9_]+ on /i.test(raw)) {
    return raw;
  }
  const head = weakness ? weaknessLabel(weakness) : "Contact issue";
  if (id) {
    const short = String(id).length > 18 ? `…${String(id).slice(-10)}` : String(id);
    return `${head} — ${short}`;
  }
  return head;
}

/**
 * Parse or structure proposal detail into { blame, confidence, why } when possible.
 */
export function proposalDetailParts(proposal) {
  const detail = proposal?.detail != null ? String(proposal.detail) : "";
  const parts = { blame: null, confidence: null, why: null, raw: detail };
  // Pattern: blame=intake; confidence=0.54; why=status=abandoned outcome=incomplete; ...
  const blame = /blame\s*=\s*([^;]+)/i.exec(detail);
  const conf = /confidence\s*=\s*([0-9.]+)/i.exec(detail);
  const why = /why\s*=\s*([^;]+)/i.exec(detail);
  if (blame) parts.blame = humanizeKey(blame[1].trim());
  if (conf) parts.confidence = conf[1].trim();
  if (why) parts.why = humanizeKey(why[1].trim().replace(/\s+/g, " "));
  // Fallbacks from structured fields if present
  if (!parts.blame && proposal?.blame) parts.blame = humanizeKey(proposal.blame);
  if (!parts.confidence && proposal?.confidence != null) parts.confidence = String(proposal.confidence);
  return parts;
}

export function formatDetailValue(v) {
  if (v == null) return "—";
  if (typeof v !== "object") return String(v);
  if (v.summary != null) return String(v.summary);
  if (v.text != null) return String(v.text);
  if (v.message != null) return String(v.message);
  if (v.label != null) return String(v.label);
  try {
    return JSON.stringify(v);
  } catch {
    return String(v);
  }
}
