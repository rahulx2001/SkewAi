import { defineConfig, devices } from "@playwright/test";

/**
 * Skew AI ops console E2E.
 * Serves production /ui from FastAPI on :8000 (reuseExistingServer).
 * Auth: set E2E_API_KEY (defaults to live-harden key used in pilot).
 */
const BASE = process.env.BASE_URL || "http://127.0.0.1:8000";
const API_KEY =
  process.env.E2E_API_KEY ||
  process.env.FRONTLINE_API_KEY ||
  "live-harden-key-32-chars-min!!";

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
  // Prefer already-running hardened API; do not spawn open-mode server by accident.
  webServer: {
    command: "echo 'reuse existing server on BASE_URL'",
    url: `${BASE}/health`,
    reuseExistingServer: true,
    timeout: 5_000,
  },
});

export { API_KEY, BASE };
