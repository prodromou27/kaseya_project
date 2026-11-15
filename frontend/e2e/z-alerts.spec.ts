import { expect, test, type Page } from "@playwright/test";

async function login(page: Page, email: string) {
  await page.goto("/login");
  await page.getByLabel("Email").fill(email);
  await page.getByLabel("Password").fill(process.env.DEMO_USER_PASSWORD ?? "");
  await page.getByRole("button", { name: "Sign in", exact: true }).click();
  await expect(page.getByRole("heading", { name: "Dashboard", exact: true })).toBeVisible();
}

test("an engineer adds, pauses and resumes watches and opens the alerts list from the bell", async ({ page }) => {
  await login(page, "demo.engineer.a@demo.invalid");
  // Start from no watches so the test can be repeated.
  const csrf = (await page.context().cookies()).find((c) => c.name.includes("csrf"))?.value ?? "";
  for (const w of await (await page.request.get("/api/v1/alert-subscriptions/")).json()) {
    await page.request.delete(`/api/v1/alert-subscriptions/${w.id}/`, { headers: { "X-CSRFToken": csrf } });
  }
  await page.getByRole("link", { name: /^Alerts/ }).click();
  await page.getByRole("tab", { name: "My watches", exact: true }).click();
  const form = page.getByRole("form", { name: "Add watch" });
  await form.getByLabel("Alert me when").selectOption("offline");
  await form.getByLabel("Days").fill("1");
  await form.getByRole("button", { name: "Add watch" }).click();
  await expect(page.getByRole("list", { name: "My watches" })).toContainText("Device not seen for more than 1 days");
  await form.getByLabel("Alert me when").selectOption("new_device");
  await form.getByRole("button", { name: "Add watch" }).click();
  await expect(page.getByRole("list", { name: "My watches" })).toContainText("New device appears");
  // Pausing and resuming keeps the watch.
  const watch = page.getByRole("list", { name: "My watches" }).getByRole("listitem").filter({ hasText: "New device appears" });
  const patched = () => page.waitForResponse((r) => r.request().method() === "PATCH" && r.url().includes("/alert-subscriptions/"));
  await page.waitForLoadState("networkidle"); // let the list settle after the second add
  await Promise.all([patched(), watch.getByRole("button", { name: "Pause" }).click()]);
  await expect(watch).toContainText("(paused)");
  await Promise.all([patched(), watch.getByRole("button", { name: "Resume" }).click()]);
  await expect(watch).not.toContainText("(paused)");
  await page.getByRole("tab", { name: "Alerts", exact: true }).click();
  await expect(page.getByRole("tabpanel")).toContainText(/No alerts yet|Mark all as read/);
});
