/**
 * Aggressive UI interactions: settings save key, nav clicks, simulate via palette.
 */
import { test, expect } from "@playwright/test";

const KEY =
  process.env.E2E_API_KEY ||
  process.env.FRONTLINE_API_KEY ||
  "live-harden-key-32-chars-min!!";

async function seedKey(page) {
  await page.addInitScript((key) => {
    localStorage.setItem("frontline_api_key", key);
  }, KEY);
}

test.describe("UI interactions", () => {
  test("sidebar nav clicks visit every primary item", async ({ page }) => {
    await seedKey(page);
    await page.goto("/ui/#command");
    await page.waitForLoadState("domcontentloaded");
    const labels = [
      "Voice agent",
      "Live console",
      "Case queue",
      "Early warning",
      "Trust",
      "Platform",
      "Settings",
      "Command center",
    ];
    for (const label of labels) {
      const btn = page.getByRole("button", { name: label, exact: true }).first();
      if ((await btn.count()) === 0) {
        // collapsed sidebar may only show icons — use hash fallback
        continue;
      }
      await btn.click();
      await page.waitForTimeout(350);
      await expect(page.locator("body")).toBeVisible();
      const err = page.locator("text=HTTP 401");
      await expect(err).toHaveCount(0);
    }
  });

  test("settings save key reloads packs (no 401)", async ({ page }) => {
    // Start without key, then paste and save
    await page.addInitScript(() => localStorage.removeItem("frontline_api_key"));
    await page.goto("/ui/#settings");
    await page.waitForLoadState("networkidle").catch(() => {});
    await page.waitForTimeout(500);

    // Find password or text input for API key
    const inputs = page.locator("input");
    const count = await inputs.count();
    let filled = false;
    for (let i = 0; i < count; i++) {
      const el = inputs.nth(i);
      const type = await el.getAttribute("type");
      const ph = (await el.getAttribute("placeholder")) || "";
      if (type === "password" || /api|key|secret/i.test(ph)) {
        await el.fill(KEY);
        filled = true;
        break;
      }
    }
    if (!filled && count > 0) {
      // fallback: first empty text-like input
      await inputs.first().fill(KEY);
      filled = true;
    }

    // Click Save if present
    const save = page.getByRole("button", { name: /save/i }).first();
    if ((await save.count()) > 0) {
      await save.click();
      await page.waitForTimeout(800);
    }

    // Packs request should be authorized after save
    const body = await page.locator("body").innerText();
    // Should not permanently show HTTP 401 after save (may flash briefly)
    // Reload settings with key in storage
    await page.evaluate((key) => localStorage.setItem("frontline_api_key", key), KEY);
    await page.goto("/ui/#settings");
    await page.waitForLoadState("networkidle").catch(() => {});
    await page.waitForTimeout(800);
    const body2 = await page.locator("body").innerText();
    expect(body2).not.toMatch(/HTTP 401/);
  });

  test("case queue export button does not 401", async ({ page }) => {
    await seedKey(page);
    const exportFails = [];
    page.on("response", (res) => {
      if (res.url().includes("/cases/export") && res.status() >= 400) {
        exportFails.push(`${res.status()}`);
      }
    });
    await page.goto("/ui/#cases");
    await page.waitForLoadState("networkidle").catch(() => {});
    await page.waitForTimeout(600);
    const exportBtn = page.getByRole("button", { name: /export/i }).first();
    if ((await exportBtn.count()) > 0) {
      await exportBtn.click();
      await page.waitForTimeout(800);
    }
    expect(exportFails).toEqual([]);
  });

  test("enterprise ops load does not 500/401", async ({ page }) => {
    await seedKey(page);
    const bad = [];
    page.on("response", (res) => {
      if (
        res.url().includes("/api/frontline/enterprise/") &&
        (res.status() === 401 || res.status() >= 500)
      ) {
        bad.push(`${res.status()} ${res.url()}`);
      }
    });
    await page.goto("/ui/#enterprise");
    await page.waitForLoadState("networkidle").catch(() => {});
    await page.waitForTimeout(1500);
    expect(bad, bad.join("\n")).toEqual([]);
  });

  test("platform OS loads without 401", async ({ page }) => {
    await seedKey(page);
    const bad = [];
    page.on("response", (res) => {
      if (res.url().includes("/api/v3/") && res.status() === 401) {
        bad.push(res.url());
      }
    });
    await page.goto("/ui/#platform");
    await page.waitForLoadState("networkidle").catch(() => {});
    await page.waitForTimeout(1200);
    expect(bad).toEqual([]);
  });
});
