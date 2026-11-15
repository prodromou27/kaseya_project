import { expect, test, type Page } from "@playwright/test";

import { openNav } from "./nav";

async function login(page: Page, email: string) {
  await page.goto("/login");
  await page.getByLabel("Email").fill(email);
  await page.getByLabel("Password").fill(process.env.DEMO_USER_PASSWORD ?? "");
  await page.getByRole("button", { name: "Sign in", exact: true }).click();
  await expect(page.getByRole("heading", { name: "Dashboard", exact: true })).toBeVisible();
}

test("observed subnets list group spread and an admin proposes the dominant group as the approved subnet", async ({ page }) => {
  await login(page, "demo.admin.a@demo.invalid");
  await openNav(page, "Groups & network");
  await page.getByRole("tab", { name: "Subnets", exact: true }).click();
  const table = page.getByRole("table", { name: "Observed subnets" });
  await expect(table).toContainText("Spans 2 groups");
  const candidate = table.getByRole("row").filter({ has: page.getByRole("button", { name: /^Propose for / }) }).first();
  await expect(candidate).toBeVisible();
  // Pin the row by its subnet: the Propose button disappears once the proposal exists.
  const cidr = ((await candidate.locator("td").first().locator("span.font-mono").textContent()) ?? "").trim();
  const row = table.getByRole("row").filter({ hasText: cidr });
  await row.getByRole("button", { name: /^Propose for / }).click();
  await expect(row).toContainText("awaiting approval");
  await row.getByRole("button", { name: "Devices", exact: true }).click();
  await expect(page.getByRole("table", { name: /^Devices in subnet / })).toBeVisible();
});
