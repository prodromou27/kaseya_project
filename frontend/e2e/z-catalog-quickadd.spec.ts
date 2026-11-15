import { expect, test, type Page } from "@playwright/test";

import { openNav } from "./nav";

async function login(page: Page, email: string) {
  await page.goto("/login");
  await page.getByLabel("Email").fill(email);
  await page.getByLabel("Password").fill(process.env.DEMO_USER_PASSWORD ?? "");
  await page.getByRole("button", { name: "Sign in", exact: true }).click();
  await expect(page.getByRole("heading", { name: "Dashboard", exact: true })).toBeVisible();
}

test("a super admin adds an installed program to the catalog from the software inventory", async ({ page }) => {
  await login(page, "demo.superadmin@demo.invalid");
  const selector = page.locator("#customer-selector");
  await selector.selectOption((await selector.locator("option", { hasText: "DEMO-A" }).first().getAttribute("value")) ?? "");
  await openNav(page, "Software");
  await page.getByRole("tab", { name: "Installed programs", exact: true }).click();
  const table = page.getByRole("table", { name: "Installed programs" });
  await table.getByRole("row", { name: /Microsoft Edge/ }).getByRole("button", { name: "Add to catalog" }).click();
  const form = page.getByRole("form", { name: /Add Microsoft Edge to the catalog/ });
  await expect(form.getByLabel("Vendor")).toHaveValue("Microsoft Corporation");
  await expect(form.getByLabel("Current version")).not.toHaveValue("");
  await form.getByLabel("Evidence link (https)").fill("https://learn.microsoft.com/deployedge/microsoft-edge-relnote-stable-channel");
  await form.getByRole("button", { name: "Add to catalog" }).click();
  // The E2E stack requires a second approver; with self-approval allowed it is added immediately.
  await expect(form.getByRole("status")).toContainText(/Submitted|Added/);
});
