import { expect, test, type Page } from "@playwright/test";

/**
 * VSA4-01/02 device health on the fixture demo stack (runs after p1.spec.ts synced DEMO-A). Fixture only.
 * Deterministic demo agent versions: every 9th device 5.0.7 (14), index 50 "dev-build", the rest 5.1.2.
 */
const PASSWORD = process.env.DEMO_USER_PASSWORD ?? "";

async function login(page: Page, email: string) {
  await page.goto("/login");
  await page.getByLabel("Email").fill(email);
  await page.getByLabel("Password").fill(PASSWORD);
  await page.getByRole("button", { name: "Sign in" }).click();
  await expect(page.getByRole("heading", { name: "Dashboard" })).toBeVisible();
}

test("every health dimension partitions the whole population", async ({ page }) => {
  await login(page, "demo.engineer.a@demo.invalid");
  await page.getByRole("link", { name: "Device health" }).click();
  await expect(page.getByRole("region", { name: "System disk free space" })).toBeVisible();
  await expect(page.getByText(/not live monitoring telemetry/)).toBeVisible();
  const customers = await (await page.request.get("/api/v1/customers/")).json();
  const a = customers.results.find((c: { code: string }) => c.code === "DEMO-A");
  const s = await (await page.request.get(`/api/v1/customers/${a.id}/device-health/summary/`)).json();
  expect(s.devices).toBe(130);
  for (const [dim, counts] of Object.entries(s.dimensions as Record<string, Record<string, number>>)) {
    expect(Object.values(counts).reduce((x, y) => x + y, 0), dim).toBe(130);
  }
  // Agent age is evaluated only once a minimum version is approved (a rerun may already have one).
  expect(s.dimensions.agent_version.not_evaluated).toBe(s.thresholds.minimum_agent_version ? 0 : 130);
  await page.getByRole("region", { name: "Antivirus" }).getByRole("button", { name: "Disabled" }).click();
  await expect(page.getByText(/Filtered by/)).toBeVisible();
});

test("minimum agent version takes effect only after a second administrator approves", async ({ page }) => {
  await login(page, "demo.admin.a@demo.invalid");
  await page.getByRole("link", { name: "Device health" }).click();
  await page.getByLabel("Minimum agent version").fill("5.1");
  await page.getByLabel("Reason").fill("Agent baseline (E2E)");
  await page.getByRole("button", { name: "Propose thresholds" }).click();
  const history = page.getByRole("table", { name: "Threshold history" });
  await expect(history).toContainText("proposed");
  await history.getByRole("button", { name: "Approve" }).click();
  await expect(page.getByRole("alert")).toContainText("A different administrator must approve");
  await page.getByRole("button", { name: "Sign out" }).click();

  await login(page, "demo.superadmin@demo.invalid");
  const value = await page.locator("#customer-selector option", { hasText: "DEMO-A" }).getAttribute("value");
  await page.locator("#customer-selector").selectOption(value ?? "");
  await page.getByRole("link", { name: "Device health" }).click();
  await page.getByRole("table", { name: "Threshold history" }).getByRole("button", { name: "Approve" }).click();
  await expect(page.getByText("approved", { exact: true }).first()).toBeVisible();
  const versions = page.getByRole("region", { name: "Agent version" });
  await expect(versions.getByRole("row", { name: /Below approved minimum/ })).toContainText("14");
  await expect(versions.getByRole("row", { name: /Version not comparable/ })).toContainText("1");
  await expect(versions.getByRole("row", { name: /At or above approved minimum/ })).toContainText("115");
});
