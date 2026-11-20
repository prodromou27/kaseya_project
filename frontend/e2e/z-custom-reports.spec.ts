import { expect, test, type Page } from "@playwright/test";

import { openNav } from "./nav";

async function login(page: Page, email: string) {
  await page.goto("/login");
  await page.getByLabel("Email").fill(email);
  await page.getByLabel("Password").fill(process.env.DEMO_USER_PASSWORD ?? "");
  await page.getByRole("button", { name: "Sign in", exact: true }).click();
  await expect(page.getByRole("heading", { name: "Dashboard", exact: true })).toBeVisible();
}

test("an engineer builds a filtered custom report, previews it and generates an Excel file", async ({ page }) => {
  await login(page, "demo.engineer.a@demo.invalid");
  await openNav(page, "Reports");
  await page.getByRole("tab", { name: "Custom report", exact: true }).click();
  await page.getByRole("radio", { name: /Device health/ }).click();
  await page.getByRole("button", { name: "Add filter" }).click();
  await page.getByLabel("Field", { exact: true }).selectOption("disk");
  await page.getByRole("checkbox", { name: "Critical", exact: true }).check();
  await page.getByRole("button", { name: "Preview" }).click();
  const preview = page.getByRole("table", { name: "Custom report preview" });
  await expect(preview).toBeVisible();
  await expect(preview.locator("tbody tr").first()).toContainText("critical");
  await expect(preview.locator("tbody")).not.toContainText(/\bok\b/);

  await page.getByLabel("Report title (optional)").fill("Critical disks");
  await page.getByRole("button", { name: "Generate report" }).click();
  await expect(page.getByRole("link", { name: "Download XLSX" })).toBeVisible({ timeout: 20_000 });
  await page.getByRole("tab", { name: "History", exact: true }).click();
  await expect(page.getByRole("table").first()).toContainText("Critical disks");
});
