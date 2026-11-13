// Ad-hoc UI review helper (not a test): signs in and screenshots every main page. Usage:
//   node e2e/shots.mjs <out-dir> <email>
import { chromium } from "@playwright/test";

const [outDir, email] = process.argv.slice(2);
const PASSWORD = process.env.DEMO_USER_PASSWORD ?? "";
const BASE = "http://localhost:5173";
const pages = [
  "/", "/customers", "/assets", "/software", "/windows-updates", "/patch-policies", "/device-health", "/changes",
  "/notifications", "/groups", "/onboarding", "/reports", "/admin", "/admin?tab=integrations",
];

const browser = await chromium.launch();
const page = await browser.newPage({ viewport: { width: 1440, height: 900 } });
await page.goto(`${BASE}/login`);
await page.getByLabel("Email").fill(email);
await page.getByLabel("Password").fill(PASSWORD);
await page.getByRole("button", { name: "Sign in" }).click();
await page.getByRole("heading", { name: "Dashboard" }).waitFor();
const customerLabel = process.argv[4];
if (customerLabel) {
  const select = page.locator("#customer-selector");
  const value = await select.locator("option", { hasText: customerLabel }).first().getAttribute("value");
  await select.selectOption(value);
}
for (const path of pages) {
  await page.goto(`${BASE}${path}`);
  await page.waitForLoadState("networkidle");
  await page.waitForTimeout(600);
  const name = path === "/" ? "dashboard" : path.slice(1).replace(/[/?=]/g, "_");
  await page.screenshot({ path: `${outDir}/${name}.png`, fullPage: true });
}
// First device detail and first customer detail.
await page.goto(`${BASE}/assets`);
await page.waitForLoadState("networkidle");
const firstAsset = page.locator('a[href^="/assets/"]').first();
if (await firstAsset.count()) {
  await firstAsset.click();
  await page.waitForLoadState("networkidle");
  await page.waitForTimeout(600);
  await page.screenshot({ path: `${outDir}/asset_detail.png`, fullPage: true });
}
await page.goto(`${BASE}/customers`);
await page.waitForLoadState("networkidle");
const firstCustomer = page.locator('a[href^="/customers/"]').first();
if (await firstCustomer.count()) {
  await firstCustomer.click();
  await page.waitForLoadState("networkidle");
  await page.waitForTimeout(600);
  await page.screenshot({ path: `${outDir}/customer_detail.png`, fullPage: true });
}
// Narrow (phone) width of the dashboard.
await page.setViewportSize({ width: 390, height: 844 });
await page.goto(`${BASE}/`);
await page.waitForLoadState("networkidle");
await page.screenshot({ path: `${outDir}/dashboard_mobile.png`, fullPage: true });
await browser.close();
