import { chromium } from "@playwright/test";

const url = process.env.UI_URL || "http://127.0.0.1:8787/ui/#command";
const out = process.env.SHOT || "dashboard.png";
const errors = [];
const browser = await chromium.launch({ headless: true });
const page = await browser.newPage({ viewport: { width: 1440, height: 900 } });
page.on("pageerror", (e) => errors.push(String(e)));
page.on("console", (msg) => {
  if (msg.type() === "error") errors.push(`console:${msg.text()}`);
});
const resp = await page.goto(url, { waitUntil: "networkidle", timeout: 30000 });
await page.waitForSelector(".app", { timeout: 15000 });
await page.waitForTimeout(700);
const box = await page.evaluate(() => {
  const el = document.querySelector(".app") || document.body;
  const r = el.getBoundingClientRect();
  const cs = getComputedStyle(document.body);
  return {
    w: r.width,
    h: r.height,
    area: r.width * r.height,
    bg: cs.backgroundColor,
    greeting: document.querySelector(".cc-greeting")?.textContent || "",
    hasSidebar: !!document.querySelector(".sidebar"),
    hasNavActive: !!document.querySelector(".nav-item.active"),
    title: document.title,
  };
});
await page.screenshot({ path: out, fullPage: false });
await browser.close();
const minArea = 1440 * 900 * 0.55;
const ok =
  Boolean(resp && resp.ok()) &&
  errors.length === 0 &&
  box.area >= minArea &&
  box.hasSidebar &&
  Boolean(box.greeting);
console.log(JSON.stringify({ ok, status: resp && resp.status(), errors, box, out, url }, null, 2));
if (!ok) process.exit(1);
