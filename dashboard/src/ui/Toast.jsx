import { createContext, useCallback, useContext, useEffect, useMemo, useRef, useState } from "react";

const ToastContext = createContext(null);

let seq = 0;

/**
 * Toast notifications. Errors persist until dismissed because an operator who
 * missed a failed takeover needs to see it whenever they look back at the screen.
 */
export function ToastProvider({ children }) {
  const [toasts, setToasts] = useState([]);
  const timers = useRef(new Map());

  const dismiss = useCallback((id) => {
    setToasts((list) => list.filter((t) => t.id !== id));
    const timer = timers.current.get(id);
    if (timer) {
      clearTimeout(timer);
      timers.current.delete(id);
    }
  }, []);

  const push = useCallback(
    (message, { tone = "info", detail = "", duration } = {}) => {
      const id = ++seq;
      const ttl = duration ?? (tone === "danger" ? 0 : 5000);
      setToasts((list) => [...list.slice(-4), { id, message, detail, tone }]);
      if (ttl > 0) {
        timers.current.set(
          id,
          setTimeout(() => dismiss(id), ttl),
        );
      }
      return id;
    },
    [dismiss],
  );

  useEffect(() => {
    const map = timers.current;
    return () => {
      map.forEach((t) => clearTimeout(t));
      map.clear();
    };
  }, []);

  const api = useMemo(
    () => ({
      push,
      dismiss,
      success: (msg, opts) => push(msg, { ...opts, tone: "ok" }),
      error: (msg, opts) => push(msg, { ...opts, tone: "danger" }),
      warn: (msg, opts) => push(msg, { ...opts, tone: "warn" }),
      info: (msg, opts) => push(msg, { ...opts, tone: "info" }),
    }),
    [push, dismiss],
  );

  return (
    <ToastContext.Provider value={api}>
      {children}
      <div className="toast-stack" role="region" aria-label="Notifications">
        {toasts.map((t) => (
          <div
            key={t.id}
            className={`toast tone-${t.tone}`}
            role={t.tone === "danger" ? "alert" : "status"}
            aria-live={t.tone === "danger" ? "assertive" : "polite"}
          >
            <div className="toast-body">
              <div className="toast-message">{t.message}</div>
              {t.detail && <div className="toast-detail mono">{t.detail}</div>}
            </div>
            <button
              type="button"
              className="toast-close"
              onClick={() => dismiss(t.id)}
              aria-label="Dismiss notification"
            >
              ×
            </button>
          </div>
        ))}
      </div>
    </ToastContext.Provider>
  );
}

export function useToast() {
  const ctx = useContext(ToastContext);
  if (!ctx) throw new Error("useToast must be used inside <ToastProvider>");
  return ctx;
}
