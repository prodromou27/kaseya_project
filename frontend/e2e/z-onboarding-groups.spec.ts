import { expect, test, type Page } from "@playwright/test";
import type { GroupNetwork } from "../src/lib/types";

async function login(page: Page, email: string) {
  await page.goto("/login");
  await page.getByLabel("Email").fill(email);
  await page.getByLabel("Password").fill(process.env.DEMO_USER_PASSWORD ?? "");
  await page.getByRole("button", { name: "Sign in", exact: true }).click();
  await expect(page.getByRole("heading", { name: "Dashboard", exact: true })).toBeVisible();
}

test("onboarding is temporary and reviewed CIDR rules suggest a manual destination", async ({ page }) => {
  await login(page, "demo.admin.a@demo.invalid");
  const customers = await (await page.request.get("/api/v1/customers/")).json();
  const customer = customers.results.find((row: { code: string }) => row.code === "DEMO-A");
  const base = `/api/v1/customers/${customer.id}`;
  const tree = await (await page.request.get(`${base}/hierarchy/`)).json();
  const org = tree.organizations[0];
  const groups: { external_id: string; name: string }[] = org.sites.flatMap((site: { groups: { external_id: string; name: string }[] }) => site.groups);
  const source = groups[0];
  const target = groups[1];
  const sourceUrl = `/groups/${source.external_id}?instance=${org.instance_id}`;
  const targetUrl = `/groups/${target.external_id}?instance=${org.instance_id}`;
  const net: GroupNetwork = await (await page.request.get(`${base}/groups/${source.external_id}/network/?instance=${org.instance_id}`)).json();
  const device = net.devices.find((row) => row.adapters.some((nic) => nic.addresses.some((ip) => ip.version === 4 && ip.kind === "private")))!;
  const ip = device.adapters.flatMap((nic) => nic.addresses).find((ip) => ip.version === 4 && ip.kind === "private")!;
  await page.goto(sourceUrl);
  await page.getByLabel("Use as an onboarding group").check();
  await expect(page.getByText(/Onboarding group: temporary/)).toBeVisible();
  await page.goto(targetUrl);
  await page.getByLabel("Use as an onboarding group").uncheck();
  const reason = `Fixture CIDR destination ${Date.now()}`;
  await page.getByLabel("Subnet (CIDR)").fill(`${ip.address}/32`);
  await page.getByLabel("Reason", { exact: true }).fill(reason);
  await page.getByRole("button", { name: "Propose subnet", exact: true }).click();
  await expect(page.getByRole("row").filter({ hasText: reason })).toContainText("proposed");
  await page.getByRole("button", { name: "Sign out", exact: true }).click();
  await login(page, "demo.superadmin@demo.invalid");
  await page.evaluate((id: string) => sessionStorage.setItem("okp.selectedCustomer", id), customer.id);
  await page.goto(targetUrl);
  await page.getByRole("row").filter({ hasText: reason }).getByRole("button", { name: "Approve", exact: true }).click();
  await expect(page.getByRole("row").filter({ hasText: reason })).toContainText("approved");
  await page.goto(`/assets/${device.asset_id}?tab=operations`);
  await page.getByRole("tab", { name: "Operations", exact: true }).click();
  const suggestions = page.getByRole("region", { name: "CIDR group suggestions" });
  await expect(suggestions).toContainText("valid temporary installation destination");
  await expect(suggestions).toContainText(`${ip.address} in ${ip.address}/32`);
  await suggestions.getByRole("button", { name: `Use ${target.name}`, exact: true }).click();
  await expect(page.getByLabel("Target group")).not.toHaveValue("");
  const actual: GroupNetwork = await (await page.request.get(`${base}/groups/${source.external_id}/network/?instance=${org.instance_id}`)).json();
  expect(actual.devices.some((row) => row.asset_id === device.asset_id)).toBe(true);
  await page.screenshot({ path: "../backend/var/codex-audit/onboarding-group-suggestions.png", fullPage: true });
});
