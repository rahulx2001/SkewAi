import { useEffect, useState } from "react";
import {
  completeGoogleHandoff,
  fetchMe,
  getStoredSubject,
  saveGoogleProvider,
} from "../src/apiAuth.js";

function routeParams() {
  const raw = window.location.hash.slice(1);
  const q = raw.includes("?") ? raw.slice(raw.indexOf("?") + 1) : "";
  const hp = new URLSearchParams(q);
  const sp = new URLSearchParams(window.location.search);
  for (const [k, v] of sp.entries()) {
    if (!hp.has(k)) hp.set(k, v);
  }
  return hp;
}

function GoogleMark() {
  return (
    <svg className="google-mark" viewBox="0 0 48 48" aria-hidden="true">
      <path fill="#EA4335" d="M24 9.5c3.54 0 6.71 1.22 9.21 3.6l6.85-6.85C35.9 2.38 30.47 0 24 0 14.62 0 6.51 5.38 2.56 13.22l7.98 6.19C12.43 13.72 17.74 9.5 24 9.5z" />
      <path fill="#4285F4" d="M46.98 24.55c0-1.57-.15-3.09-.38-4.55H24v9.02h12.94c-.58 2.96-2.26 5.48-4.78 7.18l7.73 6c4.51-4.18 7.09-10.36 7.09-17.65z" />
      <path fill="#FBBC05" d="M10.53 28.59c-.48-1.45-.76-2.99-.76-4.59s.27-3.14.76-4.59l-7.98-6.19C.92 16.46 0 20.12 0 24c0 3.88.92 7.54 2.56 10.78l7.97-6.19z" />
      <path fill="#34A853" d="M24 48c6.48 0 11.93-2.13 15.89-5.81l-7.73-6c-2.15 1.45-4.92 2.3-8.16 2.3-6.26 0-11.57-4.22-13.47-9.91l-7.98 6.19C6.51 42.62 14.62 48 24 48z" />
    </svg>
  );
}

export default function SignIn() {
  const [status, setStatus] = useState(null);
  const [me, setMe] = useState(null);
  const [err, setErr] = useState("");
  const [busy, setBusy] = useState(false);
  const [clientId, setClientId] = useState("");
  const [clientSecret, setClientSecret] = useState("");

  const redirectUri =
    status?.redirect_uri || "http://127.0.0.1:8000/api/frontline/auth/oidc/callback";

  useEffect(() => {
    const params = routeParams();
    const handoff = params.get("handoff");
    const error = params.get("error");
    if (error) setErr(error.replaceAll("_", " "));

    fetch("/api/frontline/auth/oidc/status")
      .then((r) => (r.ok ? r.json() : {}))
      .then(setStatus)
      .catch(() => setStatus({ configured: false }));

    fetchMe()
      .then((m) => {
        setMe(m);
        if (m?.signed_in && !handoff) {
          window.location.hash = "command";
        }
      })
      .catch(() => setMe({ signed_in: false }));

    if (handoff) {
      setBusy(true);
      completeGoogleHandoff(handoff)
        .then(() => {
          window.location.hash = "command";
        })
        .catch((e) => {
          setErr(String(e.message || e));
          setBusy(false);
        });
    }
  }, []);

  const configured = Boolean(status?.configured);
  const signedIn = Boolean(me?.signed_in);

  function startGoogle() {
    const next = `${window.location.origin}/ui/`;
    window.location.href = `/api/frontline/auth/oidc/start?next=${encodeURIComponent(next)}`;
  }

  async function connectAndStart(e) {
    e.preventDefault();
    setErr("");
    setBusy(true);
    try {
      const out = await saveGoogleProvider({
        clientId: clientId.trim(),
        clientSecret: clientSecret.trim(),
        redirectUri,
      });
      setStatus(out);
      startGoogle();
    } catch (ex) {
      setErr(String(ex.message || ex));
      setBusy(false);
    }
  }

  return (
    <div className="signin-page">
      <div className="signin-card">
        <div className="signin-brand">Skew AI</div>
        <h1>Sign in with Google</h1>
        <p className="sub">
          Google verifies the account. The API exchanges the code, checks the
          ID token, and stores the session in an httpOnly cookie.
        </p>

        {signedIn && !busy && (
          <div className="banner banner-ok" role="status">
            Signed in as {me.subject || getStoredSubject()}.{" "}
            <button type="button" className="ghost" onClick={() => (window.location.hash = "command")}>
              Open console
            </button>
          </div>
        )}

        {err && (
          <div className="banner banner-error" role="alert">
            {err}
          </div>
        )}

        {configured ? (
          <button
            type="button"
            className="google-btn"
            onClick={startGoogle}
            disabled={busy}
          >
            <GoogleMark />
            {busy ? "Finishing Google sign-in…" : "Continue with Google"}
          </button>
        ) : (
          <form className="signin-connect" onSubmit={connectAndStart}>
            <p className="signin-hint">
              Create an OAuth client in Google Cloud Console (APIs &amp; Services
              → Credentials → Create credentials → OAuth client ID → Web
              application). Add this authorized redirect URI:
            </p>
            <code className="signin-redirect">{redirectUri}</code>
            <label>
              Client ID
              <input
                type="text"
                name="google_client_id"
                autoComplete="off"
                spellCheck={false}
                value={clientId}
                onChange={(e) => setClientId(e.target.value)}
                placeholder="….apps.googleusercontent.com"
                required
              />
            </label>
            <label>
              Client secret
              <input
                type="password"
                name="google_client_secret"
                autoComplete="new-password"
                value={clientSecret}
                onChange={(e) => setClientSecret(e.target.value)}
                required
              />
            </label>
            <button type="submit" className="google-btn" disabled={busy}>
              <GoogleMark />
              {busy ? "Connecting…" : "Save and continue with Google"}
            </button>
          </form>
        )}
      </div>
    </div>
  );
}
