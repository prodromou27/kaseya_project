import { expect, test, type Page } from "@playwright/test";

import { openNav, showNotes } from "./nav";
import fs from "node:fs";

/** P2 path on the fixture-backed demo stack. Runs after p1.spec.ts (which syncs DEMO-A). Fixture data only. */
const PASSWORD = process.env.DEMO_USER_PASSWORD ?? "";

async function login(page: Page, email: string) {
  await page.goto("/login");
  await page.getByLabel("Email").fill(email);
  await page.getByLabel("Password").fill(PASSWORD);
  await page.getByRole("button", { name: "Sign in" }).click();
  await expect(page.getByRole("heading", { name: "Dashboard" })).toBeVisible();
}

test("windows updates distinguishes reported, not collected and non-Windows devices", async ({ page }) => {
  await login(page, "demo.engineer.a@demo.invalid");
  await openNav(page, "Windows updates");
  await expect(page.getByText("Devices with available updates")).toBeVisible();
  await expect(page.getByText(/never counted as zero/)).toBeVisible();
  await showNotes(page);
  await expect(page.getByText(/does not document a per-device update-scan timestamp/)).toBeVisible();
  await page.getByRole("button", { name: /Not supported \(non-Windows\)/ }).click();
  await expect(page.getByRole("table", { name: /Devices: Not supported/ })).toContainText("mac");
});

for (const [format, magic] of [["xlsx", "PK"], ["pdf", "%PDF"]] as const) {
  test(`exports ${format.toUpperCase()} from the Reports page`, async ({ page }) => {
    await login(page, "demo.engineer.a@demo.invalid");
    await openNav(page, "Reports");
    await page.getByLabel("Report", { exact: true }).selectOption({ label: "Operating system updates (RPT-04)" });
    await page.getByLabel("Format").selectOption(format);
    await page.getByRole("button", { name: "Generate" }).click();
    await page.getByRole("tab", { name: "History" }).click();
    const newest = page.getByRole("table", { name: "DEMO-A reports" }).getByRole("row").nth(1);
    await expect(newest).toContainText(format.toUpperCase());
    const link = newest.getByRole("link", { name: "Download" });
    await expect(link).toBeVisible({ timeout: 20_000 });
    const [download] = await Promise.all([page.waitForEvent("download"), link.click()]);
    expect(download.suggestedFilename()).toMatch(new RegExp(`^DEMO-A_os_updates_.*\\.${format}$`));
    const head = fs.readFileSync(await download.path()).subarray(0, 4).toString("latin1");
    expect(head.startsWith(magic)).toBe(true);
  });
}

test("a report can be regenerated from its pinned snapshot", async ({ page }) => {
  await login(page, "demo.engineer.a@demo.invalid");
  await openNav(page, "Reports");
  await page.getByRole("tab", { name: "History" }).click();
  await page.getByRole("button", { name: "Regenerate" }).first().click();
  await expect(page.getByText("regenerated").first()).toBeVisible({ timeout: 20_000 });
});

test("definition + schedule with an unauthorised recipient is rejected, authorised accepted", async ({ page }) => {
  await login(page, "demo.engineer.a@demo.invalid");
  await openNav(page, "Reports");
  page.once("dialog", (d) => void d.accept("Weekly inventory"));
  await page.getByRole("button", { name: "Save as definition" }).click();
  await expect(page.getByText("Definition saved.")).toBeVisible();
  await page.getByRole("tab", { name: "Definitions & schedules" }).click();
  const form = page.getByRole("form", { name: /Schedule Weekly inventory/ });
  await form.getByLabel("Timezone (IANA)").fill("Asia/Nicosia");
  await form.getByLabel("Recipients (emails, in-portal)").fill("demo.viewer.b@demo.invalid");
  await form.getByRole("button", { name: "Add schedule" }).click();
  await expect(form.getByRole("alert")).toContainText("cannot receive");
  await form.getByLabel("Recipients (emails, in-portal)").fill("demo.admin.a@demo.invalid");
  await form.getByRole("button", { name: "Add schedule" }).click();
  await expect(page.getByText(/weekly at 07:00 Asia\/Nicosia/)).toBeVisible();
});

test("dashboard shows history with a table view", async ({ page }) => {
  await login(page, "demo.engineer.a@demo.invalid");
  await expect(page.getByText("Devices over time")).toBeVisible();
  await page.getByRole("button", { name: "Show table" }).click();
  await expect(page.getByRole("table", { name: "Devices over time" })).toBeVisible();
});
