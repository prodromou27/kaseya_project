import { expect, test, type Page } from "@playwright/test";

/**
 * P1 path on the fixture-backed demo stack. Runs after foundation.spec.ts (which approves DEMO-A's mapping).
 * Data is the bundled fictional fixture tenant — NOT a live VSA X instance.
 */
const PASSWORD = process.env.DEMO_USER_PASSWORD ?? "";

async function login(page: Page, email: string) {
  await page.goto("/login");
  await page.getByLabel("Email").fill(email);
  await page.getByLabel("Password").fill(PASSWORD);
  await page.getByRole("button", { name: "Sign in" }).click();
  await expect(page.getByRole("heading", { name: "Dashboard" })).toBeVisible();
}

test("engineer syncs the approved fixture source and browses inventory", async ({ page }) => {
  await login(page, "demo.engineer.a@demo.invalid");
  await page.getByRole("link", { name: "Assets" }).click();
  await page.getByRole("button", { name: "Sync now (read-only)" }).click();
  await expect(page.getByText("as of", { exact: false }).first()).toBeVisible({ timeout: 30_000 });
  await expect(page.getByText(/130 devices/)).toBeVisible({ timeout: 30_000 });
  await expect(page.getByText(/not a live VSA X tenant/)).toBeVisible();
  await page.reload();
  const table = page.getByRole("table", { name: "DEMO-A assets" });
  await expect(table).toBeVisible();
  await expect(page.getByText("130 records · page 1 of 3")).toBeVisible();
  await expect(table.getByRole("link").first()).toHaveText(/^DEMOA-/);

  await page.getByLabel("Search").fill("DEMOA-WS041");
  await expect(page.getByText("1 record · page 1 of 1")).toBeVisible();
  await expect(table.getByText("not collected")).toBeVisible();

  await page.getByLabel("Search").fill("");
  await table.getByRole("link").first().click();
  await expect(page.getByRole("tab", { name: /Installed software/ })).toBeVisible();
  await page.getByRole("tab", { name: /Installed software/ }).click();
  await expect(page.getByRole("table", { name: "Installed software" })).toBeVisible();
});

test("software versions show separate populations and the non-patch disclaimer", async ({ page }) => {
  await login(page, "demo.engineer.a@demo.invalid");
  await page.getByRole("link", { name: "Software versions" }).click();
  await expect(page.getByText(/Not evidence of missing third-party patches/)).toBeVisible();
  await expect(page.getByText("Version compliance")).toBeVisible();
  await expect(page.getByRole("button", { name: /Not catalogued/ })).toBeVisible();
  await expect(page.getByRole("table", { name: "Catalogued products" })).toContainText("DEMO Google Chrome");
  // 7-Zip is architecture-specific in the demo catalog, so it must never be classified as outdated/current.
  await page.getByRole("button", { name: /Unknown/ }).click();
  await expect(page.getByRole("table", { name: "Software installations" })).toContainText("architecture_unverifiable");
});

test("engineer exports a scoped inventory CSV with provenance", async ({ page }) => {
  await login(page, "demo.engineer.a@demo.invalid");
  await page.getByRole("link", { name: "Assets" }).click();
  await page.getByRole("button", { name: "Export inventory CSV" }).click();
  const link = page.getByRole("link", { name: /Download \(130 rows\)/ });
  await expect(link).toBeVisible({ timeout: 15_000 });
  const [download] = await Promise.all([page.waitForEvent("download"), link.click()]);
  const path = await download.path();
  const fs = await import("node:fs");
  const text = fs.readFileSync(path, "utf-8");
  expect(text).toContain("# Customer: Demo Customer A (fixture) (DEMO-A)");
  expect(text).toContain("# Data basis: fixture");
  expect(text).not.toContain("DEMOB-");
  expect(text).not.toContain("UNMAPPED-");
});

test("viewer of DEMO-B cannot reach DEMO-A inventory and cannot sync", async ({ page, browser }) => {
  const admin = await browser.newContext();
  const adminPage = await admin.newPage();
  await login(adminPage, "demo.superadmin@demo.invalid");
  const a = await (await adminPage.request.get("/api/v1/customers/?search=DEMO-A")).json();
  const assets = await (await adminPage.request.get(`/api/v1/customers/${a.results[0].id}/assets/?page_size=1`)).json();
  await admin.close();

  await login(page, "demo.viewer.b@demo.invalid");
  expect((await page.request.get(`/api/v1/customers/${a.results[0].id}/assets/`)).status()).toBe(404);
  expect((await page.request.get(`/api/v1/assets/${assets.results[0].id}/`)).status()).toBe(404);
  await page.getByRole("link", { name: "Assets" }).click();
  await expect(page.getByRole("button", { name: "Sync now (read-only)" })).toHaveCount(0);
});

test("catalog import cannot be approved by its own submitter", async ({ page }) => {
  await login(page, "demo.superadmin@demo.invalid");
  await page.getByRole("link", { name: "Administration" }).click();
  await page.getByRole("tab", { name: "Software catalog" }).click();
  await page.getByRole("button", { name: "Preview (dry run)" }).click();
  await expect(page.getByText(/Row 1:/).first()).toBeVisible();
  await page.getByRole("button", { name: "Submit for review" }).click();
  await expect(page.getByText(/A different administrator must approve it/)).toBeVisible();
  await expect(page.getByText("awaiting another reviewer").first()).toBeVisible();
});
