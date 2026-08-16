/** Minimal stroke icons — one house style (no emoji, no Lucide package). */
const s = { width: 18, height: 18, viewBox: "0 0 24 24", fill: "none", stroke: "currentColor", strokeWidth: 1.6, strokeLinecap: "round", strokeLinejoin: "round", "aria-hidden": true };

export function IconGrid(p) {
  return (
    <svg {...s} {...p}>
      <rect x="3" y="3" width="7" height="7" rx="1" />
      <rect x="14" y="3" width="7" height="7" rx="1" />
      <rect x="3" y="14" width="7" height="7" rx="1" />
      <rect x="14" y="14" width="7" height="7" rx="1" />
    </svg>
  );
}
export function IconMic(p) {
  return (
    <svg {...s} {...p}>
      <path d="M12 2a3 3 0 0 1 3 3v7a3 3 0 0 1-6 0V5a3 3 0 0 1 3-3z" />
      <path d="M19 10v2a7 7 0 0 1-14 0v-2" />
      <line x1="12" y1="19" x2="12" y2="22" />
    </svg>
  );
}
export function IconHeadset(p) {
  return (
    <svg {...s} {...p}>
      <path d="M4 14v-2a8 8 0 0 1 16 0v2" />
      <path d="M4 14v4a2 2 0 0 0 2 2h1v-6H6a2 2 0 0 0-2 2z" />
      <path d="M20 14v4a2 2 0 0 1-2 2h-1v-6h1a2 2 0 0 1 2 2z" />
    </svg>
  );
}
export function IconFolder(p) {
  return (
    <svg {...s} {...p}>
      <path d="M3 7a2 2 0 0 1 2-2h4l2 2h8a2 2 0 0 1 2 2v8a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2V7z" />
    </svg>
  );
}
export function IconPulse(p) {
  return (
    <svg {...s} {...p}>
      <polyline points="3 12 7 12 10 5 14 19 17 12 21 12" />
    </svg>
  );
}
export function IconAlert(p) {
  return (
    <svg {...s} {...p}>
      <path d="M10.3 3.9 1.8 18a2 2 0 0 0 1.7 3h17a2 2 0 0 0 1.7-3L13.7 3.9a2 2 0 0 0-3.4 0z" />
      <line x1="12" y1="9" x2="12" y2="13" />
      <line x1="12" y1="17" x2="12.01" y2="17" />
    </svg>
  );
}
export function IconChart(p) {
  return (
    <svg {...s} {...p}>
      <line x1="4" y1="20" x2="20" y2="20" />
      <rect x="6" y="10" width="3" height="8" rx="0.5" />
      <rect x="11" y="6" width="3" height="12" rx="0.5" />
      <rect x="16" y="12" width="3" height="6" rx="0.5" />
    </svg>
  );
}
export function IconShield(p) {
  return (
    <svg {...s} {...p}>
      <path d="M12 3l8 3v6c0 5-3.5 8.5-8 10-4.5-1.5-8-5-8-10V6l8-3z" />
    </svg>
  );
}
export function IconBuilding(p) {
  return (
    <svg {...s} {...p}>
      <rect x="4" y="3" width="16" height="18" rx="1" />
      <path d="M9 21V12h6v9" />
      <path d="M8 7h.01M12 7h.01M16 7h.01M8 11h.01M12 11h.01M16 11h.01" />
    </svg>
  );
}
export function IconLayers(p) {
  return (
    <svg {...s} {...p}>
      <polygon points="12 2 2 7 12 12 22 7 12 2" />
      <polyline points="2 17 12 22 22 17" />
      <polyline points="2 12 12 17 22 12" />
    </svg>
  );
}
export function IconGear(p) {
  return (
    <svg {...s} {...p}>
      <circle cx="12" cy="12" r="3" />
      <path d="M19.4 15a1.7 1.7 0 0 0 .3 1.8l.1.1a2 2 0 1 1-2.8 2.8l-.1-.1a1.7 1.7 0 0 0-1.8-.3 1.7 1.7 0 0 0-1 1.5V21a2 2 0 1 1-4 0v-.1a1.7 1.7 0 0 0-1-1.5 1.7 1.7 0 0 0-1.8.3l-.1.1a2 2 0 1 1-2.8-2.8l.1-.1a1.7 1.7 0 0 0 .3-1.8 1.7 1.7 0 0 0-1.5-1H3a2 2 0 1 1 0-4h.1a1.7 1.7 0 0 0 1.5-1 1.7 1.7 0 0 0-.3-1.8l-.1-.1a2 2 0 1 1 2.8-2.8l.1.1a1.7 1.7 0 0 0 1.8.3H9a1.7 1.7 0 0 0 1-1.5V3a2 2 0 1 1 4 0v.1a1.7 1.7 0 0 0 1 1.5 1.7 1.7 0 0 0 1.8-.3l.1-.1a2 2 0 1 1 2.8 2.8l-.1.1a1.7 1.7 0 0 0-.3 1.8V9c.3.6.9 1 1.5 1H21a2 2 0 1 1 0 4h-.1a1.7 1.7 0 0 0-1.5 1z" />
    </svg>
  );
}
export function IconPhone(p) {
  return (
    <svg {...s} {...p}>
      <path d="M22 16.9v3a2 2 0 0 1-2.2 2 19.8 19.8 0 0 1-8.6-3.1 19.5 19.5 0 0 1-6-6A19.8 19.8 0 0 1 2.1 4.2 2 2 0 0 1 4.1 2h3a2 2 0 0 1 2 1.7c.1.9.3 1.8.6 2.6a2 2 0 0 1-.5 2.1L8 9.9a16 16 0 0 0 6 6l1.5-1.2a2 2 0 0 1 2.1-.4c.8.3 1.7.5 2.6.6a2 2 0 0 1 1.8 2z" />
    </svg>
  );
}
export function IconSpeaker(p) {
  return (
    <svg {...s} {...p}>
      <polygon points="11 5 6 9 2 9 2 15 6 15 11 19 11 5" />
      <path d="M15.5 8.5a5 5 0 0 1 0 7" />
      <path d="M19 5a9 9 0 0 1 0 14" />
    </svg>
  );
}
export function IconHangup(p) {
  return (
    <svg {...s} {...p}>
      <path d="M10.7 5.1a16 16 0 0 1 12.2 12.2l-2.4.6a2 2 0 0 1-2.3-1.2l-.8-2a2 2 0 0 1 .5-2.2l1.3-1.2a12 12 0 0 0-6.3-6.3L11.7 6a2 2 0 0 1-2.2.5l-2-.8A2 2 0 0 1 6.3 3.4l.6-2.4z" transform="rotate(135 12 12)" />
    </svg>
  );
}
export function IconSpark(p) {
  return (
    <svg {...s} {...p}>
      <path d="M12 2v4M12 18v4M4.9 4.9l2.8 2.8M16.3 16.3l2.8 2.8M2 12h4M18 12h4M4.9 19.1l2.8-2.8M16.3 7.7l2.8-2.8" />
      <circle cx="12" cy="12" r="3" />
    </svg>
  );
}
