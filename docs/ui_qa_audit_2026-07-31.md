# Skew AI ops console — full UI QA audit

**Date:** 2026-07-31  
**App under test:** `http://127.0.0.1:8000/ui/` (uvicorn + `dashboard/dist`)  
**Themes checked:** `data-theme="light"` and `data-theme="dark"` (Playwright + source)  
**Scope:** All 11 primary nav routes + shell chrome (sidebar, topbar, palette, theme, shortcuts)  
**Out of scope:** Backend correctness, live Twilio/PSTN, full WCAG suite, implementing fixes  

**Method:** Playwright crawl of every `#route` in light and dark (screenshots under implementer scratch), source review of `dashboard/routes/*` + shell CSS/JS, and visual inspection of captured PNGs.

**Assumptions**
- Empty data states are acceptable for a pilot DB with no open cases; defects below are about presentation, brand, or control design — not “no cases yet.”
- API paths `/api/frontline/*` and env names `FRONTLINE_*` stay for compatibility; user-visible product brand should still read **Skew AI**.

---

## Severity summary

| Severity | Count |
|----------|------:|
| Blocker  | 0 |
| Major    | 7 |
| Minor    | 12 |
| **Total open defects** | **19** |

---

## Shell chrome

| Area | Result |
|------|--------|
| Brand lockup | **Clean** — “Skew AI” / `skewai · live VOC ops` |
| Sidebar nav groups | **Clean** — active state works light+dark |
| Topbar crumb / page title | **Clean** |
| Health chip | **Clean** — pack id + ok |
| Command palette (⌘K) | **Clean** — opens, focusable |
| Theme toggle | **Clean** — dark ↔ light only (wallboard removed); no theme toast |
| Refresh | **Clean** |
| Capability-pack ribbon | **Clean** — removed (not present) |
| Checkbox global CSS | **Clean** — 16px checkboxes (connector Enabled fixed) |

### Shell defects

| ID | Severity | Location | What is wrong | Fix recommendation |
|----|----------|----------|---------------|--------------------|
| S1 | **Minor** | Command palette action label (`App.jsx` ~`act-simulate-15`) | Label still says **“Simulate 15 contacts (fill wallboard)”** — “wallboard” is retired theme language | Rename to “Simulate 15 contacts (fill Command center)” or “seed live ops” |
| S2 | **Minor** | Palette action “Re-check system health” | Fires a toast **“Health re-checked”** with no extra info — same class of noise as the removed theme toast | Drop toast, or only toast on failure |
| S3 | **Minor** | Type stack (`index.html`, `styles.css`) | Loads **Sora + IBM Plex Mono** from Google Fonts (known “AI SaaS default” pairing per design law) | Self-host a deliberate pair if brand polish is a priority; not a functional bug |

---

## Route-by-route

### 1. Command center (`#command`)

**Overall:** Solid flagship. Light + dark tokens apply; jump tiles and stats read cleanly. Empty floor view is intentional.

| ID | Severity | Location | What is wrong | Fix recommendation |
|----|----------|----------|---------------|--------------------|
| C1 | **Minor** | Error banner copy (`CommandCenter.jsx`) | On load failure: **“Could not load wallboard”** | Say “Could not load command center” / “ops snapshot” |
| — | — | Rest of surface | — | **Clean** for layout, contrast, empty states, CTAs |

---

### 2. Voice agent (`#call`)

**Overall:** Ready-to-start empty state is clear; capabilities panel is useful. Light theme works.

| ID | Severity | Location | What is wrong | Fix recommendation |
|----|----------|----------|---------------|--------------------|
| V1 | **Major** | Header CTA **Start voice call** (light theme screenshot) | Primary control in the page header reads **washed / low contrast** vs the solid primary on Live console (“Start voice contact”) — easy to miss as the main action | Ensure header CTA uses full solid primary fill + dark label; avoid muted/icon-btn wash; match Live console weight |
| V2 | **Minor** | Capabilities panel keys (`stt`, `barge_in`, `text path`) | Snake_case / eng jargon in a customer-facing ops UI | Human labels: “Speech to text”, “Barge-in”, “Text while in call” |
| — | — | Greeting / barge-in path | Source shows greeting phase protection shipped | No UI defect observed in idle state |

---

### 3. Live console (`#console`)

**Overall:** **Clean.** Empty “No live contacts” with clear CTAs; light/dark OK; no raw JSON.

| ID | Severity | Location | What is wrong | Fix recommendation |
|----|----------|----------|---------------|--------------------|
| — | — | Full surface | — | **No issue found** |

---

### 4. Case queue (`#cases`)

**Overall:** Good structure and empty state. Filters and table headers expose raw backend enums.

| ID | Severity | Location | What is wrong | Fix recommendation |
|----|----------|----------|---------------|--------------------|
| Q1 | **Major** | Status filter chips (`CaseQueue.jsx` `STATUS`) | Chip labels are raw enums: **`open`**, **`pending_followup`**, **`closed`** (snake_case) | Display labels: “Open”, “Pending follow-up”, “Closed”; keep enum values only as data |
| Q2 | **Minor** | Table headers | ALL_CAPS snake style: `CASE_ID`, `SAFETY FLAGS`, `PEAK FR.` | Title case human headers: “Case ID”, “Safety flags”, “Peak frustration” |
| Q3 | **Minor** | Case drawer status actions (same file) | Same raw `pending_followup` strings on buttons | Same humanize map as Q1 |

---

### 5. Insights (`#insights`)

**Overall:** **Clean** boards with empty states; no raw JSON dumps observed. Window control works.

| ID | Severity | Location | What is wrong | Fix recommendation |
|----|----------|----------|---------------|--------------------|
| — | — | Full surface | — | **No issue found** (empty data is expected with sparse pilot traffic) |

---

### 6. Early warning (`#warning`)

**Overall:** **Clean** for empty pilot; simulate path present. Light/dark OK.

| ID | Severity | Location | What is wrong | Fix recommendation |
|----|----------|----------|---------------|--------------------|
| — | — | Full surface | — | **No issue found** |

---

### 7. Feature studio (`#studio`)

**Overall:** Analytics and sibling tabs use tables/cards (not raw JSON). Good vs earlier JSON-dump era.

| ID | Severity | Location | What is wrong | Fix recommendation |
|----|----------|----------|---------------|--------------------|
| F1 | **Minor** | Tab strip + many primary actions across Booking/Jobs/etc. | Dense multi-tab surface; several actions still use terse lowercase labels in places | Standardize Title Case on primary buttons across tabs |
| F2 | **Minor** | Empty analytics cards | Honest empty copy — good; some panels still feel sparse | Optional: one shared empty illustration or single “Run simulate to populate” CTA at top of Analytics |
| — | — | Raw JSON boards | Not present on Analytics (tables used) | **Clean** for the original JSON-dump complaint |

---

### 8. Enterprise ops (`#enterprise`)

**Overall:** Tabbed explorer works; default Timeline empty state is clear but operator-heavy.

| ID | Severity | Location | What is wrong | Fix recommendation |
|----|----------|----------|---------------|--------------------|
| E1 | **Major** | Primary CTA **load timeline** (and siblings “lookup”, etc.) | Lowercase sentence CTAs mixed with Title Case elsewhere | “Load timeline”, “Lookup memory”, “Run scenario” — consistent Title Case |
| E2 | **Major** | Timeline step selection style (`EnterpriseOps.jsx` inline) | Selected step background: `var(--panel-2, #1a1f2e)` — **undefined token** + **dark-only fallback** breaks light-theme selection (dark smear on light page when a step is selected) | Use `var(--bg-hover)` / `var(--accent-muted)`; never hard-code `#1a1f2e` |
| E3 | **Minor** | Detail values | Nested objects fall back to `JSON.stringify(v).slice(0, 120)` in the timeline detail pane | Prefer summary/text fields only; if dump needed, put behind “Raw” disclosure |
| E4 | **Minor** | Empty default | Requires knowing `interaction_id` shape | Prefill dropdown from recent interactions (already partially there) + helper: “Pick a recent contact or simulate first” |

---

### 9. Audit reports (`#audits`)

**Overall:** Split list + detail with markdown renderer (tables, headings). Mismatch checkbox uses `check-row`.

| ID | Severity | Location | What is wrong | Fix recommendation |
|----|----------|----------|---------------|--------------------|
| A1 | **Minor** | Empty selection state | “Select a report from the left” is fine | Auto-select first report when list loads |
| A2 | **Minor** | Export filenames historically `frontline-*` | Source uses `skewai-audit-export-*` (fixed earlier) | Confirm on next export; **OK in source** |

---

### 10. Platform OS (`#platform`)

**Overall:** Functional governance UI, but presentation is engineer-console, not ops-console.

| ID | Severity | Location | What is wrong | Fix recommendation |
|----|----------|----------|---------------|--------------------|
| P1 | **Major** | Proposal **titles** | Shown as `abandoned_or_incomplete on int_…` (raw weakness class + id) | Human title: “Abandoned contact — incomplete intake” + mono id secondary |
| P2 | **Major** | Proposal **detail** line | Raw dump: `blame=intake; confidence=0.54; why=status=abandoned…` | Structured chips: Blame · Confidence · Why (plain English) |
| P3 | **Major** | Trend chips | `abandoned_or_incomplete: 7` snake_case keys as chip text | Humanize weakness/status keys for display |
| P4 | **Minor** | Buttons | Lowercase **scan failures**, **approve**, **reject** | Title Case: “Scan failures”, “Approve”, “Reject” |
| P5 | **Minor** | Experiments / Governance tabs | Artifact & deployment lists are mono one-liners (`kind/name@version · id`) | Compact table: Kind · Name · Version · Status |

---

### 11. Settings (`#settings`)

**Overall:** Layout OK after checkbox fix; brand and env jargon still leak into the UI.

| ID | Severity | Location | What is wrong | Fix recommendation |
|----|----------|----------|---------------|--------------------|
| T1 | **Major** | Pilot API key field | Placeholder **`FRONTLINE_API_KEY`** and body copy cites `FRONTLINE_API_KEY` / `X-API-Key` env machine names as the product face | Placeholder: “Paste pilot API key”; helper can mention env once in muted mono |
| T2 | **Minor** | Dead-letter help | Visible path `POST /api/frontline/alerts/dead-letter/…/replay` (Playwright counted “frontline” ×2) | “Replay resends the failed webhook” without full path; keep path in docs |
| T3 | **Minor** | Connector URL placeholder | `https://hooks.example.com/frontline` | `https://hooks.example.com/skewai` or generic `/hooks` |
| T4 | **Minor** | Buttons | Lowercase **save**, **activate**, **save connector** | “Save”, “Activate”, “Save connector” |
| T5 | **Minor** | Alerts field | Placeholder `(read from ALERT_WEBHOOK_URL env…)` | “Configured on server” + optional reveal of redacted URL |

---

## Cross-cutting themes

| Theme | Status |
|-------|--------|
| Light theme shell (sidebar/main/cards) | **Fixed / clean** — tokens + overrides; crawl confirmed light `--bg #e9eef5`, dark `--bg #090b10` |
| Dark theme regression | **Clean** in crawl |
| Wallboard theme | **Removed** from toggle |
| Theme change toast | **Removed** |
| Connector Enabled checkbox layout | **Fixed** |
| Raw JSON feature boards | **Clean** on Feature studio Analytics; residual JSON only as fallback snippets (E3) |
| User-facing “Frontline” product name | **Mostly clean**; residual env/API strings in Settings (T1–T3) |
| Toast noise | Theme toast gone; health re-check toast remains (S2) |

---

## Priority fix order (recommended)

1. **P1–P3** — Platform OS proposal presentation (highest “not ops-ready” feel)  
2. **Q1** — Case queue status human labels  
3. **E2** — Enterprise timeline light-theme selection color  
4. **V1** — Voice agent primary CTA contrast weight  
5. **E1 + P4 + T4** — Global Title Case on primary buttons  
6. **T1–T3** — Settings brand/env copy  
7. **S1, C1** — Retire “wallboard” wording  
8. Minors (table headers, mono lists, toast)

---

## Coverage checklist

| Nav id | Light | Dark | Defects or clean |
|--------|:-----:|:----:|------------------|
| command | ✓ | ✓ | C1 minor |
| call | ✓ | ✓ | V1 major, V2 minor |
| console | ✓ | ✓ | **Clean** |
| cases | ✓ | ✓ | Q1 major, Q2–Q3 minor |
| insights | ✓ | ✓ | **Clean** |
| warning | ✓ | ✓ | **Clean** |
| studio | ✓ | ✓ | F1–F2 minor |
| enterprise | ✓ | ✓ | E1–E2 major, E3–E4 minor |
| audits | ✓ | ✓ | A1–A2 minor |
| platform | ✓ | ✓ | P1–P3 major, P4–P5 minor |
| settings | ✓ | ✓ | T1 major, T2–T5 minor |
| shell | ✓ | ✓ | S1–S3 minor |

---

## Evidence

- Playwright crawl log + JSON: implementer scratch `qa-crawl.log`, `qa-crawl-results.json`, `qa-deep.json`  
- Screenshots: `qa-light-*.png`, `qa-dark-*.png`, `qa-deep-*.png`  
- Spot-check notes: `qa-spotcheck.txt`, summary: `qa-summary.txt`  

This report is the deliverable for the QA goal; fixes are intentionally **not** implemented here.

---

## Fixed (2026-07-31 implementer pass)

Closed by code changes (label maps + surgical copy/CSS). Non-goal left open: **S3** (Sora/IBM Plex font stack).

| ID | Status |
|----|--------|
| P1–P4, P5 | Fixed — Platform OS human titles/chips/tables + Title Case |
| Q1–Q3 | Fixed — statusLabel map + title-case headers |
| E1–E4 | Fixed — Title Case CTAs, theme token selection, formatDetailValue, helper empty copy |
| V1–V2 | Fixed — `voice-cta` solid primary + capabilityLabel |
| T1–T5 | Fixed — Settings brand/env copy + Title Case |
| S1–S2, C1 | Fixed — wallboard wording + health toast noise |
| A1 | Fixed — auto-select first audit |
| A2 | Already OK in source |
| F1–F2, S3 | Partial / non-goal (F1 Title Case on named surfaces only; S3 fonts deferred) |
