import { expect, test, type Page } from "@playwright/test";
import { readFile } from "node:fs/promises";

async function login(page: Page, email = "demo.engineer.a@demo.invalid") {
  await page.goto("/login");
  await page.getByLabel("Email").fill(email);
  await page.getByLabel("Password").fill(process.env.DEMO_USER_PASSWORD ?? "");
  await page.getByRole("button", { name: "Sign in", exact: true }).click();
  await expect(page.getByRole("heading", { name: "Dashboard", exact: true })).toBeVisible();
}

test("dashboard attention metrics open the exact filtered investigation", async ({ page }) => {
  await login(page);
  const tile = page.getByRole("region", { name: "Summary" }).getByRole("link", { name: /Offline \/ stale/ });
  await tile.click();
  await expect(page).toHaveURL(/connectivity=offline,stale,never_seen/);
  const table = page.getByRole("table", { name: "Device health", exact: true });
  await expect(table).toBeVisible();
  await expect(page.getByText(/Filtered by/)).toContainText("or");
  await page.goto("/");
  await page.getByRole("region", { name: "Summary" }).getByRole("link", { name: /Missing critical updates/ }).click();
  await expect(page.getByLabel("Severity", { exact: true })).toHaveValue("Critical");
  await expect(page.getByRole("table", { name: "Device updates" })).toBeVisible();
});

test("group network exports reported facts with source identity and provenance", async ({ page }) => {
  await login(page);
  await page.goto("/groups");
  await page.getByRole("link", { name: "Workstations", exact: true }).last().click();
  await page.getByRole("button", { name: "Export group network", exact: true }).click();
  const link = page.getByRole("link", { name: /^Download CSV/ });
  await expect(link).toBeVisible();
  const [download] = await Promise.all([page.waitForEvent("download"), link.click()]);
  const path = await download.path();
  const content = await readFile(path!, "utf8");
  expect(content).toContain("source_instance_id");
  expect(content).toContain("network_state");
  expect(content).toContain("derived_cidr");
  expect(content).toContain("not physical topology");
});

test("device investigation retains filters, columns and the active tab across reload", async ({ page }) => {
  await login(page);
  await page.goto("/assets?search=DEMOA-WS001");
  await page.getByRole("table", { name: "DEMO-A assets" }).getByRole("link", { name: "DEMOA-WS001" }).click();
  await page.getByRole("tab", { name: "Network", exact: true }).click();
  await expect(page).toHaveURL(/tab=network/);
  await page.reload();
  await expect(page.getByRole("tab", { name: "Network", exact: true })).toHaveAttribute("aria-selected", "true");
  await page.getByRole("link", { name: "Back to devices" }).click();
  await expect(page.getByRole("searchbox", { name: "Search", exact: true })).toHaveValue("DEMOA-WS001");
  await page.getByText("Columns", { exact: true }).click();
  await page.getByRole("checkbox", { name: "Agent", exact: true }).uncheck();
  await expect(page.getByRole("columnheader", { name: "Agent", exact: true })).toHaveCount(0);
});

test("narrow screens keep tables and tabs inside the viewport and Escape closes navigation", async ({ page }) => {
  await page.setViewportSize({ width: 390, height: 844 });
  await login(page);
  for (const path of ["/assets", "/changes", "/patch-policies"]) {
    await page.goto(path);
    await expect(page.getByRole("heading", { level: 1 }).first()).toBeVisible();
    await page.waitForLoadState("networkidle");
    expect(await page.evaluate("document.documentElement.scrollWidth <= window.innerWidth")).toBe(true);
  }
  const menu = page.getByRole("button", { name: "Menu", exact: true });
  await menu.click();
  await expect(page.getByRole("navigation", { name: "Main" })).toBeVisible();
  await page.keyboard.press("Escape");
  await expect(page.getByRole("navigation", { name: "Main" })).toBeHidden();
  await expect(menu).toBeFocused();
});

test("group assignment proposal requires independent review and never executes a VSA change", async ({ page }) => {
  await login(page);
  await page.goto("/assets?search=DEMOA-WS001");
  await page.getByRole("table", { name: "DEMO-A assets" }).getByRole("link", { name: "DEMOA-WS001" }).click();
  await page.getByRole("tab", { name: "Operations", exact: true }).click();
  await expect(page.getByRole("region", { name: "Propose group move" })).toBeVisible();
  const targets = page.getByLabel("Target group");
  const target = await targets.locator("option").nth(1).getAttribute("value");
  await targets.selectOption(target!);
  await page.getByLabel("Change reason").fill("Correct placement after onboarding review");
  await page.getByRole("button", { name: "Submit proposal" }).click();
  await expect(page.getByRole("status")).toContainText("No VSA change was executed");
  await page.getByRole("button", { name: "Sign out", exact: true }).click();
  await login(page, "demo.admin.a@demo.invalid");
  await page.goto("/group-moves");
  await page.getByRole("row").filter({ hasText: "DEMOA-WS001" }).getByRole("button", { name: "Review proposal" }).click();
  await page.getByLabel("Review reason").fill("Independent review completed; execution remains disabled");
  await page.getByRole("button", { name: "Approve proposal only" }).click();
  await expect(page.getByRole("row").filter({ hasText: "DEMOA-WS001" })).toContainText("approved");
  const customers = await (await page.request.get("/api/v1/customers/")).json();
  const requests = await (await page.request.get(`/api/v1/customers/${customers.results[0].id}/group-moves/`)).json();
  expect(requests.results[0].execution_enabled).toBe(false);
});
