import { expect, test, type Page } from "@playwright/test";

import { openNav } from "./nav";

// Needs the E2E backend started with VSA_CUSTOM_FIELD_WRITES_ENABLED=true (fixture integration: writes go to an
// in-process fake, never to a VSA X server). Runs after p1.spec.ts, which syncs the DEMO-A inventory.

async function login(page: Page, email: string) {
  await page.goto("/login");
  await page.getByLabel("Email").fill(email);
  await page.getByLabel("Password").fill(process.env.DEMO_USER_PASSWORD ?? "");
  await page.getByRole("button", { name: "Sign in", exact: true }).click();
  await expect(page.getByRole("heading", { name: "Dashboard", exact: true })).toBeVisible();
}

async function selectDemoA(page: Page) {
  const selector = page.locator("#customer-selector");
  const value = await selector.locator("option", { hasText: "DEMO-A" }).first().getAttribute("value");
  await selector.selectOption(value ?? "");
}

test("a super admin enables PatchRing, an engineer prepares a pasted list and an admin applies it with verified results", async ({ page }) => {
  test.setTimeout(120_000);
  await login(page, "demo.superadmin@demo.invalid");
  await selectDemoA(page);
  await openNav(page, "Settings");
  await page.getByRole("tab", { name: "Integrations" }).click();
  await page.getByRole("row", { name: /fixture/i }).getByRole("button", { name: "Edit" }).first().click();
  await page.getByLabel("Allow confirmed custom field assignments for this integration").check();
  await page.getByRole("button", { name: "Save" }).click();
  await openNav(page, "Custom fields");
  await page.getByRole("tab", { name: "Field overview" }).click();
  await page.getByRole("button", { name: "Read fields from VSA X" }).click();
  const fields = page.getByRole("table", { name: "Custom fields in VSA X" });
  await expect(fields.getByText("Read-only in VSA X")).toBeVisible({ timeout: 30_000 });
  const ring = fields.getByRole("row", { name: /PatchRing/ });
  const editable = ring.getByLabel("Editable in the portal");
  if (!(await editable.isChecked())) await editable.click(); // saved first, then shown as checked
  await expect(ring.getByText("Editable", { exact: true })).toBeVisible();
  await expect(ring.getByLabel("Editable in the portal")).toBeChecked();
  await page.getByRole("button", { name: "Sign out" }).click();

  await login(page, "demo.engineer.a@demo.invalid");
  await selectDemoA(page);
  await openNav(page, "Custom fields");
  await page.getByRole("tab", { name: "Import list" }).click();
  await page.getByLabel(/Workstations \(one per line/).fill("DEMOA-WS001\nDEMOA-WS005\nDEMOA-SRV007\nNO-SUCH-PC");
  await page.getByRole("combobox", { name: "Custom field", exact: true }).selectOption({ label: "PatchRing (Text)" });
  const value = `Ring ${Date.now() % 100000}`; // a new value each run: the fixture VSA keeps earlier writes in memory
  await page.getByLabel("Value", { exact: true }).fill(value);
  await page.getByRole("button", { name: "Find devices" }).click();

  const job = page.getByRole("region", { name: "Custom field job" });
  // No line needs a device choice, so the preview starts without another click; unmatched lines stay listed.
  const preview = job.getByRole("table", { name: "Preview of changes" });
  await expect(preview.getByRole("row", { name: /DEMOA-WS005/ })).toContainText("Update", { timeout: 30_000 });
  await expect(preview.getByRole("row", { name: /DEMOA-SRV007/ })).toContainText("Unsupported");
  await expect(preview.getByRole("row", { name: /NO-SUCH-PC/ })).toContainText("Not found");
  await expect(preview.getByRole("row", { name: /DEMOA-WS001/ })).toContainText(/Assign|Update/);
  // Engineers prepare and preview; only an administrator applies.
  await expect(job.getByText("Ready for an administrator")).toBeVisible();
  await expect(job.getByRole("button", { name: "Apply changes" })).toHaveCount(0);
  await page.getByRole("button", { name: "Sign out" }).click();

  await login(page, "demo.admin.a@demo.invalid");
  await selectDemoA(page);
  await openNav(page, "Custom fields");
  // The prepared job is waiting at the top of the page: one click to open, one confirmation to apply.
  const waiting = page.getByRole("region", { name: "Waiting for you to apply" });
  await waiting.getByRole("listitem").filter({ hasText: value }).getByRole("button", { name: "Review and apply" }).click();
  await expect(job.getByRole("table", { name: "Preview of changes" }).getByRole("row", { name: /DEMOA-WS005/ })).toContainText("Update");
  await job.getByLabel(/I confirm setting PatchRing on \d+ workstations? in VSA X, overwriting/).check();
  await job.getByRole("button", { name: "Apply changes" }).click();
  const results = job.getByRole("table", { name: "Results" });
  await expect(results.getByText("Verified success")).toHaveCount(2, { timeout: 60_000 });
  await expect(job.getByRole("link", { name: "Download results (Excel)" })).toBeVisible();
  await page.getByRole("tab", { name: "Assignment history" }).click();
  await expect(page.getByRole("table", { name: "Assignment history" })).toContainText(`PatchRing = ${value}`);
});
