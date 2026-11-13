import { expect, test, type Page } from "@playwright/test";

/**
 * VSA4-04 inventory changes on the fixture demo stack. A second sync of the unchanged demo data must report zero
 * differences (nothing fabricated) and list the devices whose sections could not be compared. Fixture only.
 */
const PASSWORD = process.env.DEMO_USER_PASSWORD ?? "";

async function login(page: Page, email: string) {
  await page.goto("/login");
  await page.getByLabel("Email").fill(email);
  await page.getByLabel("Password").fill(PASSWORD);
  await page.getByRole("button", { name: "Sign in" }).click();
  await expect(page.getByRole("heading", { name: "Dashboard" })).toBeVisible();
}

test("a resync of unchanged data shows no fabricated changes", async ({ page }) => {
  await login(page, "demo.engineer.a@demo.invalid");
  await page.getByRole("link", { name: "Assets" }).click();
  await page.getByRole("button", { name: "Sync now (read-only)" }).click();
  // The "130 devices" status is already visible from the first sync, so wait for the new snapshot explicitly.
  const customers = await (await page.request.get("/api/v1/customers/")).json();
  const a = customers.results.find((c: { code: string }) => c.code === "DEMO-A");
  await expect
    .poll(async () => (await (await page.request.get(`/api/v1/customers/${a.id}/changes/snapshots/`)).json()).length, {
      timeout: 60_000,
    })
    .toBeGreaterThanOrEqual(2);
  await page.getByRole("link", { name: "Inventory changes" }).click();
  await expect(page.getByText(/No person is attributed|no person is attributed/)).toBeVisible({ timeout: 30_000 });
  await expect(page.getByText(/130 devices in both/)).toBeVisible();
  await expect(page.getByText("No differences between these snapshots.")).toBeVisible();
  // Every 23rd demo device has no network section in either snapshot: 5 devices cannot be compared.
  await expect(page.getByText(/IP addresses 5 device\(s\)/)).toBeVisible();
  const kinds = page.getByRole("group", { name: "Change kinds" });
  await expect(kinds.getByRole("button", { name: /Newly observed devices/ })).toBeDisabled();
});

test("customer B viewer cannot read customer A changes", async ({ page }) => {
  await login(page, "demo.engineer.a@demo.invalid");
  const customers = await (await page.request.get("/api/v1/customers/")).json();
  const a = customers.results.find((c: { code: string }) => c.code === "DEMO-A");
  await page.getByRole("button", { name: "Sign out" }).click();
  await login(page, "demo.viewer.b@demo.invalid");
  expect((await page.request.get(`/api/v1/customers/${a.id}/changes/`)).status()).toBe(404);
});
