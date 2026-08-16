#!/usr/bin/env node
/**
 * Structural gate for Skew AI light theme.
 * Reads shipped CSS sources + production dist CSS (after `npm run build`).
 * Fails if shell/cards still hard-code dark-only fills without light overrides.
 */
import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const root = path.resolve(__dirname, "..");
const srcDir = path.join(root, "src");
const distDir = path.join(root, "dist");

const BAD_HEX = [
  "#10151e",
  "#0a0d14",
  "#121824",
  "#111722",
  "#151b27",
  "#222a3c",
  "#0b0e14",
];

function read(p) {
  return fs.readFileSync(p, "utf8");
}

function fail(msg) {
  console.error("FAIL:", msg);
  process.exitCode = 1;
}

function ok(msg) {
  console.log("OK:", msg);
}

// ── Source files ──────────────────────────────────────────────────────────
const styles = read(path.join(srcDir, "styles.css"));
const consoleCss = read(path.join(srcDir, "console.css"));
const ux = read(path.join(srcDir, "ux-v21.css"));
const allSrc = styles + "\n" + consoleCss + "\n" + ux;

// Dark default tokens must remain dark
const darkBg = styles.match(/:root\s*\{[^}]*--bg:\s*([^;]+);/s);
if (!darkBg || !/#0[0-9a-f]{5}/i.test(darkBg[1].trim())) {
  fail(`default :root --bg must stay dark, got: ${darkBg && darkBg[1]}`);
} else {
  ok(`dark :root --bg = ${darkBg[1].trim()}`);
}

// Light token block must define light bg + dark ink
const lightBlock = consoleCss.match(
  /:root\[data-theme="light"\]\s*\{([^}]+)\}/s
);
if (!lightBlock) {
  fail('missing :root[data-theme="light"] token block in console.css');
} else {
  const block = lightBlock[1];
  const bg = (block.match(/--bg:\s*([^;]+);/) || [])[1];
  const ink = (block.match(/--ink:\s*([^;]+);/) || [])[1];
  if (!bg || !/^#([e-fE-F]|[a-dA-D][8-9a-fA-F])/.test(bg.trim())) {
    // light bg should be high luminance (rough: starts with e/f or mid-high)
    if (!bg || !/^#[a-fA-F0-9]{6}/.test(bg.trim())) {
      fail(`light --bg missing or invalid: ${bg}`);
    } else {
      // numeric luminance check
      const hex = bg.trim().slice(1);
      const r = parseInt(hex.slice(0, 2), 16);
      const g = parseInt(hex.slice(2, 4), 16);
      const b = parseInt(hex.slice(4, 6), 16);
      const lum = (0.2126 * r + 0.7152 * g + 0.0722 * b) / 255;
      if (lum < 0.72) fail(`light --bg too dark (lum=${lum.toFixed(3)}): ${bg}`);
      else ok(`light --bg = ${bg.trim()} lum=${lum.toFixed(3)}`);
    }
  } else {
    ok(`light --bg = ${bg.trim()}`);
  }
  if (!ink) fail("light --ink missing");
  else {
    const hex = ink.trim().slice(1);
    const r = parseInt(hex.slice(0, 2), 16);
    const g = parseInt(hex.slice(2, 4), 16);
    const b = parseInt(hex.slice(4, 6), 16);
    const lum = (0.2126 * r + 0.7152 * g + 0.0722 * b) / 255;
    if (lum > 0.35) fail(`light --ink too light (lum=${lum.toFixed(3)}): ${ink}`);
    else ok(`light --ink = ${ink.trim()} lum=${lum.toFixed(3)}`);
  }
}

// Shell rules must not hard-code problem hexes
for (const hex of BAD_HEX) {
  if (allSrc.toLowerCase().includes(hex.toLowerCase())) {
    fail(`hard-coded dark fill still present: ${hex}`);
  }
}
ok("no problem dark hex fills in source CSS");

// Required light overrides (specificity safety net)
const requiredLight = [
  ':root[data-theme="light"] .sidebar',
  ':root[data-theme="light"] .main',
  ':root[data-theme="light"] .jump-tile',
  ':root[data-theme="light"] .stat-card',
];
for (const sel of requiredLight) {
  if (!allSrc.includes(sel)) fail(`missing light override: ${sel}`);
}
ok("required light shell/card overrides present");

// Tokenized shell backgrounds
if (!/\.sidebar\s*\{[^}]*var\(--bg-(panel|raised)\)/s.test(ux + styles)) {
  fail(".sidebar must use theme tokens for background");
}
if (!/\.main\s*\{[^}]*var\(--bg/s.test(ux + styles)) {
  fail(".main must use theme tokens for background");
}
ok("shell backgrounds are token-based");

// Button hover must not hard-code #222a3c
if (/button:hover[^{]*\{[^}]*#222a3c/s.test(styles)) {
  fail("button:hover still hard-codes #222a3c");
}
ok("button hover uses theme-aware color");

// ── Dist (built) ──────────────────────────────────────────────────────────
const distCssFiles = fs.existsSync(distDir)
  ? fs.readdirSync(path.join(distDir, "assets")).filter((f) => f.endsWith(".css"))
  : [];
if (!distCssFiles.length) {
  fail("no dist CSS — run npm run build first");
} else {
  const distCss = distCssFiles
    .map((f) => read(path.join(distDir, "assets", f)))
    .join("\n");
  for (const hex of BAD_HEX) {
    if (distCss.toLowerCase().includes(hex.toLowerCase())) {
      fail(`dist CSS still contains hard-coded dark fill: ${hex}`);
    }
  }
  if (!distCss.includes('data-theme="light"') && !distCss.includes("data-theme=light")) {
    // vite may keep quotes
    if (!/data-theme.{0,3}light/.test(distCss)) {
      fail("dist CSS missing light theme rules");
    }
  }
  if (!/--bg:\s*#090b10/.test(distCss) && !/--bg:#090b10/.test(distCss)) {
    // minifier may drop spaces
    if (!/--bg:\s*#090b10/i.test(distCss) && !distCss.includes("#090b10")) {
      fail("dist CSS lost dark default --bg");
    } else {
      ok("dist retains dark default --bg");
    }
  } else {
    ok("dist retains dark default --bg");
  }
  // light bg present
  if (!/#e9eef5|#f3f5f9|#eef2f7|#e4ebf3/i.test(distCss)) {
    fail("dist CSS missing expected light surface hexes");
  } else {
    ok("dist CSS includes light surface colors");
  }
  ok(`dist CSS checked: ${distCssFiles.join(", ")}`);
}

if (process.exitCode) {
  console.error("\nassert-light-theme: FAILED");
  process.exit(1);
}
console.log("\nassert-light-theme: PASSED");
