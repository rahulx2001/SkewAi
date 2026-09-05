import { useEffect, useRef, useState } from "react";
import { AUTH_EVENT, fetchMe, getStoredSubject, signOut } from "../apiAuth.js";

export default function AccountSignIn({ pack }) {
  const [open, setOpen] = useState(false);
  const [me, setMe] = useState(null);
  const box = useRef(null);

  async function refresh() {
    try {
      setMe(await fetchMe());
    } catch {
      setMe({ signed_in: false });
    }
  }

  useEffect(() => {
    refresh();
    const on = () => refresh();
    window.addEventListener(AUTH_EVENT, on);
    window.addEventListener("storage", on);
    return () => {
      window.removeEventListener(AUTH_EVENT, on);
      window.removeEventListener("storage", on);
    };
  }, []);

  useEffect(() => {
    if (!open) return undefined;
    const onDown = (e) => {
      if (box.current && !box.current.contains(e.target)) setOpen(false);
    };
    const onKey = (e) => {
      if (e.key === "Escape") setOpen(false);
    };
    document.addEventListener("mousedown", onDown);
    document.addEventListener("keydown", onKey);
    return () => {
      document.removeEventListener("mousedown", onDown);
      document.removeEventListener("keydown", onKey);
    };
  }, [open]);

  const signedIn = Boolean(me?.signed_in);
  const who = signedIn ? me.subject || getStoredSubject() || "Signed in" : "Sign in";
  const sub = signedIn ? me.role || "agent" : pack || "Google account";

  function onFoot() {
    if (signedIn) {
      setOpen((v) => !v);
      return;
    }
    window.location.hash = "signin";
  }

  return (
    <div className="account-wrap" ref={box}>
      <button
        type="button"
        className={"account-foot" + (signedIn ? " signed-in" : "")}
        onClick={onFoot}
        aria-expanded={signedIn ? open : undefined}
        title={signedIn ? `${who} · ${sub}` : "Sign in with Google"}
      >
        <div className="account-meta">
          <div className="who">{who}</div>
          <div className="role">{sub}</div>
        </div>
      </button>

      {open && signedIn && (
        <div className="account-menu" role="dialog" aria-label="Account">
          <div className="account-menu-head">
            Signed in as <strong>{who}</strong>
            <div className="faint">Google / OIDC session</div>
          </div>
          <button type="button" className="ghost" onClick={() => (window.location.hash = "settings")}>
            Open Settings
          </button>
          <button
            type="button"
            onClick={() => {
              signOut();
              setMe({ signed_in: false });
              setOpen(false);
            }}
          >
            Sign out
          </button>
        </div>
      )}
    </div>
  );
}
