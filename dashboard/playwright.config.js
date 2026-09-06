import { defineConfig, devices } from "@playwright/test";

/**
 * Skew AI ops console E2E.
 * Serves production /ui from FastAPI on :8000 (reuseExistingServer).
 * Auth: set E2E_API_KEY or FRONTLINE_API_KEY. No hardcoded fallback.
 * Browsers: npx playwright install chromium
 * Requires an already-running API on BASE_URL (fails if /health is down).
 */
const BASE = process.env.BASE_URL || "http://127.0.0.1:8000";
const API_KEY = process.env.E2E_API_KEY || process.env.FRONTLINE_API_KEY || "";

export default defineConfig({
  testDir: "./e2e",
  fullyParallel: false,
  forbidOnly: !!process.env.CI,
  retries: process.env.CI ? 1 : 0,
  workers: 1,
  timeout: 60_000,
  expect: { timeout: 12_000 },
  reporter: [
    ["list"],
    ["html", { open: "never", outputFolder: "playwright-report" }],
    ["json", { outputFile: "playwright-results.json" }],
  ],
  use: {
    baseURL: BASE,
    trace: "on-first-retry",
    screenshot: "only-on-failure",
    video: "retain-on-failure",
    actionTimeout: 12_000,
    navigationTimeout: 30_000,
  },
  projects: [{ name: "chromium", use: { ...devices["Desktop Chrome"] } }],
  // Require an already-running API. Fail loudly if /health is unreachable.
  webServer: {
    command: `python3 -c "import urllib.request,sys; urllib.request.urlopen('${BASE}/health', timeout=3); print('health ok')" && sleep 3600`,
    url: `${BASE}/health`,
    reuseExistingServer: true,
    timeout: 8_000,
  },
});

export { API_KEY, BASE };
