import { expect, test, type Page } from "@playwright/test";

async function login(page: Page) {
  await page.goto("/login");
  await page.getByLabel("Email").fill("demo.engineer.a@demo.invalid");
  await page.getByLabel("Password").fill(process.env.DEMO_USER_PASSWORD ?? "");
  await page.getByRole("button", { name: "Sign in", exact: true }).click();
  await expect(page.getByRole("heading", { name: "Dashboard", exact: true })).toBeVisible();
}

test("engineer saves a layout and retains it across reload, paging, filtering and investigation", async ({ page }) => {
  await login(page);
  await page.goto("/assets");
  await page.getByLabel("Rows per page").selectOption("25");
  const table = page.getByRole("table", { name: "DEMO-A assets", exact: true });
  await expect(table.locator("tbody tr")).toHaveCount(25);
  await page.getByText("Columns", { exact: true }).click();
  await page.getByRole("checkbox", { name: "Site", exact: true }).uncheck();
  await page.getByLabel("Density").selectOption("comfortable");
  await table.getByRole("button", { name: "Device", exact: true }).click();
  await page.getByText("Saved views", { exact: true }).click();
  const name = `Investigation layout ${Date.now()}`;
  await page.getByLabel("View name").fill(name);
  const [response] = await Promise.all([
    page.waitForResponse((response) => response.url().includes("/saved-views/") && response.request().method() === "POST"),
    page.getByRole("button", { name: "Save view", exact: true }).click(),
  ]);
  expect(response.status()).toBe(201);
  const saved = await response.json();
  expect(saved.layout.columns).not.toContain("site_name");
  expect(saved.layout).toMatchObject({ density: "comfortable", page_size: 25 });
  await expect(page).toHaveURL(new RegExp(`view=${saved.id}`));
  await page.reload();
  await expect(page.getByLabel("Density")).toHaveValue("comfortable");
  await expect(table.getByRole("columnheader", { name: "Site", exact: true })).toHaveCount(0);
  await expect(table.locator("tbody tr")).toHaveCount(25);
  await page.getByRole("button", { name: "Next", exact: true }).click();
  await expect(page).toHaveURL(/page=2/);
  await expect(table.getByRole("columnheader", { name: "Site", exact: true })).toHaveCount(0);
  await page.getByRole("searchbox", { name: "Search", exact: true }).pressSequentially("DEMOA-WS001", { delay: 10 });
  await expect(page.getByRole("searchbox", { name: "Search", exact: true })).toHaveValue("DEMOA-WS001");
  await expect(table.locator("tbody tr")).toHaveCount(1);
  await table.getByRole("link", { name: "DEMOA-WS001", exact: true }).click();
  await page.getByRole("link", { name: "Back to devices", exact: true }).click();
  await expect(page.getByRole("searchbox", { name: "Search", exact: true })).toHaveValue("DEMOA-WS001");
  await expect(page.getByLabel("Density")).toHaveValue("comfortable");
  await expect(table.getByRole("columnheader", { name: "Site", exact: true })).toHaveCount(0);
});

test("group directory filters by site and links the exact source population", async ({ page }) => {
  await login(page);
  await page.goto("/groups");
  await page.getByRole("searchbox", { name: "Search groups", exact: true }).fill("Workstations");
  const site = page.getByRole("combobox", { name: "Site", exact: true });
  const hq = await site.locator("option").filter({ hasText: /^HQ/ }).getAttribute("value");
  await site.selectOption(hq!);
  const table = page.getByRole("table", { name: "Agent groups", exact: true });
  await expect(table.locator("tbody tr")).toHaveCount(1);
  const devices = table.getByRole("link", { name: /devices in Workstations at HQ/ });
  const href = await devices.getAttribute("href");
  expect(href).toMatch(/group_id=20011&instance=/);
  await devices.click();
  await expect(page).toHaveURL(/group_id=20011&instance=/);
  await expect(page.getByRole("button", { name: "Remove Group filter" })).toBeVisible();
  await expect(page.getByRole("table", { name: "DEMO-A assets" })).toBeVisible();
  const customers = await (await page.request.get("/api/v1/customers/")).json();
  const params = new URL(href!, "http://fixture.invalid").searchParams;
  const population = await (await page.request.get(`/api/v1/customers/${customers.results[0].id}/assets/?${params}`)).json();
  expect(population.count).toBe(75);
  await page.goBack();
  await expect(page.getByRole("searchbox", { name: "Search groups", exact: true })).toHaveValue("Workstations");
  await page.goBack();
  await expect(page.getByRole("combobox", { name: "Site", exact: true })).toHaveValue("");
  await expect(page.getByRole("table", { name: "Agent groups" }).locator("tbody tr")).toHaveCount(2);

});

test("phone list controls stay in the viewport and keyboard search recovers empty results", async ({ page }) => {
  await page.setViewportSize({ width: 390, height: 844 });
  await login(page);
  await page.goto("/assets?page=999");
  await page.getByRole("button", { name: "Return to first page", exact: true }).click();
  await expect(page).not.toHaveURL(/page=999/);
  const search = page.getByRole("searchbox", { name: "Search", exact: true });
  await search.fill("NO-SUCH-FIXTURE-DEVICE");
  await expect(page.getByText("No devices match your filters.", { exact: true })).toBeVisible();
  await page.getByRole("button", { name: "Clear filters and show all devices", exact: true }).click();
  await expect(page.getByRole("table", { name: "DEMO-A assets" })).toBeVisible();
  expect(await page.evaluate("document.documentElement.scrollWidth <= innerWidth")).toBe(true);
  const more = page.getByText("More filters", { exact: true });
  await more.focus();
  await page.keyboard.press("Enter");
  await expect(page.getByRole("combobox", { name: "Group", exact: true })).toBeVisible();
});
