import { expect, test, type Page } from "@playwright/test";

import { openNav } from "./nav";

/**
 * VSA4-03 notifications + custom fields on the fixture demo stack (runs after p1.spec.ts synced DEMO-A). Fixture only.
 * Demo notifications carry DEMO\svc-backupN accounts and adminN@demo.invalid addresses that must never be shown.
 */
const PASSWORD = process.env.DEMO_USER_PASSWORD ?? "";

async function login(page: Page, email: string) {
  await page.goto("/login");
  await page.getByLabel("Email").fill(email);
  await page.getByLabel("Password").fill(PASSWORD);
  await page.getByRole("button", { name: "Sign in" }).click();
  await expect(page.getByRole("heading", { name: "Dashboard" })).toBeVisible();
}

test("notifications are redacted and not-collected devices are explicit", async ({ page }) => {
  await login(page, "demo.engineer.a@demo.invalid");
  await openNav(page, "Notifications");
  await expect(page.getByText("Devices not collected", { exact: true })).toBeVisible();
  const table = page.getByRole("table", { name: "Device notifications" });
  await page.getByLabel("Priority").selectOption("critical");
  await expect(table).toContainText("[account]");
  await expect(table).toContainText("[email]");
  await expect(table).not.toContainText("svc-backup");
  await expect(table).not.toContainText("@demo.invalid");
  await table.getByRole("link").first().click();
  await page.getByRole("tab", { name: "Notifications" }).click();
  await expect(page.getByText(/older than 14 days not stored/)).toBeVisible();
  await expect(page.getByText(/Custom fields are read only for names approved/)).toBeVisible();
});

test("customer admin cannot approve a credential-like custom field", async ({ page }) => {
  await login(page, "demo.admin.a@demo.invalid");
  await openNav(page, "Customers");
  await page.getByRole("link", { name: /DEMO-A/ }).first().click();
  await page.getByRole("tab", { name: "Custom fields" }).click();
  await page.getByLabel("Custom field name (exact)").fill("Local Admin Password");
  await page.getByLabel("Reason").fill("convenience (E2E)");
  await page.getByRole("button", { name: "Propose field" }).click();
  await expect(page.getByRole("alert")).toContainText("cannot be approved");
});
