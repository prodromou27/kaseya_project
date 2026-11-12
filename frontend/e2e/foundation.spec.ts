import { expect, test, type Page } from "@playwright/test";

const PASSWORD = process.env.DEMO_USER_PASSWORD ?? "";

async function login(page: Page, email: string) {
  await page.goto("/login");
  await page.getByLabel("Email").fill(email);
  await page.getByLabel("Password").fill(PASSWORD);
  await page.getByRole("button", { name: "Sign in" }).click();
  await expect(page.getByRole("heading", { name: "Dashboard" })).toBeVisible();
}

test.beforeAll(() => {
  if (PASSWORD.length < 14) throw new Error("Set DEMO_USER_PASSWORD to the value used for `manage.py seed_demo`.");
});

test("anonymous user is sent to login", async ({ page }) => {
  await page.goto("/customers");
  await expect(page.getByRole("form", { name: "Local sign-in" })).toBeVisible();
  const resp = await page.request.get("/api/v1/customers/");
  expect(resp.status()).toBe(401);
});

test("engineer sees only their customer and cannot reach another by URL or API", async ({ page }) => {
  await login(page, "demo.engineer.a@demo.invalid");
  const selector = page.getByLabel("Customer");
  await expect(selector.locator("option")).toHaveText(["Select a customer…", "DEMO-A — Demo Customer A (fixture)"]);
  const list = await page.request.get("/api/v1/customers/?page_size=200");
  const codes = (await list.json()).results.map((c: { code: string }) => c.code);
  expect(codes).toEqual(["DEMO-A"]);

  const search = await page.request.get("/api/v1/customers/?search=DEMO-B");
  expect((await search.json()).count).toBe(0);
  const foreign = await page.request.get("/api/v1/customers/00000000-0000-4000-8000-000000000000/");
  expect(foreign.status()).toBe(404);
  await expect(page.getByRole("link", { name: "Administration" })).toHaveCount(0);
});

test("engineer cannot open Customer B using its real ID (IDOR)", async ({ browser }) => {
  const adminCtx = await browser.newContext();
  const adminPage = await adminCtx.newPage();
  await login(adminPage, "demo.superadmin@demo.invalid");
  const all = await (await adminPage.request.get("/api/v1/customers/?search=DEMO-B")).json();
  const customerB = all.results[0].id as string;
  await adminCtx.close();

  const engCtx = await browser.newContext();
  const page = await engCtx.newPage();
  await login(page, "demo.engineer.a@demo.invalid");
  for (const path of ["", "memberships/", "mappings/", "audit-events/", "reports/"]) {
    const resp = await page.request.get(`/api/v1/customers/${customerB}/${path}`);
    expect(resp.status(), path).toBe(404);
    expect(await resp.text()).not.toContain("Demo Customer B");
  }
  await page.goto(`/customers/${customerB}`);
  await expect(page.getByRole("alert")).toContainText("Not found.");
  await engCtx.close();
});

test("super admin approves the demo source mapping and the audit trail records it", async ({ page }) => {
  await login(page, "demo.superadmin@demo.invalid");
  await page.getByRole("link", { name: "Administration" }).click();
  await expect(page.getByRole("tab", { name: "Mapping review" })).toHaveAttribute("aria-selected", "true");
  const row = page.getByRole("row", { name: /demo-org-1001/ });
  page.once("dialog", (d) => void d.accept());
  await row.getByRole("button", { name: "Approve" }).click();
  await expect(page.getByRole("row", { name: /demo-org-1001/ })).toHaveCount(0);
  await page.getByLabel("Status").selectOption("approved");
  await expect(page.getByRole("row", { name: /demo-org-1001/ })).toContainText("approved");
  await page.getByRole("tab", { name: "Audit log" }).click();
  await expect(page.getByRole("table", { name: "System audit events" })).toContainText("mapping.approved");
});

test("customer admin generates and downloads a scoped audit report", async ({ page }) => {
  await login(page, "demo.admin.a@demo.invalid");
  await page.getByRole("link", { name: "Reports" }).click();
  await page.getByRole("button", { name: "Generate audit log CSV" }).click();
  const link = page.getByRole("link", { name: "Download CSV" }).first();
  await expect(link).toBeVisible({ timeout: 15_000 });
  const [download] = await Promise.all([page.waitForEvent("download"), link.click()]);
  expect(download.suggestedFilename()).toMatch(/^DEMO-A_customer_audit_log_.*\.csv$/);
});
