// Fixture-only visual review. Run against the locally seeded stack, never a customer deployment.
// DEMO_USER_PASSWORD=... node e2e/audit-review.mjs <output-directory>
import { chromium } from "@playwright/test";
import { mkdir, writeFile } from "node:fs/promises";

const out = process.argv[2];
if (!out || !process.env.DEMO_USER_PASSWORD) throw new Error("Output directory and DEMO_USER_PASSWORD required.");
const browser = await chromium.launch();
const page = await browser.newPage({ baseURL: "http://127.0.0.1:5173", viewport: { width: 1440, height: 960 } });
const errors = [];
page.on("pageerror", (error) => errors.push(error.message));
await mkdir(out, { recursive: true });
await page.goto("http://127.0.0.1:5173/login");
await page.getByLabel("Email").fill("demo.superadmin@demo.invalid");
await page.getByLabel("Password").fill(process.env.DEMO_USER_PASSWORD);
await page.getByRole("button", { name: "Sign in", exact: true }).click();
await page.getByRole("heading", { name: "Dashboard", exact: true }).waitFor();
const customers = await (await page.request.get("/api/v1/customers/?page_size=200")).json();
const customer = customers.results.find((c) => c.code === "DEMO-A");
await page.getByLabel("Customer", { exact: true }).selectOption(customer.id);
const assets = await (await page.request.get(`/api/v1/customers/${customer.id}/assets/`)).json();
const hierarchy = await (await page.request.get(`/api/v1/customers/${customer.id}/hierarchy/`)).json();
if (!assets.results.length) throw new Error("Seed, approve and synchronize the DEMO-A fixture before visual review.");
const paths = [
  ["dashboard", "/"], ["devices", "/assets"], ["device-detail", `/assets/${assets.results[0].id}`],
  ["software", "/software"], ["windows-updates", "/windows-updates"], ["onboarding", "/onboarding"],
  ["groups", "/groups"], ["reports", "/reports"], ["settings", "/admin"],
  ["health", "/device-health"], ["changes", "/changes"], ["notifications", "/notifications"],
  ["policies", "/patch-policies"], ["group-moves", "/group-moves"], ["lifecycle", "/lifecycle"], ["customers", "/customers"],
];
const firstGroup = hierarchy.organizations.flatMap((organization) => organization.sites).flatMap((site) => site.groups)[0];
if (firstGroup) paths.push(["group-network", `/groups/${firstGroup.external_id}?instance=${firstGroup.instance_id}`]);
const observations = [];
for (const width of [1440, 390]) {
  await page.setViewportSize({ width, height: width === 390 ? 844 : 960 });
  for (const [name, path] of paths) {
    await page.goto(`http://127.0.0.1:5173${path}`);
    await page.waitForLoadState("networkidle");
    await page.getByRole("heading", { level: 1 }).first().waitFor();
    await page.screenshot({ path: `${out}/${name}-${width}.png`, fullPage: true });
    observations.push({
      name, width, path,
      ...await page.evaluate(() => ({
        documentWidth: document.documentElement.scrollWidth,
        viewportWidth: window.innerWidth,
        alerts: [...document.querySelectorAll('[role="alert"]')].map((el) => el.textContent),
      })),
    });
  }
}
await writeFile(`${out}/observations.json`, JSON.stringify({ fixture: true, errors, observations }, null, 2));
await browser.close();
console.log(JSON.stringify({ screenshots: observations.length, errors, overflows: observations.filter((o) => o.documentWidth > o.viewportWidth) }));
