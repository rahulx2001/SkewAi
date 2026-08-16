import { useCallback, useEffect, useRef, useState } from "react";

/** State mirrored into localStorage so shell preferences survive a reload. */
export function useLocalStorage(key, initial) {
  const [value, setValue] = useState(() => {
    try {
      const raw = window.localStorage.getItem(key);
      return raw === null ? initial : JSON.parse(raw);
    } catch {
      return initial;
    }
  });

  useEffect(() => {
    try {
      window.localStorage.setItem(key, JSON.stringify(value));
    } catch {
      /* quota or private mode — preference is best-effort */
    }
  }, [key, value]);

  return [value, setValue];
}

/**
 * Interval polling that pauses while the tab is hidden and can be paused by the
 * operator. Returns the last-success time so callers can show data freshness.
 */
export function usePolling(fn, intervalMs, { enabled = true } = {}) {
  const [paused, setPaused] = useState(false);
  const [lastRun, setLastRun] = useState(null);
  const [pending, setPending] = useState(false);
  const fnRef = useRef(fn);
  fnRef.current = fn;

  const run = useCallback(async () => {
    setPending(true);
    try {
      await fnRef.current();
      setLastRun(new Date());
    } finally {
      setPending(false);
    }
  }, []);

  useEffect(() => {
    if (!enabled) return undefined;
    let cancelled = false;
    let timer = null;

    const tick = async () => {
      if (cancelled) return;
      if (!paused && document.visibilityState === "visible") await run();
      if (!cancelled) timer = setTimeout(tick, intervalMs);
    };

    run();
    timer = setTimeout(tick, intervalMs);

    const onVisible = () => {
      if (document.visibilityState === "visible" && !paused) run();
    };
    document.addEventListener("visibilitychange", onVisible);

    return () => {
      cancelled = true;
      if (timer) clearTimeout(timer);
      document.removeEventListener("visibilitychange", onVisible);
    };
  }, [enabled, intervalMs, paused, run]);

  return { refresh: run, paused, setPaused, lastRun, pending };
}

/**
 * Global hotkeys. `bindings` maps a chord like "mod+k" or "?" to a handler.
 * Keystrokes typed into inputs are ignored unless the chord uses a modifier.
 */
export function useHotkeys(bindings, deps = []) {
  const ref = useRef(bindings);
  ref.current = bindings;

  useEffect(() => {
    const onKey = (e) => {
      const target = e.target;
      const typing =
        target &&
        (target.tagName === "INPUT" ||
          target.tagName === "TEXTAREA" ||
          target.tagName === "SELECT" ||
          target.isContentEditable);

      const mod = e.metaKey || e.ctrlKey;
      const key = e.key.toLowerCase();
      const chords = [];
      if (mod) chords.push(`mod+${key}`);
      if (e.shiftKey) chords.push(`shift+${key}`);
      if (!mod && !e.altKey) chords.push(key);

      for (const chord of chords) {
        const handler = ref.current[chord];
        if (!handler) continue;
        if (typing && !chord.startsWith("mod+")) continue;
        e.preventDefault();
        handler(e);
        return;
      }
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, deps);
}

/** Keeps a value from re-rendering downstream more often than `delay`. */
export function useDebounced(value, delay = 200) {
  const [debounced, setDebounced] = useState(value);
  useEffect(() => {
    const t = setTimeout(() => setDebounced(value), delay);
    return () => clearTimeout(t);
  }, [value, delay]);
  return debounced;
}

/** Traps Tab focus inside a container while it is open (dialogs, drawers). */
export function useFocusTrap(ref, active, onClose) {
  useEffect(() => {
    if (!active || !ref.current) return undefined;
    const node = ref.current;
    const previous = document.activeElement;

    const selector =
      'a[href], button:not([disabled]), input:not([disabled]), select:not([disabled]), textarea:not([disabled]), [tabindex]:not([tabindex="-1"])';

    const focusables = () => Array.from(node.querySelectorAll(selector)).filter((el) => el.offsetParent !== null);
    const first = focusables()[0];
    if (first) first.focus();

    const onKey = (e) => {
      if (e.key === "Escape") {
        e.stopPropagation();
        onClose?.();
        return;
      }
      if (e.key !== "Tab") return;
      const items = focusables();
      if (items.length === 0) return;
      const firstEl = items[0];
      const lastEl = items[items.length - 1];
      if (e.shiftKey && document.activeElement === firstEl) {
        e.preventDefault();
        lastEl.focus();
      } else if (!e.shiftKey && document.activeElement === lastEl) {
        e.preventDefault();
        firstEl.focus();
      }
    };

    node.addEventListener("keydown", onKey);
    return () => {
      node.removeEventListener("keydown", onKey);
      if (previous && previous.focus) previous.focus();
    };
  }, [ref, active, onClose]);
}
