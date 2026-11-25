// Ad-hoc UI review helper (not a test): one page as one user. Usage: node e2e/shot-one.mjs <out.png> <email> <path> [customer]
// Optional: E2E_BASE_URL (default http://localhost:5173), SHOT_WIDTH (default 1440).
import { chromium } from "@playwright/test";

const [out, email, path, customerLabel] = process.argv.slice(2);
const BASE = process.env.E2E_BASE_URL ?? "http://localhost:5173";
const browser = await chromium.launch();
const page = await browser.newPage({ viewport: { width: Number(process.env.SHOT_WIDTH ?? 1440), height: 900 } });
await page.goto(`${BASE}/login`);
await page.getByLabel("Email").fill(email);
await page.getByLabel("Password").fill(process.env.DEMO_USER_PASSWORD ?? "");
await page.getByRole("button", { name: "Sign in" }).click();
await page.getByRole("heading", { name: "Dashboard" }).waitFor();
if (customerLabel) {
  const select = page.locator("#customer-selector");
  await select.selectOption(await select.locator("option", { hasText: customerLabel }).first().getAttribute("value"));
}
await page.goto(`${BASE}${path}`);
await page.waitForLoadState("networkidle");
await page.waitForTimeout(700);
await page.screenshot({ path: out, fullPage: true });
await browser.close();
