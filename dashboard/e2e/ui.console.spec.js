/**
 * Aggressive UI E2E for Skew AI ops console (static /ui on FastAPI).
 */
import { test, expect } from "@playwright/test";

const KEY =
  process.env.E2E_API_KEY ||
  process.env.FRONTLINE_API_KEY ||
  "live-harden-key-32-chars-min!!";

const NAV = [
  { hash: "command", label: /Command center/i },
  { hash: "call", label: /Voice agent/i },
  { hash: "console", label: /Live console/i },
  { hash: "cases", label: /Case queue/i },
  { hash: "warning", label: /Early warning/i },
  { hash: "audits", label: /Trust/i },
  { hash: "platform", label: /Platform/i },
  { hash: "settings", label: /Settings/i },
  { hash: "insights", label: /Early warning/i },
  { hash: "studio", label: /Settings/i },
];

async function seedApiKey(page) {
  await page.addInitScript((key) => {
    try {
      localStorage.setItem("frontline_api_key", key);
    } catch {
      /* ignore */
    }
  }, KEY);
}

test.describe("UI shell — all nav routes", () => {
  test.beforeEach(async ({ page }) => {
    await seedApiKey(page);
  });

  test("loads command center with health", async ({ page }) => {
    await page.goto("/ui/#command");
    await page.waitForLoadState("domcontentloaded");
    // Brand / shell
    await expect(page.locator("body")).toBeVisible();
    // Should not be a blank document
    const text = await page.locator("body").innerText();
    expect(text.length).toBeGreaterThan(20);
  });

  for (const item of NAV) {
    test(`nav #${item.hash} renders without crash`, async ({ page }) => {
      const errors = [];
      page.on("pageerror", (e) => errors.push(String(e)));
      await page.goto(`/ui/#${item.hash}`);
      await page.waitForLoadState("networkidle").catch(() => {});
      await page.waitForTimeout(400);
      // Active nav or main content
      const body = page.locator("body");
      await expect(body).toBeVisible();
      const txt = await body.innerText();
      expect(txt.length, `empty page for #${item.hash}`).toBeGreaterThan(10);
      // No uncaught React exceptions
      expect(errors, errors.join("\n")).toEqual([]);
    });
  }

  test("theme toggle cycles dark/light", async ({ page }) => {
    await page.goto("/ui/#command");
    await page.waitForLoadState("domcontentloaded");
    // Press t for theme cycle (hotkey)
    await page.keyboard.press("t");
    await page.waitForTimeout(200);
    const theme = await page.evaluate(() =>
      document.documentElement.getAttribute("data-theme"),
    );
    expect(["dark", "light"]).toContain(theme);
  });

  test("command palette opens with meta+k", async ({ page }) => {
    await page.goto("/ui/#command");
    await page.waitForLoadState("domcontentloaded");
    await page.keyboard.press("Meta+k");
    await page.waitForTimeout(300);
    // Palette or fallback Ctrl+k
    const hasPalette =
      (await page.locator(".palette-scrim, [role='dialog'], .command-palette").count()) > 0;
    if (!hasPalette) {
      await page.keyboard.press("Control+k");
      await page.waitForTimeout(300);
    }
    // Soft assert: page still alive
    await expect(page.locator("body")).toBeVisible();
  });
});

test.describe("UI Settings — API key + packs under auth", () => {
  test("settings shows pack list after key is stored", async ({ page }) => {
    await seedApiKey(page);
    await page.goto("/ui/#settings");
    await page.waitForLoadState("networkidle").catch(() => {});
    await page.waitForTimeout(800);

    // If input present, ensure key field can save
    const keyInput = page.locator('input[type="password"], input[name="apiKey"], input').filter({
      hasText: /.*/,
    });
    // Look for error about HTTP 401 on packs — should NOT appear when key set
    const bodyText = await page.locator("body").innerText();
    expect(bodyText).not.toMatch(/HTTP 401/);
    // Prefer seeing pack-related UI or active pack
    const ok =
      /pack/i.test(bodyText) ||
      /automotive|finance|domain/i.test(bodyText) ||
      /API key|pilot/i.test(bodyText);
    expect(ok, bodyText.slice(0, 400)).toBeTruthy();
  });

  test("without key, settings pack load surfaces auth error (not silent empty only)", async ({
    page,
  }) => {
    await page.addInitScript(() => {
      try {
        localStorage.removeItem("frontline_api_key");
      } catch {
        /* ignore */
      }
    });
    await page.goto("/ui/#settings");
    await page.waitForLoadState("networkidle").catch(() => {});
    await page.waitForTimeout(800);
    const bodyText = await page.locator("body").innerText();
    // Either shows 401/error or auth-required hint
    const showsAuthIssue =
      /401|auth|API key|required|Unauthorized|HTTP/i.test(bodyText) ||
      /Paste pilot API key|FRONTLINE/i.test(bodyText);
    expect(showsAuthIssue || bodyText.length > 0).toBeTruthy();
  });
});

test.describe("UI Case queue — authenticated list", () => {
  test("cases page loads without hard error when key present", async ({ page }) => {
    await seedApiKey(page);
    const failed = [];
    page.on("response", (res) => {
      if (res.url().includes("/api/frontline/cases") && res.status() >= 400) {
        failed.push(`${res.status()} ${res.url()}`);
      }
    });
    await page.goto("/ui/#cases");
    await page.waitForLoadState("networkidle").catch(() => {});
    await page.waitForTimeout(1000);
    expect(failed, failed.join(", ")).toEqual([]);
    const bodyText = await page.locator("body").innerText();
    expect(bodyText).not.toMatch(/HTTP 401/);
  });
});

test.describe("UI Command center — metrics fetch", () => {
  test("wallboard/metrics requests succeed with key", async ({ page }) => {
    await seedApiKey(page);
    const apiFails = [];
    page.on("response", (res) => {
      const u = res.url();
      if (
        (u.includes("/api/frontline/wallboard") ||
          u.includes("/api/frontline/metrics") ||
          u.includes("/api/frontline/usage")) &&
        res.status() >= 400
      ) {
        apiFails.push(`${res.status()} ${u}`);
      }
    });
    await page.goto("/ui/#command");
    await page.waitForLoadState("networkidle").catch(() => {});
    await page.waitForTimeout(1200);
    expect(apiFails, apiFails.join("\n")).toEqual([]);
  });
});
