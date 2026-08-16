import { Component, useRef } from "react";
import { useFocusTrap } from "./hooks.js";
import { fmtRelative } from "./format.js";

/** Placeholder block sized like the content it replaces, so layout never jumps. */
export function Skeleton({ width = "100%", height = 14, radius = 6, style }) {
  return (
    <span
      className="skeleton"
      style={{ width, height, borderRadius: radius, ...style }}
      aria-hidden="true"
    />
  );
}

export function SkeletonStats({ count = 4 }) {
  return (
    <div className="stat-grid" aria-busy="true">
      {Array.from({ length: count }).map((_, i) => (
        <div className="stat-card" key={i}>
          <Skeleton width="45%" height={11} />
          <Skeleton width="60%" height={28} />
          <Skeleton width="70%" height={11} />
        </div>
      ))}
    </div>
  );
}

export function SkeletonRows({ rows = 5, cols = 4 }) {
  return (
    <div className="skeleton-rows" aria-busy="true">
      {Array.from({ length: rows }).map((_, r) => (
        <div className="skeleton-row" key={r}>
          {Array.from({ length: cols }).map((__, c) => (
            <Skeleton key={c} width={c === 0 ? "30%" : "18%"} height={12} />
          ))}
        </div>
      ))}
    </div>
  );
}

/** Empty state that tells the operator what to do next, not just that it's empty. */
export function EmptyState({ title, hint, action, icon = null }) {
  return (
    <div className="empty-state">
      {icon && <div className="empty-state-icon">{icon}</div>}
      <div className="empty-state-title">{title}</div>
      {hint && <p className="empty-state-hint">{hint}</p>}
      {action && <div className="empty-state-action">{action}</div>}
    </div>
  );
}

/** Live/paused indicator with the age of the data on screen. */
export function Freshness({ lastRun, pending, paused, onTogglePause, onRefresh, intervalLabel }) {
  const stamp = lastRun
    ? fmtRelative(
        `${lastRun.getFullYear()}-${String(lastRun.getMonth() + 1).padStart(2, "0")}-${String(
          lastRun.getDate(),
        ).padStart(2, "0")}T${String(lastRun.getHours()).padStart(2, "0")}:${String(lastRun.getMinutes()).padStart(
          2,
          "0",
        )}:${String(lastRun.getSeconds()).padStart(2, "0")}`,
      )
    : "never";

  return (
    <div className="freshness">
      <span className={`freshness-dot${paused ? " paused" : ""}${pending ? " pulsing" : ""}`} aria-hidden="true" />
      <span className="freshness-text">
        {paused ? "Paused" : "Live"}
        <span className="faint"> · updated {stamp}</span>
        {intervalLabel && !paused && <span className="faint"> · every {intervalLabel}</span>}
      </span>
      {onTogglePause && (
        <button type="button" className="ghost tiny" onClick={onTogglePause}>
          {paused ? "Resume" : "Pause"}
        </button>
      )}
      {onRefresh && (
        <button type="button" className="ghost tiny" onClick={onRefresh} disabled={pending}>
          {pending ? "…" : "Refresh"}
        </button>
      )}
    </div>
  );
}

/** Slide-over detail panel with focus trap and Escape-to-close. */
export function Drawer({ open, title, subtitle, onClose, children, footer, width = 520 }) {
  const ref = useRef(null);
  useFocusTrap(ref, open, onClose);
  if (!open) return null;

  return (
    <div className="drawer-scrim" onMouseDown={(e) => e.target === e.currentTarget && onClose?.()}>
      <aside
        className="drawer"
        style={{ width }}
        role="dialog"
        aria-modal="true"
        aria-label={title}
        ref={ref}
      >
        <header className="drawer-head">
          <div>
            <h2>{title}</h2>
            {subtitle && <div className="drawer-sub mono">{subtitle}</div>}
          </div>
          <button type="button" className="ghost icon-btn" onClick={onClose} aria-label="Close panel">
            ×
          </button>
        </header>
        <div className="drawer-body">{children}</div>
        {footer && <footer className="drawer-foot">{footer}</footer>}
      </aside>
    </div>
  );
}

/** Keeps one broken page from blanking the whole console. */
export class ErrorBoundary extends Component {
  constructor(props) {
    super(props);
    this.state = { error: null };
  }

  static getDerivedStateFromError(error) {
    return { error };
  }

  componentDidCatch(error, info) {
    // eslint-disable-next-line no-console
    console.error("Dashboard page crashed:", error, info);
  }

  render() {
    if (this.state.error) {
      return (
        <div className="panel error-panel">
          <h2>This view hit an error</h2>
          <p className="muted">
            The rest of the console is still running. Reload the view, or switch pages and come back.
          </p>
          <pre className="mono error-trace">{String(this.state.error?.message || this.state.error)}</pre>
          <button type="button" className="primary" onClick={() => this.setState({ error: null })}>
            Retry view
          </button>
        </div>
      );
    }
    return this.props.children;
  }
}
