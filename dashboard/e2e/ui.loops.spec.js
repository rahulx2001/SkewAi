import { test, expect } from "@playwright/test";

test.describe("Operator loops", () => {
  test("command critical card opens filtered case queue", async ({ page }) => {
    const errors = [];
    page.on("pageerror", (e) => errors.push(String(e)));
    await page.goto("/ui/#command");
    await page.waitForLoadState("domcontentloaded");
    await page.waitForTimeout(800);
    const btn = page.locator("button.stat-card-btn", { hasText: "Critical open" });
    await expect(btn).toBeVisible();
    await btn.click();
    await page.waitForTimeout(500);
    expect(page.url()).toMatch(/#cases/);
    expect(page.url()).toMatch(/severity=Critical/);
    expect(errors).toEqual([]);
    await expect(page.locator("text=This view hit an error")).toHaveCount(0);
  });

  test("case row opens drawer", async ({ page }) => {
    await page.goto("/ui/#cases");
    await page.waitForTimeout(800);
    const row = page.locator("table tbody tr").first();
    if ((await row.count()) === 0) test.skip();
    await row.click();
    await expect(page.locator('[role="dialog"][aria-label="Case detail"]')).toBeVisible();
  });

  test("early warning simulate modal closes on Escape", async ({ page }) => {
    await page.goto("/ui/#warning");
    await page.waitForTimeout(600);
    await page.getByRole("button", { name: /Simulate traffic/i }).first().click();
    await expect(page.locator(".modal-backdrop")).toBeVisible();
    await page.keyboard.press("Escape");
    await page.waitForTimeout(200);
    await expect(page.locator(".modal-backdrop")).toHaveCount(0);
  });

  test("g then a opens trust", async ({ page }) => {
    await page.goto("/ui/#command");
    await page.waitForTimeout(400);
    await page.keyboard.press("g");
    await page.waitForTimeout(80);
    await page.keyboard.press("a");
    await page.waitForTimeout(300);
    expect(page.url()).toMatch(/#audits/);
  });

  test("retired hashes alias into the cut nav", async ({ page }) => {
    await page.goto("/ui/#studio");
    await page.waitForTimeout(400);
    expect(page.url()).toMatch(/#settings/);
    await page.goto("/ui/#insights");
    await page.waitForTimeout(400);
    expect(page.url()).toMatch(/#warning/);
    await page.goto("/ui/#trust");
    await page.waitForTimeout(400);
    expect(page.url()).toMatch(/#audits/);
    expect(page.url()).toMatch(/tab=reports/);
  });

  test("command open-cases card jumps to queue", async ({ page }) => {
    await page.goto("/ui/#command");
    await page.waitForTimeout(800);
    const cards = page.locator("button.stat-card-btn");
    await expect(cards).toHaveCount(4);
    await page.locator("button.stat-card-btn", { hasText: "Open cases" }).click();
    await page.waitForTimeout(400);
    expect(page.url()).toMatch(/#cases/);
  });

  test("settings remember-key defaults off", async ({ page }) => {
    await page.goto("/ui/#settings");
    await page.waitForTimeout(500);
    const box = page.getByLabel(/Remember API key on this device/i);
    await expect(box).toHaveCount(1);
    await expect(box).not.toBeChecked();
  });
});
