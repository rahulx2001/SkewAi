/**
 * Single-tenant pilot auth helpers.
 * Key is saved in Settings → localStorage key `frontline_api_key`.
 * When empty, headers/query are omitted (open local/dev server).
 *
 * Security (SOC 2 / enterprise): localStorage is XSS-accessible. Prefer
 * httpOnly session cookies + OIDC in production. Pilots: FRONTLINE_AUTH_REQUIRED=1
 * and treat the browser as a trusted device only.
 *
 * WebSocket: prefer first-message auth (no query-string secrets).
 * withApiKeyQuery is deprecated and intentionally a no-op for keys.
 */

export const API_KEY_STORAGE = "frontline_api_key";

export function getStoredApiKey() {
  if (typeof localStorage === "undefined") return "";
  try {
    return (localStorage.getItem(API_KEY_STORAGE) || "").trim();
  } catch {
    return "";
  }
}

/** Headers for write/console REST routes (X-API-Key when set). */
export function apiHeaders(extra = {}) {
  const h = { ...extra };
  const key = getStoredApiKey();
  if (key) h["X-API-Key"] = key;
  return h;
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
