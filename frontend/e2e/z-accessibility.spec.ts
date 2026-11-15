import { createRequire } from "node:module";

import { expect, test, type Page } from "@playwright/test";

// WCAG 2.1 A/AA automated checks (axe-core) on the main pages, at desktop and phone widths. Automated rules find
// only part of the issues (contrast, names, roles, labels); keyboard and screen-reader reviews stay manual.
const AXE = createRequire(import.meta.url).resolve("axe-core/axe.min.js");
const PAGES = ["/", "/compliance", "/assets", "/device-health", "/windows-updates", "/software", "/patch-policies", "/lifecycle",
  "/notifications", "/changes", "/cleanup", "/alerts", "/groups", "/onboarding", "/reports", "/customers", "/admin", "/admin?tab=status"];

async function violations(page: Page): Promise<string[]> {
  await page.addScriptTag({ path: AXE });
  // Runs in the page (string form: the e2e TypeScript config has no DOM types).
  return page.evaluate<string[]>(`(async () => {
    const result = await window.axe.run(document, { runOnly: ["wcag2a", "wcag2aa", "wcag21a", "wcag21aa"] });
    return result.violations.map((v) => v.id + ": " + v.nodes.slice(0, 3).map((n) => n.target.join(" ")).join(" | "));
  })()`);
}

for (const [label, viewport] of [["desktop", { width: 1440, height: 900 }], ["phone", { width: 390, height: 844 }]] as const) {
  test(`main pages have no automated WCAG 2.1 AA violations (${label})`, async ({ page }) => {
    test.setTimeout(120_000);
    await page.setViewportSize(viewport);
    await page.goto("/login");
    expect(await violations(page), "/login").toEqual([]);
    await page.getByLabel("Email").fill("demo.superadmin@demo.invalid");
    await page.getByLabel("Password").fill(process.env.DEMO_USER_PASSWORD ?? "");
    await page.getByRole("button", { name: "Sign in", exact: true }).click();
    await expect(page.getByRole("heading", { name: "Dashboard", exact: true })).toBeVisible();
    const selector = page.locator("#customer-selector");
    await selector.selectOption((await selector.locator("option", { hasText: "DEMO-A" }).first().getAttribute("value")) ?? "");
    for (const path of PAGES) {
      await page.goto(path);
      await page.waitForLoadState("networkidle");
      expect(await violations(page), path).toEqual([]);
    }
  });
}
