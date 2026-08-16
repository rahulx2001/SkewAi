/**
 * Shared ops actions used by Command Center + Command Palette.
 * Keeps deep-links and demo traffic one source of truth.
 */
import { apiHeaders } from "../apiAuth.js";

export const SS = {
  caseSev: "frontline:case_filter_sev",
  caseStatus: "frontline:case_filter_status",
  caseSelect: "frontline:case_select_id",
  consoleSelect: "frontline:console_select_id",
  caseSearch: "frontline:case_search_q",
};

export function goHash(id) {
  window.location.hash = id;
}

export function openCases({ severity, status, caseId, q } = {}) {
  try {
    if (severity) sessionStorage.setItem(SS.caseSev, severity);
    else sessionStorage.removeItem(SS.caseSev);
    if (status) sessionStorage.setItem(SS.caseStatus, status);
    else sessionStorage.removeItem(SS.caseStatus);
    if (caseId) sessionStorage.setItem(SS.caseSelect, caseId);
    if (q) sessionStorage.setItem(SS.caseSearch, q);
  } catch {
    /* ignore */
  }
  goHash("cases");
}

export function openConsole(interactionId) {
  try {
    if (interactionId) sessionStorage.setItem(SS.consoleSelect, interactionId);
  } catch {
    /* ignore */
  }
  goHash("console");
}

export function consumeSession(key) {
  try {
    const v = sessionStorage.getItem(key);
    if (v != null) sessionStorage.removeItem(key);
    return v;
  } catch {
    return null;
  }
}

/** Replay N corpus records as simulated contacts (fills wallboard / analytics). */
export async function simulateTraffic({ count = 15, speed = "instant" } = {}) {
  const params = new URLSearchParams({
    count: String(count),
    speed: String(speed),
  });
  const r = await fetch(`/api/frontline/simulate?${params}`, {
    method: "POST",
    headers: apiHeaders(),
  });
  if (!r.ok) {
    const t = await r.text().catch(() => "");
    throw new Error(`simulate failed (${r.status}) ${t.slice(0, 160)}`);
  }
  return r.json();
}

export async function fetchOpenP1Cases(limit = 10) {
  const r = await fetch(
    `/api/frontline/cases?severity=Critical&status=open&limit=${limit}`,
    { headers: apiHeaders() },
  );
  if (!r.ok) return [];
  const d = await r.json();
  return d.cases || [];
}
