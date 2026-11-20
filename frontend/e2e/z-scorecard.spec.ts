import { expect, test, type Page } from "@playwright/test";

import { openNav } from "./nav";

async function login(page: Page, email: string) {
  await page.goto("/login");
  await page.getByLabel("Email").fill(email);
  await page.getByLabel("Password").fill(process.env.DEMO_USER_PASSWORD ?? "");
  await page.getByRole("button", { name: "Sign in", exact: true }).click();
  await expect(page.getByRole("heading", { name: "Dashboard", exact: true })).toBeVisible();
}

test("a customer admin produces the monthly scorecard from the customer summary", async ({ page }) => {
  await login(page, "demo.admin.a@demo.invalid");
  await openNav(page, "Customers");
  await page.getByRole("link", { name: /DEMO-A/ }).first().click();
  await expect(page.getByRole("tab", { name: "Summary", exact: true })).toHaveAttribute("aria-selected", "true");
  await page.getByRole("button", { name: "Monthly scorecard (PDF)" }).click();
  // With eager Celery (E2E) the PDF renders inside the request, so allow for a slow answer.
  await expect(page.getByRole("link", { name: "Download PDF" })).toBeVisible({ timeout: 30_000 }); // offered in place
  const recent = page.getByRole("region", { name: "Recent reports" });
  await expect(recent.getByRole("link", { name: /Customer scorecard/ }).first()).toBeVisible({ timeout: 30_000 });
});
