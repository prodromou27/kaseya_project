import { expect, test, type Page } from "@playwright/test";
import { readFile } from "node:fs/promises";

async function login(page: Page) {
  await page.goto("/login");
  await page.getByLabel("Email").fill("demo.engineer.a@demo.invalid");
  await page.getByLabel("Password").fill(process.env.DEMO_USER_PASSWORD ?? "");
  await page.getByRole("button", { name: "Sign in", exact: true }).click();
  await expect(page.getByRole("heading", { name: "Dashboard", exact: true })).toBeVisible();
}

test("software investigation finds a device and returns to the same filters", async ({ page }) => {
  await login(page);
  await page.goto("/software?view=installations&state=");
  await page.getByRole("searchbox", { name: "Search", exact: true }).pressSequentially("DEMOA-WS001", { delay: 10 });
  const table = page.getByRole("table", { name: "Software installations", exact: true });
  await expect(table).toContainText("DEMOA-WS001");
  await table.getByRole("link", { name: "DEMOA-WS001", exact: true }).first().click();
  await expect(page.getByRole("tab", { name: /Installed software/ })).toHaveAttribute("aria-selected", "true");
  await page.reload();
  await page.getByRole("link", { name: "Back to software", exact: true }).click();
  await expect(page.getByRole("searchbox", { name: "Search", exact: true })).toHaveValue("DEMOA-WS001");
  await expect(page.getByRole("tab", { name: "Installations", exact: true })).toHaveAttribute("aria-selected", "true");
});

test("Windows coverage pages all devices and exports collection evidence", async ({ page }) => {
  await login(page);
  await page.goto("/windows-updates?view=coverage");
  await page.getByLabel("Rows per page").selectOption("25");
  await page.getByRole("button", { name: "Last", exact: true }).click();
  await expect(page.getByRole("table", { name: "Device collection coverage" }).locator("tbody tr")).toHaveCount(5);
  await page.getByRole("combobox", { name: "Available-update collection", exact: true }).selectOption("not_collected");
  await expect(page).not.toHaveURL(/page=6/);
  await expect(page.getByRole("button", { name: "Export update records", exact: true })).toHaveCount(0);
  await page.getByRole("button", { name: "Export device coverage", exact: true }).click();
  const download = page.getByRole("link", { name: /Download CSV/ });
  await expect(download).toBeVisible();
  const [file] = await Promise.all([page.waitForEvent("download"), download.click()]);
  const csv = await readFile((await file.path())!, "utf8");
  expect(csv).toContain("available_status");
  expect(csv).toContain("not_collected");
  expect(csv).not.toContain("DEMOB-");
});

test("update record search retains the investigation origin through device details", async ({ page }) => {
  await login(page);
  await page.goto("/windows-updates");
  const table = page.getByRole("table", { name: "Device updates", exact: true });
  await expect(table).toBeVisible();
  const hostname = await table.locator("tbody tr").first().getByRole("link").first().innerText();
  await page.getByRole("searchbox", { name: "Search updates", exact: true }).fill(hostname);
  await expect(table).toContainText(hostname);
  await table.getByRole("link", { name: hostname, exact: true }).first().click();
  await expect(page.getByRole("tab", { name: "OS updates", exact: true })).toHaveAttribute("aria-selected", "true");
  await page.getByRole("link", { name: "Back to Windows updates", exact: true }).click();
  await expect(page.getByRole("searchbox", { name: "Search updates", exact: true })).toHaveValue(hostname);
});
