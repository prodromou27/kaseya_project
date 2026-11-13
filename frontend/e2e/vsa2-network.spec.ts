import { expect, test, type Page } from "@playwright/test";

/**
 * VSA2-05 expected subnets on the fixture demo stack (runs after p1.spec.ts synced DEMO-A). Fixture only.
 * HQ/Servers (group 20012) devices use 10.1.10.(10+index); with 10.1.10.0/25 expected, only DEMOA-SRV119
 * (10.1.10.129) is outside.
 */
const PASSWORD = process.env.DEMO_USER_PASSWORD ?? "";

async function login(page: Page, email: string) {
  await page.goto("/login");
  await page.getByLabel("Email").fill(email);
  await page.getByLabel("Password").fill(PASSWORD);
  await page.getByRole("button", { name: "Sign in" }).click();
  await expect(page.getByRole("heading", { name: "Dashboard" })).toBeVisible();
}

test("expected subnet needs a second administrator and then flags outside addresses", async ({ page }) => {
  await login(page, "demo.admin.a@demo.invalid");
  await page.goto("/groups/20012");
  const flags = page.getByRole("list", { name: "Review flags" });
  await expect(flags.getByRole("listitem").filter({ hasText: "outside the expected subnets" })).toContainText("not evaluated");
  await page.getByLabel("Subnet (CIDR)").fill("10.1.10.0/25");
  await page.getByLabel("Reason").fill("HQ server range (E2E)");
  await page.getByRole("button", { name: "Propose subnet" }).click();
  const table = page.getByRole("table", { name: "Expected subnets" });
  await expect(table).toContainText("proposed");
  await table.getByRole("button", { name: "Approve" }).click();
  await expect(page.getByRole("alert")).toContainText("A different administrator must approve");
  await page.getByRole("button", { name: "Sign out" }).click();

  await login(page, "demo.superadmin@demo.invalid");
  const value = await page.locator("#customer-selector option", { hasText: "DEMO-A" }).getAttribute("value");
  await page.locator("#customer-selector").selectOption(value ?? "");
  await page.goto("/groups/20012");
  await page.getByRole("table", { name: "Expected subnets" }).getByRole("button", { name: "Approve" }).click();
  const outside = page.getByRole("table", { name: "Addresses outside expected subnets" });
  await expect(outside).toContainText("DEMOA-SRV119");
  await expect(outside).toContainText("10.1.10.129");
  await expect(page.getByRole("list", { name: "Review flags" }).getByRole("listitem").filter({ hasText: "outside the expected subnets" })).toContainText("1");
});
