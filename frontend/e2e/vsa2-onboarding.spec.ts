import { expect, test, type Page } from "@playwright/test";

import { openNav, showNotes } from "./nav";

/**
 * VSA2 onboarding reconciliation on the fixture demo stack (runs after p1.spec.ts synced DEMO-A). Fixture only.
 * Demo naming: DEMOA-WS001 (HQ/Workstations), DEMOA-WS002 (HQ/Workstations), DEMOA-WS003 (Branch/Workstations).
 */
const PASSWORD = process.env.DEMO_USER_PASSWORD ?? "";

async function login(page: Page, email: string) {
  await page.goto("/login");
  await page.getByLabel("Email").fill(email);
  await page.getByLabel("Password").fill(PASSWORD);
  await page.getByRole("button", { name: "Sign in" }).click();
  await expect(page.getByRole("heading", { name: "Dashboard" })).toBeVisible();
}

const CSV = [
  "Computer Name,Expected Site,Expected Group,Notes",
  "DEMOA-WS001,HQ,Workstations,ok",
  "DEMOA-WS002,HQ,Servers,should be a server",
  "DEMOA-WS003,HQ,Workstations,",
  "GHOST-999,HQ,Workstations,never deployed?",
  "demoa-ws001,hq,Workstations,repeated line",
  ",HQ,Workstations,no identifier",
  "DEMOA-WS004,HQ,Workstations,=HYPERLINK(\"http://example.invalid\")",
].join("\n");

test("engineer reconciles an expected device list and downloads the workbook", async ({ page }) => {
  await login(page, "demo.engineer.a@demo.invalid");
  await openNav(page, "Onboarding check");
  await expect(page.getByText(/Compared against VSA snapshot/)).toBeVisible();
  await page.getByLabel("Expected inventory file").setInputFiles({ name: "expected.csv", mimeType: "text/csv", buffer: Buffer.from(CSV) });
  const preview = page.getByRole("table", { name: "Preview of mapped rows" });
  await expect(preview).toBeVisible();
  await expect(page.getByLabel("Hostname (identifier)")).toHaveValue("0");
  await page.getByRole("button", { name: "Start comparison" }).click();

  await expect(page.getByRole("heading", { name: "Onboarding check — expected.csv" })).toBeVisible();
  const tile = (label: string) => page.locator("div.rounded", { has: page.getByText(label, { exact: true }) }).first();
  await expect(tile("Expected rows")).toContainText("7");
  await expect(tile("Matched correct")).toContainText("2");
  await expect(tile("Wrong group")).toContainText("1");
  await expect(tile("Wrong site / org")).toContainText("1");
  await expect(tile("Not found")).toContainText("1");
  await expect(tile("Duplicate / invalid")).toContainText("2");
  await showNotes(page);
  await expect(page.getByText(/is not proof that an agent is not installed/)).toBeVisible();

  await page.getByRole("button", { name: "Wrong group" }).click();
  await expect(page.getByRole("table", { name: "Expected rows" })).toContainText("DEMOA-WS002");
  await page.getByRole("button", { name: "Unexpected in VSA" }).click();
  await expect(page.getByRole("table", { name: "Unexpected VSA devices" })).toBeVisible();

  const download = page.waitForEvent("download");
  await page.getByRole("link", { name: "Download workbook (XLSX)" }).click();
  expect((await download).suggestedFilename()).toMatch(/^DEMO-A_onboarding_\d{8}T\d{6}Z\.xlsx$/);
});

test("macro-enabled workbook is refused before anything is stored", async ({ page }) => {
  await login(page, "demo.engineer.a@demo.invalid");
  await openNav(page, "Onboarding check");
  await page.getByLabel("Expected inventory file").setInputFiles({ name: "evil.xlsm", mimeType: "application/vnd.ms-excel.sheet.macroEnabled.12", buffer: Buffer.from("PK\u0003\u0004") });
  await expect(page.getByRole("alert")).toContainText("Only .xlsx and .csv files are accepted");
});

test("customer B cannot see customer A comparisons", async ({ page }) => {
  await login(page, "demo.engineer.a@demo.invalid");
  const customers = await (await page.request.get("/api/v1/customers/")).json();
  const a = customers.results.find((c: { code: string }) => c.code === "DEMO-A");
  const runs = await (await page.request.get(`/api/v1/customers/${a.id}/onboarding/runs/`)).json();
  expect(runs.count).toBeGreaterThan(0);
  await page.getByRole("button", { name: /sign out/i }).click();
  await login(page, "demo.viewer.b@demo.invalid");
  expect((await page.request.get(`/api/v1/customers/${a.id}/onboarding/runs/`)).status()).toBe(404);
  expect((await page.request.get(`/api/v1/customers/${a.id}/onboarding/runs/${runs.results[0].id}/export/?output=xlsx`)).status()).toBe(404);
});
