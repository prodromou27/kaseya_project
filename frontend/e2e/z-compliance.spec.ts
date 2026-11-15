import { expect, test, type Page } from "@playwright/test";

import { openNav } from "./nav";

async function login(page: Page, email: string) {
  await page.goto("/login");
  await page.getByLabel("Email").fill(email);
  await page.getByLabel("Password").fill(process.env.DEMO_USER_PASSWORD ?? "");
  await page.getByRole("button", { name: "Sign in", exact: true }).click();
  await expect(page.getByRole("heading", { name: "Dashboard", exact: true })).toBeVisible();
}

test("a customer admin defines a baseline and sees per-device findings; an engineer cannot edit", async ({ page }) => {
  await login(page, "demo.admin.a@demo.invalid");
  await openNav(page, "Compliance");
  await page.getByRole("button", { name: "New baseline" }).click();
  const form = page.getByRole("form", { name: "New baseline" });
  const name = `E2E baseline ${Date.now()}`;
  await form.getByLabel("Name", { exact: true }).fill(name);
  await form.getByLabel("Rule", { exact: true }).first().selectOption("disk_free_min");
  await form.getByLabel("Minimum free %").fill("15");
  await form.getByRole("button", { name: "Add rule" }).click();
  await form.getByLabel("Rule", { exact: true }).nth(1).selectOption("forbidden_software");
  await form.getByLabel("Program name contains").fill("Beta");
  await form.getByRole("button", { name: "Create baseline" }).click();

  await expect(page.getByRole("heading", { name })).toBeVisible();
  await expect(page.getByRole("button", { name: /System disk at least 15% free/ })).toContainText("failing");
  const table = page.getByRole("table", { name: "Compliance by device" });
  await expect(table).toContainText("Not compliant");
  await page.getByRole("button", { name: /“Beta” is not installed/ }).click();
  await expect(table).toContainText("Installed: Google Chrome Beta");
  await page.getByRole("button", { name: "Sign out" }).click();

  await login(page, "demo.engineer.a@demo.invalid");
  await openNav(page, "Compliance");
  await expect(page.getByRole("link", { name: new RegExp(name) })).toBeVisible();
  await expect(page.getByRole("button", { name: "New baseline" })).toHaveCount(0);
});
