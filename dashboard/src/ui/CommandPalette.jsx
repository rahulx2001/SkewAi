import { useEffect, useMemo, useRef, useState } from "react";
import { useFocusTrap } from "./hooks.js";

/**
 * Subsequence match, the behaviour people expect from editor palettes:
 * "ewb" finds "Early warning board". Score favours earlier and tighter matches
 * so exact prefixes always outrank scattered hits.
 */
function fuzzyScore(haystack, needle) {
  if (!needle) return 0;
  const h = haystack.toLowerCase();
  const n = needle.toLowerCase();
  if (h.includes(n)) return 1000 - h.indexOf(n);

  let score = 0;
  let hIdx = 0;
  let streak = 0;
  for (const ch of n) {
    const found = h.indexOf(ch, hIdx);
    if (found === -1) return -1;
    streak = found === hIdx ? streak + 1 : 0;
    score += 10 + streak * 5 - Math.min(found - hIdx, 10);
    hIdx = found + 1;
  }
  return score;
}

export default function CommandPalette({ open, onClose, commands }) {
  const [query, setQuery] = useState("");
  const [cursor, setCursor] = useState(0);
  const inputRef = useRef(null);
  const listRef = useRef(null);
  const panelRef = useRef(null);
  useFocusTrap(panelRef, open, onClose);

  useEffect(() => {
    if (open) {
      setQuery("");
      setCursor(0);
      // Focus after the dialog paints so the caret lands in the field.
      requestAnimationFrame(() => inputRef.current?.focus());
    }
  }, [open]);

  const results = useMemo(() => {
    if (!query.trim()) return commands.slice(0, 12);
    return commands
      .map((c) => ({ c, score: Math.max(fuzzyScore(c.label, query), fuzzyScore(c.keywords || "", query) - 5) }))
      .filter((r) => r.score > -1)
      .sort((a, b) => b.score - a.score)
      .slice(0, 12)
      .map((r) => r.c);
  }, [commands, query]);

  useEffect(() => {
    setCursor(0);
  }, [query]);

  useEffect(() => {
    const el = listRef.current?.querySelector(`[data-idx="${cursor}"]`);
    el?.scrollIntoView({ block: "nearest" });
  }, [cursor]);

  if (!open) return null;

  const run = (cmd) => {
    onClose();
    cmd?.run?.();
  };

  const onKeyDown = (e) => {
    if (e.key === "ArrowDown") {
      e.preventDefault();
      setCursor((c) => Math.min(c + 1, results.length - 1));
    } else if (e.key === "ArrowUp") {
      e.preventDefault();
      setCursor((c) => Math.max(c - 1, 0));
    } else if (e.key === "Enter") {
      e.preventDefault();
      run(results[cursor]);
    }
  };

  const grouped = results.reduce((acc, cmd, idx) => {
    const group = cmd.group || "Other";
    (acc[group] = acc[group] || []).push({ cmd, idx });
    return acc;
  }, {});

  return (
    <div className="palette-scrim" onMouseDown={(e) => e.target === e.currentTarget && onClose()}>
      <div className="palette" role="dialog" aria-modal="true" aria-label="Command palette" ref={panelRef}>
        <div className="palette-input-row">
          <span className="palette-prompt" aria-hidden="true">
            ⌘
          </span>
          <input
            ref={inputRef}
            className="palette-input"
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            onKeyDown={onKeyDown}
            placeholder="Jump to a view or run an action…"
            aria-label="Search commands"
            aria-controls="palette-list"
            autoComplete="off"
            spellCheck="false"
          />
          <kbd className="palette-esc">esc</kbd>
        </div>

        <div className="palette-list" id="palette-list" role="listbox" ref={listRef}>
          {results.length === 0 && <div className="palette-empty">No matching command</div>}
          {Object.entries(grouped).map(([group, items]) => (
            <div key={group} className="palette-group">
              <div className="palette-group-label">{group}</div>
              {items.map(({ cmd, idx }) => (
                <button
                  key={cmd.id}
                  type="button"
                  data-idx={idx}
                  role="option"
                  aria-selected={idx === cursor}
                  className={`palette-item${idx === cursor ? " active" : ""}`}
                  onMouseEnter={() => setCursor(idx)}
                  onClick={() => run(cmd)}
                >
                  {cmd.Icon && (
                    <span className="palette-ico">
                      <cmd.Icon />
                    </span>
                  )}
                  <span className="palette-label">{cmd.label}</span>
                  {cmd.hint && <span className="palette-hint">{cmd.hint}</span>}
                </button>
              ))}
            </div>
          ))}
        </div>

        <div className="palette-foot">
          <span>
            <kbd>↑</kbd>
            <kbd>↓</kbd> navigate
          </span>
          <span>
            <kbd>↵</kbd> run
          </span>
          <span>
            <kbd>?</kbd> shortcuts
          </span>
        </div>
      </div>
    </div>
  );
}
