import { useCallback, useEffect, useMemo, useState } from "react";
import CallWidget from "../routes/CallWidget.jsx";
import LiveContactConsole from "../routes/LiveContactConsole.jsx";
import CaseQueue from "../routes/CaseQueue.jsx";
import EarlyWarningBoard from "../routes/EarlyWarningBoard.jsx";
import InsightsBoard from "../routes/InsightsBoard.jsx";
import FeatureStudio from "../routes/FeatureStudio.jsx";
import Settings from "../routes/Settings.jsx";
import CommandCenter from "../routes/CommandCenter.jsx";
import SignIn from "../routes/SignIn.jsx";
import UserJourneyGuide from "../routes/UserJourneyGuide.jsx";
import TrustDesk from "../routes/TrustDesk.jsx";
import TrustPipeline from "../routes/TrustPipeline.jsx";
import EnterpriseOps from "../routes/EnterpriseOps.jsx";
import QualityEconomics from "../routes/QualityEconomics.jsx";
import PackBuilder from "../routes/PackBuilder.jsx";
import PlatformOS from "../routes/PlatformOS.jsx";
import CommandPalette from "./ui/CommandPalette.jsx";
import { ToastProvider, useToast } from "./ui/Toast.jsx";
import { ErrorBoundary } from "./ui/Feedback.jsx";
import { useHotkeys, useLocalStorage } from "./ui/hooks.js";
import { AUTH_EVENT, apiHeaders, completeGoogleHandoff, fetchMe } from "./apiAuth.js";
import AccountSignIn from "./ui/AccountSignIn.jsx";
import { canonicalizeHash, goHash, hashQueryObject, openCases, openConsole, parseLocationHash, simulateTraffic } from "./ui/opsActions.js";
import {
  IconAlert,
  IconFolder,
  IconGear,
  IconGrid,
  IconHeadset,
  IconLayers,
  IconMic,
  IconShield,
  IconSpark,
} from "./icons.jsx";
import { packLabel } from "./ui/labels.js";

const NAV_GROUPS = [
  {
    label: "Operate",
    items: [
      { id: "command", label: "Command center", Icon: IconGrid, route: CommandCenter, keywords: "wallboard home overview live" },
      { id: "call", label: "Voice agent", Icon: IconMic, route: CallWidget, keywords: "call widget mic speak contact" },
      { id: "console", label: "Live console", Icon: IconHeadset, route: LiveContactConsole, keywords: "supervisor takeover transcript" },
      { id: "cases", label: "Case queue", Icon: IconFolder, route: CaseQueue, keywords: "tickets severity priority p1 critical" },
    ],
  },
  {
    label: "Intelligence",
    items: [
      { id: "warning", label: "Early warning", Icon: IconAlert, route: EarlyWarningBoard, keywords: "clusters risk investigations insights csat dollars copq" },
      { id: "insights", label: "Insights", Icon: IconSpark, route: InsightsBoard, keywords: "insights trends categories sentiment" },
      { id: "studio", label: "Feature studio", Icon: IconSpark, route: FeatureStudio, keywords: "feature studio forecast planning experiments" },
      { id: "economics", label: "Quality economics", Icon: IconSpark, route: QualityEconomics, keywords: "cost quality economics copq roi" },
    ],
  },
  {
    label: "Trust & platform",
    items: [
      { id: "trust", label: "Trust pipeline", Icon: IconShield, route: TrustPipeline, keywords: "pipeline quality trust scorecards" },
      { id: "enterprise", label: "Enterprise ops", Icon: IconLayers, route: EnterpriseOps, keywords: "enterprise graph memory scenarios copilot" },
      { id: "audits", label: "Trust", Icon: IconShield, route: TrustDesk, keywords: "audit groundedness labels lineage provenance eval" },
      { id: "platform", label: "Platform", Icon: IconLayers, route: PlatformOS, keywords: "governance deployments proposals v3 enterprise copilot" },
      { id: "builder", label: "Pack builder", Icon: IconFolder, route: PackBuilder, keywords: "pack builder csv mapping profile" },
      { id: "settings", label: "Settings", Icon: IconGear, route: Settings, keywords: "api key pack switch webhook theme lab builder" },
    ],
  },
];

const ALL_NAV = NAV_GROUPS.flatMap((g) => g.items);
const EXTRA_PAGES = [
  { id: "guide", label: "User guide", route: UserJourneyGuide, keywords: "guide walkthrough journey onboarding" },
  { id: "signin", label: "Sign in", route: SignIn, keywords: "google oidc" },
];
const ALL_PAGES = [...ALL_NAV, ...EXTRA_PAGES];
const THEMES = ["dark", "light"];

function useHashRoute() {
  const [raw, setRaw] = useState(() => {
    canonicalizeHash();
    return window.location.hash;
  });
  useEffect(() => {
    const on = () => {
      canonicalizeHash();
      setRaw(window.location.hash);
    };
    window.addEventListener("hashchange", on);
    return () => window.removeEventListener("hashchange", on);
  }, []);
  const { id } = parseLocationHash();
  return [
    id,
    (next) => {
      const { id: cur } = parseLocationHash();
      if (cur === next) return;
      window.location.hash = next;
    },
    raw,
  ];
}

function ShortcutSheet({ open, onClose }) {
  if (!open) return null;
  const rows = [
    ["⌘ K / Ctrl K", "Open command palette"],
    ["g then j", "User journey & guide"],
    ["g then c", "Command center"],
    ["g then v", "Voice agent"],
    ["g then l", "Live console"],
    ["g then q", "Case queue"],
    ["g then w", "Early warning"],
    ["g then a", "Trust"],
    ["g then p", "Platform"],
    ["g then s", "Settings"],
    ["g then i", "Insights"],
    ["[", "Collapse / expand sidebar"],
    ["t", "Cycle theme (dark / light)"],
    ["r", "Refresh the active view"],
    ["?", "This sheet"],
    ["esc", "Close any overlay"],
  ];
  return (
    <div className="palette-scrim" onMouseDown={(e) => e.target === e.currentTarget && onClose()}>
      <div className="shortcut-sheet" role="dialog" aria-modal="true" aria-label="Keyboard shortcuts">
        <header>
          <h2>Keyboard shortcuts</h2>
          <button type="button" className="ghost icon-btn" onClick={onClose} aria-label="Close">
            ×
          </button>
        </header>
        <dl>
          {rows.map(([k, v]) => (
            <div className="shortcut-row" key={k}>
              <dt>
                <kbd>{k}</kbd>
              </dt>
              <dd>{v}</dd>
            </div>
          ))}
        </dl>
      </div>
    </div>
  );
}

function Shell() {
  const [route, setRoute] = useHashRoute();
  const [health, setHealth] = useState(null);
  const [healthError, setHealthError] = useState(false);
  const [collapsed, setCollapsed] = useLocalStorage("fl.sidebar.collapsed", false);
  const [theme, setTheme] = useLocalStorage("fl.theme", "dark");
  const [density, setDensity] = useLocalStorage("fl.density", "comfortable");
  const [paletteOpen, setPaletteOpen] = useState(false);
  const [shortcutsOpen, setShortcutsOpen] = useState(false);
  const [mobileNavOpen, setMobileNavOpen] = useState(false);
  const [refreshKey, setRefreshKey] = useState(0);
  const [me, setMe] = useState(null);
  const toast = useToast();

  const extra = route === "signin" ? EXTRA_PAGES.find((p) => p.id === "signin") : null;
  const fallback = ALL_NAV.find((n) => n.id === "command") || ALL_NAV[0];
  const active = extra || ALL_PAGES.find((n) => n.id === route) || fallback;
  const Page = active.route;
  const liveSessionRoute = active.id === "call" || active.id === "console";
  const hashQuery = hashQueryObject();

  // Drop retired wallboard theme if still stored
  useEffect(() => {
    if (theme === "wallboard" || !THEMES.includes(theme)) {
      setTheme("dark");
    }
  }, [theme, setTheme]);

  const activeTheme = THEMES.includes(theme) ? theme : "dark";

  useEffect(() => {
    document.documentElement.setAttribute("data-theme", activeTheme);
    document.documentElement.setAttribute("data-density", density);
  }, [activeTheme, density]);

  const loadHealth = useCallback(async () => {
    try {
      const r = await fetch("/health", { headers: apiHeaders() });
      if (!r.ok) throw new Error(String(r.status));
      setHealth(await r.json());
      setHealthError(false);
    } catch (e) {
      setHealthError(true);
      throw e;
    }
  }, []);

  useEffect(() => {
    loadHealth().catch(() => {});
    const t = setInterval(() => loadHealth().catch(() => {}), 20000);
    return () => clearInterval(t);
  }, [loadHealth, route]);

  useEffect(() => {
    if (route === "signin" || route === "guide") return;
    if (route === "main") {
      setRoute("command");
      return;
    }
    if (!ALL_PAGES.some((n) => n.id === route)) setRoute("command");
  }, [route, setRoute]);

  useEffect(() => {
    const raw = window.location.hash.slice(1);
    const q = raw.includes("?") ? raw.slice(raw.indexOf("?") + 1) : "";
    const params = new URLSearchParams(q);
    const handoff = params.get("handoff");
    if (handoff) {
      completeGoogleHandoff(handoff)
        .then(() => {
          window.location.hash = raw.split("?")[0] || "command";
        })
        .catch((e) => {
          toast.error(String(e.message || e || "Google sign-in failed"));
        });
    }
    fetchMe()
      .then(setMe)
      .catch(() => setMe({ signed_in: false }));
    const on = () => {
      fetchMe()
        .then(setMe)
        .catch(() => setMe({ signed_in: false }));
    };
    window.addEventListener(AUTH_EVENT, on);
    return () => window.removeEventListener(AUTH_EVENT, on);
  }, []);

  useEffect(() => {
    setMobileNavOpen(false);
  }, [route]);

  const cycleTheme = useCallback(() => {
    setTheme((cur) => {
      const base = THEMES.includes(cur) ? cur : "dark";
      return THEMES[(THEMES.indexOf(base) + 1) % THEMES.length];
    });
  }, [setTheme]);

  const commands = useMemo(() => {
    const nav = [
      ...ALL_NAV.map((n) => ({
        id: `nav-${n.id}`,
        label: n.label,
        group: "Go to",
        Icon: n.Icon,
        keywords: n.keywords,
        hint: n.id === active.id ? "current" : "",
        run: () => setRoute(n.id),
      })),
      {
        id: "nav-guide",
        label: "User guide",
        group: "Go to",
        Icon: IconSpark,
        keywords: "guide walkthrough journey onboarding",
        run: () => setRoute("guide"),
      },
      {
        id: "nav-insights",
        label: "Insights (friction proxy)",
        group: "Go to",
        keywords: "csat product gap analytics",
        run: () => goHash("warning?tab=insights"),
      },
      {
        id: "nav-economics",
        label: "Quality economics",
        group: "Go to",
        keywords: "copq dollar hotspot",
        run: () => goHash("warning?tab=economics"),
      },
      {
        id: "nav-lab",
        label: "Feature lab",
        group: "Go to",
        keywords: "studio booking coach drain demo",
        run: () => goHash("settings?tab=lab"),
      },
      {
        id: "nav-builder",
        label: "Pack builder",
        group: "Go to",
        keywords: "csv upload mapping lint",
        run: () => goHash("settings?tab=builder"),
      },
    ];

    const actions = [
      {
        id: "act-simulate-15",
        label: "Simulate 15 contacts (fill Command center)",
        group: "Ops power",
        keywords: "demo seed traffic simulate corpus",
        hint: "POST /simulate",
        run: async () => {
          try {
            toast.info("Simulating traffic…");
            const d = await simulateTraffic({ count: 15 });
            toast.success(
              `Simulated ${d.completed ?? d.count ?? 15} contacts` +
                (d.investigations_opened != null
                  ? ` · inv ${d.investigations_opened}`
                  : d.opened_investigations != null
                    ? ` · inv ${d.opened_investigations}`
                    : ""),
            );
            setRefreshKey((k) => k + 1);
            setRoute("command");
          } catch (e) {
            toast.error(String(e.message || e));
          }
        },
      },
      {
        id: "act-p1-queue",
        label: "Open Critical case queue",
        group: "Ops power",
        keywords: "priority critical p1 fire queue",
        run: () => openCases({ severity: "Critical", status: "open" }),
      },
      {
        id: "act-open-cases",
        label: "Open all open cases",
        group: "Ops power",
        keywords: "queue triage",
        run: () => openCases({ status: "open" }),
      },
      {
        id: "act-voice",
        label: "Start voice agent",
        group: "Ops power",
        keywords: "call mic speak",
        run: () => goHash("call"),
      },
      {
        id: "act-console",
        label: "Open live supervisor console",
        group: "Ops power",
        keywords: "takeover headset",
        run: () => openConsole(),
      },
      {
        id: "act-studio",
        label: "Feature lab",
        group: "Ops power",
        keywords: "forecast fairness booking studio",
        run: () => goHash("settings?tab=lab"),
      },
      {
        id: "act-theme",
        label: "Cycle theme (dark / light)",
        group: "Actions",
        keywords: "dark light contrast display",
        hint: activeTheme,
        run: cycleTheme,
      },
      {
        id: "act-density",
        label: "Toggle density (comfortable / compact)",
        group: "Actions",
        keywords: "compact rows spacing",
        hint: density,
        run: () => setDensity((d) => (d === "compact" ? "comfortable" : "compact")),
      },
      {
        id: "act-sidebar",
        label: collapsed ? "Expand sidebar" : "Collapse sidebar",
        group: "Actions",
        keywords: "nav hide focus",
        run: () => setCollapsed((c) => !c),
      },
      {
        id: "act-refresh",
        label: "Refresh current view",
        group: "Actions",
        keywords: "reload poll data",
        run: () => setRefreshKey((k) => k + 1),
      },
      {
        id: "act-shortcuts",
        label: "Show keyboard shortcuts",
        group: "Actions",
        keywords: "help keys hotkeys",
        run: () => setShortcutsOpen(true),
      },
      {
        id: "act-health",
        label: "Re-check system health",
        group: "Actions",
        keywords: "status db pack ping",
        run: async () => {
          try {
            await loadHealth();
          } catch (e) {
            toast.error(String(e.message || e || "Health check failed"));
          }
        },
      },
    ];

    return [...nav, ...actions];
  }, [active.id, collapsed, cycleTheme, density, loadHealth, setCollapsed, setDensity, setRoute, theme, toast]);

  // "g" then a letter jumps between views, the way ops tools and mail clients do.
  const [pendingG, setPendingG] = useState(false);
  useEffect(() => {
    if (!pendingG) return undefined;
    const t = setTimeout(() => setPendingG(false), 900);
    return () => clearTimeout(t);
  }, [pendingG]);

  useHotkeys(
    {
      "mod+k": () => setPaletteOpen((o) => !o),
      "?": () => setShortcutsOpen(true),
      "[": () => setCollapsed((c) => !c),
      t: () => cycleTheme(),
      r: () => setRefreshKey((k) => k + 1),
      g: () => setPendingG(true),
      j: () => pendingG && (setRoute("guide"), setPendingG(false)),
      c: () => pendingG && (setRoute("command"), setPendingG(false)),
      v: () => pendingG && (setRoute("call"), setPendingG(false)),
      l: () => pendingG && (setRoute("console"), setPendingG(false)),
      q: () => pendingG && (setRoute("cases"), setPendingG(false)),
      w: () => pendingG && (setRoute("warning"), setPendingG(false)),
      s: () => pendingG && (setRoute("settings"), setPendingG(false)),
      a: () => pendingG && (setRoute("audits"), setPendingG(false)),
      p: () => pendingG && (setRoute("platform"), setPendingG(false)),
      i: () => pendingG && (goHash("warning?tab=insights"), setPendingG(false)),
      escape: () => {
        setPaletteOpen(false);
        setShortcutsOpen(false);
        setMobileNavOpen(false);
        window.dispatchEvent(new Event("frontline-escape"));
      },
    },
    [pendingG, cycleTheme, setCollapsed, setRoute],
  );

  const statusTone = healthError ? "danger" : health?.status === "ok" ? "ok" : "warn";
  const statusText = healthError ? "unreachable" : health?.status || "connecting";

  if (route === "signin") {
    return (
      <div className="signin-shell">
        <header className="signin-top">
          <button
            type="button"
            className="brand-mark signin-brand-btn"
            onClick={() => setRoute("command")}
          >
            Skew <em>AI</em>
          </button>
          <button
            type="button"
            className="ghost"
            onClick={cycleTheme}
            title={`Theme: ${activeTheme} (t)`}
          >
            {activeTheme === "light" ? "Dark" : "Light"}
          </button>
        </header>
        <SignIn />
      </div>
    );
  }

  const navList = (
    <>
      {NAV_GROUPS.map((g) => (
        <div key={g.label} className="nav-group">
          <div className="nav-group-label">{g.label}</div>
          {g.items.map((n) => {
            const Icon = n.Icon;
            const isActive = n.id === active.id;
            return (
              <button
                key={n.id}
                type="button"
                className={"nav-item" + (isActive ? " active" : "")}
                aria-current={isActive ? "page" : undefined}
                onClick={() => setRoute(n.id)}
                title={collapsed ? n.label : undefined}
              >
                <span className="nav-ico">
                  <Icon />
                </span>
                <span className="nav-text">{n.label}</span>
              </button>
            );
          })}
        </div>
      ))}
    </>
  );

  return (
    <div className={`app${collapsed ? " collapsed" : ""}`}>
      <a
        className="skip-link"
        href="#main"
        onClick={(e) => {
          e.preventDefault();
          document.getElementById("main")?.focus();
        }}
      >
        Skip to main content
      </a>

      <aside className="sidebar" aria-label="Primary">
        <div className="brand">
          <div className="brand-row">
            <div className="brand-copy">
              <div className="brand-mark">
                Skew <em>AI</em>
              </div>
            </div>
          </div>
          <button
            type="button"
            className="rail-pack"
            title={health?.active_pack || "pack"}
            onClick={() => setRoute("settings")}
          >
            <span>{packLabel(health?.active_pack || "automotive_nhtsa")}</span>
          </button>
          <button
            type="button"
            className="rail-search"
            onClick={() => setPaletteOpen(true)}
            aria-label="Open command palette"
          >
            <span>Search Console…</span>
            <kbd>⌘K</kbd>
          </button>
        </div>

        {navList}

        <div className="sidebar-foot">
          <button
            type="button"
            className="ghost collapse-btn"
            onClick={() => setCollapsed((c) => !c)}
            aria-label={collapsed ? "Expand sidebar" : "Collapse sidebar"}
            title={collapsed ? "Expand sidebar ([)" : "Collapse sidebar ([)"}
          >
            {collapsed ? "»" : "Collapse"}
          </button>
          <AccountSignIn />
        </div>
      </aside>

      <div className="content-col">
        <header className="topbar">
          <button
            type="button"
            className="ghost icon-btn mobile-nav-btn"
            onClick={() => setMobileNavOpen((o) => !o)}
            aria-label="Toggle navigation"
            aria-expanded={mobileNavOpen}
          >
            ☰
          </button>

          <div className="topbar-title">
            {NAV_GROUPS.find((g) => g.items.some((i) => i.id === active.id)) ? (
              <>
                <span className="topbar-crumb faint">
                  {NAV_GROUPS.find((g) => g.items.some((i) => i.id === active.id))?.label}
                </span>
                <span className="topbar-sep" aria-hidden="true">
                  /
                </span>
              </>
            ) : null}
            <span className="topbar-page">{active.label}</span>
          </div>

          <div className="topbar-right">
            {route !== "signin" && (
              me?.signed_in ? (
                <span className="topbar-who" title={me.subject || ""}>
                  {me.subject}
                </span>
              ) : (
                <button
                  type="button"
                  className="ghost topbar-signin"
                  onClick={() => setRoute("signin")}
                >
                  Sign in
                </button>
              )
            )}
            {route !== "guide" && (
              <button
                type="button"
                className="ghost guide-topbar-btn"
                onClick={() => setRoute("guide")}
                title="Open operator guide (g then j)"
              >
                Guide
              </button>
            )}

            <button
              type="button"
              className="ghost palette-trigger"
              onClick={() => setPaletteOpen(true)}
              aria-label="Open command palette"
            >
              <span className="faint">Search or jump…</span>
              <kbd>⌘K</kbd>
            </button>

            <button
              type="button"
              className={`health-chip tone-${statusTone}`}
              title="Re-check system health"
              onClick={() => loadHealth().catch((e) => toast.error(String(e.message || e || "Health check failed")))}
            >
              <span className="health-dot" aria-hidden="true" />
              <span className="health-text">{statusText}</span>
              {health?.active_pack && (
                <span className="health-pack">{packLabel(health.active_pack)}</span>
              )}
            </button>

            <button
              type="button"
              className="ghost icon-btn"
              onClick={() => setRefreshKey((k) => k + 1)}
              title="Refresh view (r)"
              aria-label="Refresh current view"
            >
              ↻
            </button>

            <button
              type="button"
              className="ghost icon-btn"
              onClick={cycleTheme}
              title={`Theme: ${activeTheme} (t)`}
              aria-label={`Change theme, currently ${activeTheme}`}
            >
              {activeTheme === "light" ? "Dark" : "Light"}
            </button>
          </div>
        </header>

        {mobileNavOpen && (
          <div
            className="mobile-nav-scrim"
            onMouseDown={(e) => {
              if (e.target === e.currentTarget) setMobileNavOpen(false);
            }}
          >
            <nav className="mobile-nav" aria-label="Mobile navigation">
              {navList}
              <div className="nav-group">
                <div className="nav-group-label">More</div>
                <button
                  type="button"
                  className={"nav-item" + (route === "guide" ? " active" : "")}
                  onClick={() => setRoute("guide")}
                >
                  <span className="nav-text">Operator guide</span>
                </button>
                {!me?.signed_in && (
                  <button type="button" className="nav-item" onClick={() => setRoute("signin")}>
                    <span className="nav-text">Sign in</span>
                  </button>
                )}
                <button type="button" className="nav-item" onClick={() => setPaletteOpen(true)}>
                  <span className="nav-text">Search console</span>
                </button>
              </div>
            </nav>
          </div>
        )}

        <main className="main page-enter" id="main" key={active.id} tabIndex={-1}>
          <ErrorBoundary key={liveSessionRoute ? active.id : `${active.id}-${refreshKey}`}>
            <Page refreshKey={refreshKey} health={health} hashQuery={hashQuery} />
          </ErrorBoundary>
        </main>
      </div>

      <CommandPalette
        open={paletteOpen}
        onClose={() => setPaletteOpen(false)}
        commands={commands}
        onOpenShortcuts={() => {
          setPaletteOpen(false);
          setShortcutsOpen(true);
        }}
      />
      <ShortcutSheet open={shortcutsOpen} onClose={() => setShortcutsOpen(false)} />
    </div>
  );
}

export default function App() {
  return (
    <ToastProvider>
      <Shell />
    </ToastProvider>
  );
}
