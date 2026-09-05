/**
 * Single-tenant pilot auth helpers.
 * Key is kept in MEMORY by default; persisted to localStorage ONLY when the
 * operator checks "Remember on this device" in Settings. Memory-only keys
 * vanish on tab close and are never written to disk, shrinking XSS theft.
 *
 * Security (SOC 2 / enterprise): any JS-accessible key is XSS-accessible.
 * Prefer httpOnly session cookies + OIDC in production (fetchMe uses
 * credentials:same-origin so a signed session works with no key at all).
 * Pilots: FRONTLINE_AUTH_REQUIRED=1 and treat the browser as trusted.
 *
 * WebSocket: prefer first-message auth (no query-string secrets).
 * withApiKeyQuery is deprecated and intentionally a no-op for keys.
 */

export const API_KEY_STORAGE = "frontline_api_key";
export const SUBJECT_STORAGE = "frontline_subject";
export const AUTH_EVENT = "frontline-auth";

// In-memory key (survives SPA navigation, not disk). Set via setApiKey().
let _memKey = "";
let _memOnly = true;

export function setApiKey(key, { remember = false } = {}) {
  _memKey = String(key || "").trim();
  _memOnly = !remember;
  // Only persist when explicitly opted in; otherwise clear disk copy.
  _write(API_KEY_STORAGE, remember ? _memKey : "");
  notifyAuthChange();
}

export function clearApiKey() {
  _memKey = "";
  _write(API_KEY_STORAGE, "");
  notifyAuthChange();
}

function _read(key) {
  if (typeof localStorage === "undefined") return "";
  try {
    return (localStorage.getItem(key) || "").trim();
  } catch {
    return "";
  }
}

function _write(key, value) {
  if (typeof localStorage === "undefined") return;
  try {
    if (value) localStorage.setItem(key, value);
    else localStorage.removeItem(key);
  } catch {
    /* ignore quota / private mode */
  }
}

export function notifyAuthChange() {
  if (typeof window === "undefined") return;
  window.dispatchEvent(new Event(AUTH_EVENT));
}

export function getStoredApiKey() {
  // Memory first (no disk write), then opt-in localStorage copy.
  if (_memKey) return _memKey;
  const disk = _read(API_KEY_STORAGE);
  if (disk) _memKey = disk; // hydrate memory for this tab
  return disk;
}

export function getStoredSubject() {
  return _read(SUBJECT_STORAGE);
}

/** Headers for write/console REST routes. Session rides an httpOnly cookie. */
export function apiHeaders(extra = {}) {
  const h = { ...extra };
  const key = getStoredApiKey();
  if (key) h["X-API-Key"] = key;
  return h;
}

export async function fetchMe() {
  const r = await fetch("/api/frontline/auth/me", {
    headers: apiHeaders(),
    credentials: "same-origin",
  });
  if (!r.ok) return { signed_in: false, status: r.status };
  return r.json();
}

export async function signOut() {
  // Logout MUST invalidate the session everywhere the client holds it:
  // memory key, opt-in disk copy, subject label, AND the server session
  // cookie (item 20). A key that survives logout is a session that survives
  // logout — previously clearApiKey() was never called here.
  clearApiKey();
  _write(SUBJECT_STORAGE, "");
  _memOnly = true;
  try {
    await fetch("/api/frontline/auth/logout", {
      method: "POST",
      credentials: "same-origin",
      headers: apiHeaders(),
    });
  } catch {
    /* cookie clear is best-effort */
  }
  notifyAuthChange();
}

/** Keyless-pilot check: true when no API key is stored anywhere (item 20).

Pure memory/disk probe — the dashboard can operate keyless when the server
runs open (local pilot) or with an httpOnly session (fetchMe signed_in).
Components must use this + apiHeaders() instead of reading storage directly.
*/
export function isKeyless() {
  if (_memKey) return false;
  return !_read(API_KEY_STORAGE);
}

/** Persist Google OAuth client on this machine (dev/pilot). Secret never stored in JS session. */
export async function saveGoogleProvider({ clientId, clientSecret, redirectUri }) {
  const r = await fetch("/api/frontline/auth/oidc/config", {
    method: "PUT",
    credentials: "same-origin",
    headers: { "Content-Type": "application/json", ...apiHeaders() },
    body: JSON.stringify({
      client_id: clientId,
      client_secret: clientSecret,
      redirect_uri: redirectUri || "",
    }),
  });
  if (!r.ok) {
    const detail = await r.text();
    throw new Error(detail || `Could not save Google client (${r.status})`);
  }
  return r.json();
}

/** Finish Google OIDC after the API callback redirects with a one-time handoff. */
export async function completeGoogleHandoff(handoff) {
  const code = String(handoff || "").trim();
  if (!code) throw new Error("Missing Google handoff");
  const r = await fetch("/api/frontline/auth/oidc/complete", {
    method: "POST",
    credentials: "same-origin",
    headers: { "Content-Type": "application/json", ...apiHeaders() },
    body: JSON.stringify({ handoff: code }),
  });
  if (!r.ok) {
    const detail = await r.text();
    throw new Error(detail || `Google sign-in failed (${r.status})`);
  }
  const out = await r.json();
  if (out.token) {
    throw new Error("server leaked session token to JavaScript");
  }
  if (out.subject || out.email) {
    _write(SUBJECT_STORAGE, out.subject || out.email || "");
  }
  notifyAuthChange();
  return out;
}

/**
 * @deprecated Query-string API keys leak via logs/history. Returns URL unchanged.
 * Use sendWsAuth(ws) after open instead.
 */
export function withApiKeyQuery(url) {
  return url;
}

/**
 * After WebSocket open, send auth frame when a pilot key is stored.
 * Server authenticate_websocket accepts this as the preferred browser path.
 */
export function sendWsAuth(ws) {
  if (!ws || typeof ws.send !== "function") return;
  const key = getStoredApiKey();
  if (!key) return;
  try {
    ws.send(JSON.stringify({ type: "auth", api_key: key }));
  } catch {
    /* ignore */
  }
}
