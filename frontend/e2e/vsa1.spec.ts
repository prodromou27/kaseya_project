import { expect, test, type Page } from "@playwright/test";

/** VSA1 hierarchy + group network on the fixture demo stack (runs after p1.spec.ts synced DEMO-A). Fixture only. */
const PASSWORD = process.env.DEMO_USER_PASSWORD ?? "";

async function login(page: Page, email: string) {
  await page.goto("/login");
  await page.getByLabel("Email").fill(email);
  await page.getByLabel("Password").fill(PASSWORD);
  await page.getByRole("button", { name: "Sign in" }).click();
  await expect(page.getByRole("heading", { name: "Dashboard" })).toBeVisible();
}

test("engineer browses org > site > group and the group's reported network", async ({ page }) => {
  await login(page, "demo.engineer.a@demo.invalid");
  await page.getByRole("link", { name: "Groups & network" }).click();
  const orgs = page.getByRole("list", { name: "Organisations" });
  await expect(orgs).toBeVisible();
  await expect(orgs.getByText("130 devices").first()).toBeVisible();
  // Demo data places a deliberate duplicate IP on a device in the HQ site's Servers group.
  await orgs.getByRole("list", { name: "Groups of HQ" }).first().getByRole("link", { name: "Servers" }).click();
  await expect(page.getByRole("table", { name: "Derived subnets" })).toBeVisible();
  await expect(page.getByText(/not discovered topology/)).toBeVisible();
  await expect(page.getByText("duplicate IP").first()).toBeVisible();
  await page.getByRole("link", { name: "Open in Assets" }).click();
  await expect(page.getByText(/VSA group \d+/)).toBeVisible();
});

test("device page shows network, hardware and security tabs and the third-party status notice", async ({ page }) => {
  await login(page, "demo.engineer.a@demo.invalid");
  await page.getByRole("link", { name: "Assets" }).click();
  await page.getByLabel("Search").fill("10.1.10.86");
  await expect(page.getByText("2 records · page 1 of 1")).toBeVisible();
  await page.getByRole("table", { name: "DEMO-A assets" }).getByRole("link").first().click();
  await page.getByRole("tab", { name: "Network" }).click();
  await expect(page.getByText("10.1.10.86").first()).toBeVisible();
  await page.getByRole("tab", { name: "Hardware & security" }).click();
  await expect(page.getByRole("table", { name: "Disks" })).toBeVisible();
  await expect(page.getByText(/units are not documented/)).toBeVisible();
  await page.getByRole("tab", { name: /Installed software/ }).click();
  await expect(page.getByText(/Third-party patch deployment status: unavailable/)).toBeVisible();
});

test("customer B viewer cannot reach customer A group network", async ({ page }) => {
  await login(page, "demo.viewer.b@demo.invalid");
  const customers = await (await page.request.get("/api/v1/customers/")).json();
  expect(customers.results.map((c: { code: string }) => c.code)).toEqual(["DEMO-B"]);
  const resp = await page.request.get("/api/v1/customers/00000000-0000-4000-8000-000000000000/groups/20012/network/");
  expect(resp.status()).toBe(404);
});
