import { expect, test, type Page } from "@playwright/test";

import { openNav } from "./nav";

/**
 * VSA3-04 patch policies on the fixture demo stack (runs after p1.spec.ts synced DEMO-A). Fixture only.
 * Demo (index-based): 130 devices; every 17th has no Patch Management entry (7), every 11th explicit No Policy (11).
 */
const PASSWORD = process.env.DEMO_USER_PASSWORD ?? "";

async function login(page: Page, email: string) {
  await page.goto("/login");
  await page.getByLabel("Email").fill(email);
  await page.getByLabel("Password").fill(PASSWORD);
  await page.getByRole("button", { name: "Sign in" }).click();
  await expect(page.getByRole("heading", { name: "Dashboard" })).toBeVisible();
}

async function selectDemoA(page: Page) {
  const value = await page.locator("#customer-selector option", { hasText: "DEMO-A" }).getAttribute("value");
  await page.locator("#customer-selector").selectOption(value ?? "");
}

const tile = (page: Page, label: string) => page.locator("div.rounded", { has: page.getByText(label, { exact: true }) }).first();

test("engineer sees assignment states kept apart and policy configuration labelled", async ({ page }) => {
  await login(page, "demo.engineer.a@demo.invalid");
  await openNav(page, "Patch policies");
  await expect(tile(page, "Policy assigned")).toContainText("112");
  await expect(tile(page, "No Policy (explicit)")).toContainText("11");
  await expect(tile(page, "No Patch Management entry")).toContainText("7");
  await expect(tile(page, "Coverage")).toContainText("112 of 123 verified; 7 excluded");
  await expect(page.getByText("configuration, not deployment status").first()).toBeVisible();
  await expect(page.getByRole("button", { name: "Propose expectation" })).toHaveCount(0);
  await openNav(page, "Devices");
  await page.getByRole("searchbox", { name: "Search", exact: true }).fill("DEMOA-WS011");
  await page.getByRole("table", { name: "DEMO-A assets" }).getByRole("link").first().click();
  await page.getByRole("tab", { name: "Policies" }).click();
  await expect(page.getByText("No Policy (explicitly configured)").first()).toBeVisible();
});

test("expectation needs a second administrator, then drives drift", async ({ page }) => {
  await login(page, "demo.admin.a@demo.invalid");
  await openNav(page, "Patch policies");
  await page.getByLabel("Scope type").selectOption("group");
  await page.getByLabel("Scope", { exact: true }).selectOption("20011"); // HQ / Workstations
  await page.getByLabel("Expected policy").selectOption("301");
  await page.getByLabel("Reason").fill("Workstation standard (E2E)");
  await page.getByRole("button", { name: "Propose expectation" }).click();
  const table = page.getByRole("table", { name: "Expected policies" });
  await expect(table).toContainText("proposed");
  await table.getByRole("button", { name: "Approve" }).click();
  await expect(page.getByRole("alert")).toContainText("A different administrator must approve");
  await page.getByRole("button", { name: "Sign out" }).click();

  await login(page, "demo.superadmin@demo.invalid");
  await selectDemoA(page);
  await openNav(page, "Patch policies");
  await page.getByRole("table", { name: "Expected policies" }).getByRole("button", { name: "Approve" }).click();
  await expect(page.getByRole("table", { name: "Expected policies" })).toContainText("approved");
  // Group 20011 (HQ/Workstations, 75 devices): 58 on 301, 7 explicit No Policy, 6 drifted to 302, 4 not reported.
  // Tile text is "<label><value>", so anchor the value at the end.
  await expect(tile(page, "Matches the approved expectation")).toHaveText(/\D58$/);
  await expect(tile(page, "Expected a policy; No Policy is explicitly configured")).toHaveText(/\D7$/);
  await expect(tile(page, "A different policy is assigned")).toHaveText(/\D6$/);
  await expect(tile(page, "No approved expectation covers this device")).toHaveText(/\D55$/);
  await page.getByLabel("Drift").selectOption("missing_policy");
  await expect(page.getByRole("table", { name: "Patch policy by device" })).toContainText("No Policy (explicitly configured)");
});
